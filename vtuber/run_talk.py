"""行为脑 → TTS 联调（只出声，不开窗）。

跑法（在 vtuber/ 目录下）：

    .venv\\Scripts\\python.exe run_talk.py
    .venv\\Scripts\\python.exe run_talk.py 20      # 跑 20 秒自动停

跟 run_vtuber.py 的区别：
    这个    单线程，只验证「行为脑 → TTS」这一段
    那个    双线程，多了 Haru 的画面（那是最终形态）
"""
from __future__ import annotations

import asyncio
import logging
import sys

from pipeline import 流水线
from voice import tts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
sys.stdout.reconfigure(line_buffering=True)
logging.getLogger("perform").setLevel(logging.WARNING)
logging.getLogger("voice.protocols_").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def main(秒数: float | None) -> None:
    tts.初始化音频()          # 单线程版：声卡在这儿初始化
    print("行为脑 → TTS 联调开始"
          + (f"（跑 {秒数:.0f} 秒）" if 秒数 else "（Ctrl+C 停）") + "\n")
    await 流水线(秒数)


if __name__ == "__main__":
    秒数 = float(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        asyncio.run(main(秒数))
    except KeyboardInterrupt:
        print("\n\n=== 手动停止 ===")
    finally:
        try:
            import pygame
            pygame.mixer.quit()
            pygame.quit()
        except Exception:
            pass
