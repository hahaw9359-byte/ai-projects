"""
小脑冒烟测试 —— 用假弹幕跑通 5 Task 流水线，把过滤效果打出来。

跑法（在 vtuber/ 目录下）：
    python run_cerebellum.py          # 跑 20 秒
    python run_cerebellum.py 60       # 跑 60 秒

你会看到四类输出：
    [统计]  每 5 秒一次，看清 DROP / SUSPECT / 投递 的比例
    [大脑]  模拟大脑消费，含 0.8 秒"抢画面+说话"耗时
    [收尾]  共享层 dump，验证 buffer 确实在按 user 累积
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from core.memory import UserMemory
from core.shared import SharedState
from core.types import BrainPayload
from cerebellum import Cerebellum, MockSource, NullAuditor

# 全部走 stdout，否则日志(stderr)和 print(stdout)混流会看不出先后时序
sys.stdout.reconfigure(line_buffering=True)      # 管道输出也逐行刷，时序才准
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("cere.audit").setLevel(logging.WARNING)


async def brain_stub(q: asyncio.Queue) -> None:
    """假装是大脑：消费 payload，模拟 0.8s 的处理耗时。"""
    while True:
        payload: BrainPayload = await q.get()
        await asyncio.sleep(0.8)          # 模拟"抢画面 → 生成 → 释放"
        print(f"    [大脑] 回复 {payload.primary_name}：{payload.text[:34]}")


async def reporter(cere: Cerebellum) -> None:
    while True:
        await asyncio.sleep(5)
        s = cere.stats
        print(
            f"  [统计] 入 {s['in']:3d} | 丢弃 {s['drop']:3d} | 疑似 {s['suspect']:2d} "
            f"| 投递 {s['out']:2d} | raw_q {cere.raw_q.qsize()}"
        )


async def main() -> None:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0

    out_q: asyncio.Queue = asyncio.Queue(maxsize=100)
    shared = SharedState()
    memory = UserMemory()                  # 不带 encoder → 无记忆模式，链路照样跑

    cere = Cerebellum(
        source=MockSource(users=6, rate=2.0, seed=42),
        out_q=out_q,
        memory=memory,
        auditor=NullAuditor(),             # 全放行（规则层已挡掉大部分）
        shared=shared,
    )

    print(f"小脑启动，跑 {duration:.0f} 秒……\n")
    started = time.monotonic()
    try:
        async with asyncio.timeout(duration):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(cere.run(), name="cere")
                tg.create_task(brain_stub(out_q), name="brain")
                tg.create_task(reporter(cere), name="report")
    except TimeoutError:
        pass

    print(f"\n=== 结束（实跑 {time.monotonic() - started:.1f}s）===")
    print("统计：", cere.stats)
    print("共享层：", shared.dump())
    print("记忆表：", memory.stats())


if __name__ == "__main__":
    asyncio.run(main())
