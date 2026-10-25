"""
行为脑冒烟测试。

跑法（在 vtuber/ 目录下）：python run_performance.py

看三件事：
  1. 流式吐字      —— [吐字] 一行一行出来
  2. 抢占 / 恢复    —— 第 3 秒被大脑抢，第 5 秒还回来
  3. ★ 状态同步     —— [快照] 那行会跟着 mode 变（这就是「同步给大脑」的接口在工作）
"""
from __future__ import annotations

import asyncio
import logging
import sys

from core.shared import SharedState
from performance import PerformBrain, SellSkill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
sys.stdout.reconfigure(line_buffering=True)
logging.getLogger("perform").setLevel(logging.WARNING)   # 日志少一点，看吐字为主


async def snapshot_watcher(shared: SharedState) -> None:
    """假装是大脑：每秒读一次共享层快照（真实的大脑就是这么读的）"""
    while True:
        await asyncio.sleep(1.0)
        snap = shared.snapshot()
        print(f"        [快照｜大脑读到的] mode={snap['mode']:<10} skill={snap['skill_id']}")


async def brain_stub(brain: PerformBrain) -> None:
    """模拟大脑抢画面：第 3 秒抢，第 5 秒还"""
    await asyncio.sleep(3)
    print("\n  >>>>>> 大脑：抢画面！\n")
    await brain.interrupt()

    await asyncio.sleep(2)
    print("\n  >>>>>> 大脑：说完了，画面还给你\n")
    await brain.resume()


async def main() -> None:
    shared = SharedState()
    brain = PerformBrain(shared=shared)
    brain.register(SellSkill())               # 加新才艺就往这加：brain.register(XXXSkill())
    brain.switch_to("sell")

    print("行为脑启动（跑 10 秒，中途演示一次抢占）\n")
    try:
        async with asyncio.timeout(10):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(brain.loop(), name="perform")
                tg.create_task(snapshot_watcher(shared), name="snapshot")
                tg.create_task(brain_stub(brain), name="brain-stub")
    except TimeoutError:
        pass

    print(f"\n=== 结束 ｜ 共吐字 {brain.emitted} 段、被抢 {brain.interrupts} 次 ===")
    print("最终快照：", shared.snapshot())


if __name__ == "__main__":
    asyncio.run(main())
