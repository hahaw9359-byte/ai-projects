"""★ 虚拟主播总入口 —— 主线程渲染 + 子线程三脑/TTS + Web 控制台 ★

跑法（在 vtuber/ 目录下）：

    .venv\\Scripts\\python.exe run_vtuber.py
    .venv\\Scripts\\python.exe run_vtuber.py 30      # 跑 30 秒自动关

线程分工：
    主线程   开窗 + 渲染循环（一秒 60 次，永远不等任何人）
    子线程   uvicorn（循环上跑着：行为脑 + TTS + 小脑 + 大脑 + 沉淀 + HTTP 端点）
    黑板     子线程写，主线程读

Web 控制台：
    浏览器打开 http://127.0.0.1:8000  （接口文档在 /docs）

看三件事：
    1. 窗口立刻出现，一直不卡
    2. 过一两秒开始出声
    3. Haru 的嘴跟着声音动
"""
from __future__ import annotations

import logging
import sys
import threading

import webapp
from stage import render

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
sys.stdout.reconfigure(line_buffering=True)
logging.getLogger("perform").setLevel(logging.WARNING)
logging.getLogger("voice.protocols_").setLevel(logging.WARNING)   # 静音协议包
logging.getLogger("httpx").setLevel(logging.WARNING)              # 静音 LLM 的请求日志


def 子线程入口(用假模型: bool = False) -> None:
    """后厨：uvicorn 带着流水线全在这儿跑（五个脑 + HTTP 控制台同一个循环）。"""
    try:
        webapp.启动服务器(用假模型=用假模型)
    except Exception as e:                      # 子线程挂了不影响画面
        print(f"      [子线程退出] {e!r}")


def main(秒数: float | None = None, 调试: bool = False, 用假模型: bool = False) -> None:
    # ① 主线程先把台子搭好（开窗、声卡、模型）—— 必须在起子线程之前
    model = render.启动()

    # ② 雇后厨（uvicorn + 流水线；控制台地址：http://127.0.0.1:8000）
    后厨 = threading.Thread(target=子线程入口, args=(用假模型,),
                             daemon=True, name="brain")
    后厨.start()

    # ③ 主线程站门口，一直画
    print("\n主线程开始渲染（关窗口退出）")
    print("Web 控制台：http://127.0.0.1:8000\n")
    try:
        render.渲染循环(model, 秒数, 调试=调试)
    except KeyboardInterrupt:
        pass
    finally:
        webapp.请求关闭()                    # 请 uvicorn 走优雅关闭（触发 lifespan 关闭段）
        后厨.join(timeout=6)                 # 等后厨把摊收完（最多等 6 秒）
        render.收场()
        print("\n=== 收场了 ===")


if __name__ == "__main__":
    参数 = sys.argv[1:]
    调试 = "--调试" in 参数
    假模型 = "--假模型" in 参数
    参数 = [a for a in 参数 if not a.startswith("--")]
    秒数 = float(参数[0]) if 参数 else None
    main(秒数, 调试, 假模型)
