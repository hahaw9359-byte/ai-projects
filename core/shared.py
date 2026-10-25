"""
三脑共享层。

一条铁律：**一个数据块只有一个写者。**
共享 ≠ 大家都能写，而是"各自把自己那一块的出口状态暴露出来"。

    perform  : 行为脑写，大脑读（覆盖写，只保留最新一帧）
    dialog   : 小脑写，大脑读（per-user 追加，零成本）

这样每个脑只多做一件事，不存在同步 / 竞态 / 类型不一致的问题。
"""
from __future__ import annotations

from collections import deque


class SharedState:
    def __init__(self, dialog_window: int = 20):
        self._dialog_window = dialog_window

        # ── 行为脑写、大脑读 ────────────────────────────
        # 覆盖写。大脑激活时读一次快照就够，不需要订阅变化。
        self.perform: dict = {
            "mode": "idle",          # idle / performing / suppressed
            "skill_id": None,
            "started_at": 0.0,
            "interruptible": True,
            "interrupt_in": 0.0,     # 距下一个可中断点还剩几秒
        }

        # ── 小脑写、大脑读 ──────────────────────────────
        # per-user 的最近若干条原文。小脑只追加，不做任何判断。
        self.dialog: dict[str, deque] = {}

    def snapshot(self) -> dict:
        """大脑激活时调一次。返回副本，防止调用方误改共享状态。"""
        return dict(self.perform)

    def push(self, user_id: str, item: dict) -> None:
        """小脑调：原文入 buffer，零成本。"""
        self.dialog.setdefault(user_id, deque(maxlen=self._dialog_window)).append(item)

    def recent(self, user_id: str) -> list[dict]:
        return list(self.dialog.get(user_id, ()))

    def dump(self) -> dict:
        """排障用：一个调用就能看到三脑各自的状态。"""
        return {
            "perform": dict(self.perform),
            "dialog_users": len(self.dialog),
            "dialog_total": sum(len(v) for v in self.dialog.values()),
        }
