"""
行为脑 —— 画面的默认持有者。

它只干三件事：
  1. 一直跑当前 skill，把吐出来的字【流式】转发给下游（TTS / 推流）
  2. 被大脑抢占时停止吐字（不做"暂停音频"这种事，就是停下不说话）
  3. 支持切换 skill（卖货 ↔ 以后的其他才艺）

状态机只有三条边：

    idle ──选中 skill──→ performing
    performing ──大脑抢画面──→ suppressed
    suppressed ──大脑说完释放──→ performing
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from core.shared import SharedState
from performance.skill import Skill

log = logging.getLogger("perform")

# 吐出一段字之后交给谁（接 TTS 前，先打印）
OnText = Callable[[str], Awaitable[None]]


class PerformBrain:
    def __init__(
        self,
        shared: SharedState | None = None,
        on_text: OnText | None = None,
    ):
        self.shared = shared
        self.on_text = on_text or self._default_sink

        self.mode = "idle"                    # idle / performing / suppressed
        self.current: Skill | None = None

        # 统计（turns 对"永不结束"的 skill 没意义，换成这两个）
        self.emitted = 0                      # 一共吐了多少段字
        self.interrupts = 0                   # 被抢了几次

        self._skills: dict[str, Skill] = {}
        self._pending: str | None = None      # 待切换的 skill id
        self._resume = asyncio.Event()
        self._resume.set()                    # 初始：未被压制
        self._started_at = 0.0

        # ★ 网页「暂停」按钮的状态位：
        #   True 期间，就算大脑说完放画面（resume），也不恢复卖货 ——
        #   不加这个，'暂停'会被下一批弹幕悄悄解除（2026-10-16 实测踩过）
        self.用户暂停 = False

    # ── 注册 / 切换 ──────────────────────────────────
    def register(self, skill: Skill) -> None:
        self._skills[skill.id] = skill
        log.info("注册才艺：%s（id=%s）", skill.name, skill.id)

    def switch_to(self, skill_id: str) -> None:
        """请求切换。会在当前这句吐完之后生效，不打断正在说的字。"""
        if skill_id not in self._skills:
            raise KeyError(f"没有这个才艺：{skill_id}，已注册：{list(self._skills)}")
        self._pending = skill_id

    # ── 抢占 / 释放（由大脑调用）─────────────────────
    async def interrupt(self) -> None:
        """大脑抢画面 —— 立刻停止吐字。"""
        if self.mode == "suppressed":
            return
        self.mode = "suppressed"
        self.interrupts += 1
        self._resume.clear()
        self._sync()
        log.info("【被抢占】停止吐字")

    async def resume(self) -> None:
        """大脑说完 —— 恢复吐字。（网页手动暂停期间：不恢复！）"""
        if self.用户暂停:
            return                            # 手动暂停优先：弹幕抢完画面也不自动恢复
        if self.mode != "suppressed":
            return
        self.mode = "performing"
        self._resume.set()
        self._sync()
        log.info("【恢复】继续吐字")

    # ── 状态快照（共享层，大脑读）────────────────────
    def _sync(self) -> None:
        if not self.shared:
            return
        self.shared.perform.update({
            "mode": self.mode,
            "skill_id": self.current.id if self.current else None,
            "started_at": self._started_at,
            "interruptible": True,
            "interrupt_in": 0.0,
        })

    # ── 主循环 ───────────────────────────────────────
    async def loop(self) -> None:
        while True:
            # 1. 被压制 → 挂着等（事件驱动，零轮询开销）
            if self.mode == "suppressed":
                await self._resume.wait()
                continue

            # 2. 处理切换请求
            if self._pending:
                self.current = self._skills[self._pending]
                self._pending = None
                self._started_at = time.time()
                log.info("切换才艺 → %s", self.current.name)

            # 3. 没有 skill → 待机
            if self.current is None:
                await asyncio.sleep(0.5)
                continue

            # 4. 跑当前 skill，流式吐字
            self.mode = "performing"
            self._sync()
            try:
                async for piece in self.current.stream():
                    # ★ 每吐一段检查一次：被抢了？要换才艺了？
                    if self.mode == "suppressed" or self._pending:
                        break
                    await self.on_text(piece)
                    self.emitted += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("才艺出错，1 秒后重试：%s", e)
                await asyncio.sleep(1)
                continue

    # ── 默认下游：先打印（接 TTS 时替换掉）────────────
    @staticmethod
    async def _default_sink(text: str) -> None:
        print(f"  [吐字] {text}")
