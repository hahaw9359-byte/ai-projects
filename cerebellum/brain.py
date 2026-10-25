"""
小脑主控 —— 5 个 Task + 4 个 Queue 的流水线。

Task 拓扑（→ 表示 Queue，箭头方向是数据流向）：

    source ─→ recv_loop ─→ raw_q ─→ filter_loop ─→ window.feed
                                                        │
                                      window.run ─→ audit_q
                                                        │
                                                        ▼
                                                   audit_loop ─→ brain_q（交给大脑）

    + gc_loop（可选）：每 60s 清一次过滤器里的按用户累积状态

为什么必须拆成多条 Task —— 一句话：**快慢分离。**

    recv   接弹幕       微秒级，绝不能阻塞（B站会踢掉卡住的连接）
    filter 硬过滤       微秒级，纯 CPU
    window 攒批         秒级，等它该等的
    audit  LLM 审核     百毫秒~秒级，慢

如果把它们写在一个 while 里，LLM 那一秒的等待会让弹幕接收停摆。
拆开之后：**接收永远不卡，审核慢慢磨。**
"""
from __future__ import annotations

import asyncio
import logging
import time

from core import logfile
from core.knowledge import 像在问产品吗
from core.shared import SharedState
from core.types import BrainPayload, DROP, RawMessage, SUSPECT
from cerebellum.audit import NullAuditor
from cerebellum.filters import FilterPipeline, default_pipeline
from cerebellum.window import BatchWindow

log = logging.getLogger("cere.核心")


class Cerebellum:
    def __init__(
        self,
        source,
        out_q: asyncio.Queue,
        *,
        memory=None,
        弹幕记忆=None,
        开智=None,
        auditor=None,
        shared: SharedState | None = None,
        pipeline: FilterPipeline | None = None,
        batch_n: int = 5,
        batch_t: float = 5.0,
        raw_q_size: int = 200,
        gc_interval: float = 60.0,
    ):
        self.source = source
        self.out_q = out_q                      # 交给大脑的队列
        self.memory = memory                    # UserMemory：提炼过的长期事实
        self.弹幕记忆 = 弹幕记忆                  # 弹幕日志文件当记忆空间（重启不丢）
        self.开智 = 开智                        # 可选：粗筛命中时问一次模型，提纯"观众想问的产品"
        self.auditor = auditor or NullAuditor()
        self.shared = shared
        self.pipeline = pipeline or default_pipeline()

        self.raw_q: asyncio.Queue[RawMessage] = asyncio.Queue(maxsize=raw_q_size)
        self.audit_q: asyncio.Queue[list[RawMessage]] = asyncio.Queue(maxsize=50)
        self.window = BatchWindow(self.audit_q, n=batch_n, t=batch_t)
        self._gc_interval = gc_interval

        # 统计，方便一眼看出过滤链条的工作情况
        self.stats = {"in": 0, "drop": 0, "suspect": 0, "out": 0}
        # 丢弃打印用的蓄水池（合并打印，防刷屏）
        self._丢蓄: dict[str, int] = {}
        self._上次丢报 = 0.0
        self._丢最近 = ""

    # ── 入口 ─────────────────────────────────────────
    async def run(self) -> None:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._recv_loop(), name="cere-recv")
            tg.create_task(self._filter_loop(), name="cere-filter")
            tg.create_task(self.window.run(), name="cere-window")
            tg.create_task(self._audit_loop(), name="cere-audit")
            tg.create_task(self._gc_loop(), name="cere-gc")

    # ── Task A：接弹幕 ───────────────────────────────
    async def _recv_loop(self) -> None:
        """★ 就是这里：把弹幕 put 进队列（第 79 行起）。

        从 source 取一条 → put 进 raw_q → 回去取下一条。
        只做 O(1) 的搬运，任何情况下都不能在这里 await 慢操作。
        """
        while True:
            try:
                async for msg in self.source:
                    # ★ 文件日志：弹幕源拿出来的每条都记一笔。
                    #   它和源层的 [抓到] 配对 —— 两条都有 = 消息确实过了线程边界；
                    #   只有 [抓到] 没有 [小脑收到] = 卡在中间（几乎不可能，但摆出来就是证据）。
                    logfile.写(f"[小脑收到] {msg.kind} | {msg.user_name}：{msg.text[:50]}")
                    try:
                        self.raw_q.put_nowait(msg)
                    except asyncio.QueueFull:
                        # 背压：高峰时丢最老的，保证新弹幕一定进得来
                        try:
                            self.raw_q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        self.raw_q.put_nowait(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 不让异常杀掉这条循环（否则 TaskGroup 会把整个小脑一起停掉）。
                # 注意：真正的"重连"能力在 source 自己内部，这里只是给它再被调用的机会。
                log.warning("弹幕源出错，3 秒后重试：%s", e)
                await asyncio.sleep(3)

    # ── Task B：硬过滤 ───────────────────────────────
    async def _filter_loop(self) -> None:
        """纯 CPU，微秒级。DROP 的当场丢，其余进攒批窗口。"""
        while True:
            msg = await self.raw_q.get()
            self.stats["in"] += 1

            verdict = self.pipeline.run(msg)
            msg.verdict = verdict

            if verdict == DROP:
                self.stats["drop"] += 1
                log.debug("DROP | %s | %s", msg.user_name, msg.text[:20])
                self._报丢弃(msg, self.pipeline.上次丢弃原因)   # ★ 让丢弃看得见
                continue
            if verdict == SUSPECT:
                self.stats["suspect"] += 1
                log.debug("SUSPECT | %s | %s", msg.user_name, msg.text[:20])

            # 礼物走插队通道，不参与攒批
            urgent = msg.kind != "danmaku"
            await self.window.feed(msg, urgent=urgent)

    # ── Task C：审核 + 检索 + 投递 ────────────────────
    async def _audit_loop(self) -> None:
        """慢路径。所有会等 IO 的事都在这里，前面两个 Task 不受影响。"""
        while True:
            batch = await self.audit_q.get()

            safe = await self.auditor.audit(batch)
            clean = [m for m in batch if m.seq in safe]
            if not clean:
                continue

            # ① 写会话 buffer —— 原文全量追加，零成本，不做任何判断。
            #    真正的"提炼成长期事实"由大脑在异步任务里做，不在这里。
            if self.shared:
                for m in clean:
                    self.shared.push(m.user_id, {"text": m.text, "ts": m.ts, "kind": m.kind})

            # ② 定 primary_user：有礼物 → 礼物用户；否则 → 最后发言的人。
            primary = self._pick_primary(clean)

            # ③ 检索这个人的历史事实。query 就是他说的话 —— 小脑手上正好有。
            memories: list[str] = []
            if self.memory:
                query = " / ".join(m.text for m in clean if m.user_id == primary.user_id)
                memories = await self.memory.search(primary.user_id, query)

            # ★ 弹幕记忆：这个人之前在直播间说过什么（SQLite —— 重启不丢、不常驻内存）
            #   和上面的 UserMemory 分工：
            #     UserMemory  = 提炼过的"事实"（他喜欢周杰伦）
            #     弹幕记忆     = 原始发言（他 14:30 说过"有货吗"）
            #   ★ 没有"刷新"这一步了：SQL 版收到就写、查的时候直接读库 ——
            #     旧版要先把文件新增部分读进内存，那正是吃内存的那一步。
            #   ★ 查的是 primary.user_id（uid），和 UserMemory / shared 同一套身份。
            if self.弹幕记忆 is not None:
                try:
                    本批文本 = {m.text.strip() for m in clean}
                    历史 = [(t, c) for t, c in self.弹幕记忆.检索(primary.user_id, 最近几条=12)
                            if c not in 本批文本]   # 正在处理的这批不算"历史"
                    if 历史:
                        串 = "、".join(f"（{t}）「{c}」" for t, c in 历史[-6:])
                        memories.append(f"他/她之前在直播间说过：{串}")
                except Exception:
                    pass                          # 记忆只是旁路，坏了不能影响主线

            # ★ 小脑开智：先粗筛，命中才问模型"观众想问什么产品"
            #   为什么放在这儿：_audit_loop 本来就是慢路径（见文件头），
            #     加一次 IO 不影响收包/过滤——画面在别的线程，更不受影响。
            #   为什么要提纯：知识库检索的分母是 query 的 2-gram 总数。
            #     一整段"送礼+哈哈+闲聊"会把覆盖率稀释到阈值以下，
            #     明明有产品问题也检索不到；提纯成"362L 有膜吗"命中率立刻回来。
            产品线索 = ""
            if self.开智 is not None:
                整批文本 = " / ".join(m.text for m in clean)
                if 像在问产品吗(整批文本):
                    产品线索 = await self._开智提取(整批文本)

            payload = BrainPayload(
                messages=clean,
                memories=memories,
                primary_user=primary.user_id,
                primary_name=primary.user_name,
                产品线索=产品线索,
            )
            self._put_brain(payload)
            self.stats["out"] += 1
            log.info(
                "→ 大脑 | %s | %d 条 | 记忆 %d 条 | %s",
                primary.user_name, len(clean), len(memories), payload.text[:36],
            )
            print(f"      [小脑] → 交大脑 {len(clean)} 条 | {primary.user_name}：{payload.text[:24]}")
            logfile.写(f"[交大脑] {len(clean)} 条 | {primary.user_name}：{payload.text[:60]}")
            if 产品线索:
                print(f"      [小脑·开智] 产品线索 → {产品线索}", flush=True)

    # ── 小脑开智：把"一锅粥"提纯成一句话 ─────────────
    _开智提示 = """从下面的直播弹幕里，找出观众想问的产品。
只输出产品名或型号，最多 15 个字；没有产品问题就输出"无"。
不要解释，不要加引号。

弹幕：{文本}"""

    async def _开智提取(self, 整批文本: str) -> str:
        """返回提纯后的产品线索；任何失败都返回空串（退回整批检索）。

        ★ 失败必须降级、不能抛：小脑是旁路，它挂了不能带走整条弹幕链路。
        ★ 截断到 300 字：一批弹幕不会太长，防的是有人粘贴长文。
        """
        try:
            出: list[str] = []
            async for 片 in self.开智.stream(self._开智提示.format(文本=整批文本[:300])):
                出.append(片)
            文 = "".join(出).strip().strip('"“”\'` ')
            if not 文 or 文 in ("无", "没有", "none", "None", "N/A"):
                return ""
            return 文[:30]
        except asyncio.CancelledError:
            raise                      # 取消要往上抛，不能吞
        except Exception as e:
            print(f"      [小脑·开智] 失败（{type(e).__name__}: {e}）→ 退回整批检索")
            return ""

    # ── 丢弃要看得见 ─────────────────────────────────
    def _报丢弃(self, msg: RawMessage, 原因: str) -> None:
        """弹幕被丢时打一行（1 秒最多一行，合并计数），同时写文件日志。

        为什么必须打印：静默丢弃在观众那边的表现就是"我发的弹幕没人理"，
        排查时完全没有线索。这行字就是要让"为什么没回应"一眼有答案。
        """
        现在 = time.monotonic()
        self._丢蓄[原因] = self._丢蓄.get(原因, 0) + 1
        self._丢最近 = msg.text[:16]
        logfile.写(f"[丢弃] {msg.user_name}：{msg.text[:40]}（{原因}）")
        if 现在 - self._上次丢报 >= 1.0:
            self._上次丢报 = 现在
            明细 = " ".join(f"{k}×{v}" for k, v in self._丢蓄.items())
            print(f"      [小脑] 丢弃 {sum(self._丢蓄.values())} 条（{明细}）"
                  f"最近一条：「{self._丢最近}」")
            self._丢蓄.clear()

    # ── Task D：定期清理 ─────────────────────────────
    async def _gc_loop(self) -> None:
        while True:
            await asyncio.sleep(self._gc_interval)
            self.pipeline.gc()

    # ── 工具 ─────────────────────────────────────────
    @staticmethod
    def _pick_primary(msgs: list[RawMessage]) -> RawMessage:
        """挑"这批该回应谁"。优先级：醒目留言 > 礼物 > 弹幕 > 点赞。

        为什么点赞垫底：点赞量大且没内容，如果它抢了 primary，
        观众真问的问题（"有2000目的吗"）就轮不到被回答 ——
        商品检索的 query 也是拿 primary 的话去查的，会查空。
        """
        for kind in ("superchat", "gift"):
            for m in msgs:
                if m.kind == kind:
                    return m
        for m in reversed(msgs):
            if m.kind == "danmaku":
                return m
        return msgs[-1]

    def _put_brain(self, payload: BrainPayload) -> None:
        """给大脑投递，同样带背压 —— 大脑忙不过来时丢最老的，不无限堆积。"""
        while True:
            try:
                self.out_q.put_nowait(payload)
                return
            except asyncio.QueueFull:
                try:
                    self.out_q.get_nowait()
                except asyncio.QueueEmpty:
                    continue                      # 队列刚被消费空，重试一次
