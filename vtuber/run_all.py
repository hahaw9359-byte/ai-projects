"""★ 三脑联动 —— 不开窗、不出声，纯看数据流 ★

跑法（在 vtuber/ 目录下）：

    .venv\\Scripts\\python.exe run_all.py
    .venv\\Scripts\\python.exe run_all.py 30      # 跑 30 秒

链路：

    假弹幕 → 小脑 → brain_q → 大脑 ─┐
                    ↑               ├→ tts_q → 假TTS（打印）
              共享层/记忆 ← 行为脑 ──┘
                    ↑
              沉淀任务（定时把对话提炼成事实）

看四件事：
    1. 小脑把弹幕过滤攒批后投给大脑
    2. 大脑抢画面 → 吐字（带情绪）→ 释放
    3. 行为脑被抢时停、被放时继续
    4. 沉淀任务把对话写进记忆（结尾看"记忆"那行）
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import sys

from core.memory import UserMemory
from core.shared import SharedState
from cerebellum import Cerebellum, MockSource
from performance import PerformBrain, SellSkill
from cerebrum import Brain, Distiller, FakeDistillLLM, FakeLLM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
sys.stdout.reconfigure(line_buffering=True)
for noisy in ("perform", "distill", "brain"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def 假encoder(text: str) -> list[float]:
    """够用的假向量：同一个文本永远得到同一个向量，能跑通检索链路。"""
    d = hashlib.md5(text.encode("utf-8")).digest()
    return [b / 255.0 for b in d[:16]]


async def main(duration: float = 25.0) -> None:
    # ── 共享资源：三个脑拿的是同一份 ──────────────────
    shared = SharedState()
    memory = UserMemory(encoder=假encoder)

    # ── 脑之间的管道 ─────────────────────────────────
    brain_q: asyncio.Queue = asyncio.Queue(maxsize=100)
    tts_q: asyncio.Queue = asyncio.Queue(maxsize=2)      # maxsize=2 = 背压

    # 行为脑的出口
    async def 行为脑吐字(text: str) -> None:
        await tts_q.put(("", text))

    # 大脑的出口（同一个队列，谁抢到画面谁说话）
    async def 大脑吐字(emotion: str, text: str) -> None:
        await tts_q.put((emotion, text))

    # ── 三个脑 ───────────────────────────────────────
    perform = PerformBrain(shared=shared, on_text=行为脑吐字)
    perform.register(SellSkill())
    perform.switch_to("sell")

    cere = Cerebellum(
        source=MockSource(users=4, rate=1.2, seed=7),
        out_q=brain_q,
        memory=memory,
        shared=shared,
        batch_n=3,
        batch_t=3.0,
    )

    brain = Brain(
        in_q=brain_q, shared=shared, memory=memory,
        llm=FakeLLM(), perform=perform, on_text=大脑吐字,
    )

    distiller = Distiller(
        shared=shared, memory=memory,
        llm=FakeDistillLLM(), interval=10.0, min_lines=2,
    )

    # ── 假装是 TTS 工人 ──────────────────────────────
    async def 假TTS() -> None:
        while True:
            emo, text = await tts_q.get()
            who = f"大脑·{emo or '--'}" if emo else "行为脑"
            print(f"    [TTS] <{who}> {text}")
            await asyncio.sleep(0.6)                     # 假装合成 + 播放要时间

    print(f"三脑联动启动，跑 {duration:.0f} 秒\n")
    try:
        async with asyncio.timeout(duration):
            async with asyncio.TaskGroup() as tg:
                tg.create_task(cere.run(), name="小脑")
                tg.create_task(perform.loop(), name="行为脑")
                tg.create_task(brain.loop(), name="大脑")
                tg.create_task(distiller.loop(), name="沉淀")
                tg.create_task(假TTS(), name="假TTS")
    except TimeoutError:
        pass

    print("\n=== 结束 ===")
    print(f"小脑    ：{cere.stats}")
    print(f"行为脑  ：吐字 {perform.emitted} 段，被抢 {perform.interrupts} 次")
    print(f"大脑    ：处理 {brain.handled} 批")
    print(f"记忆    ：{memory.stats()}")
    print(f"共享层  ：{shared.dump()}")


if __name__ == "__main__":
    参数 = [a for a in sys.argv[1:] if not a.startswith("--")]
    秒数 = float(参数[0]) if 参数 else 25.0
    asyncio.run(main(秒数))
