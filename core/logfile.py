"""
行日志 —— 把关键事件直接追加进一个文本文件，方便事后翻。

为什么要有它：
    "弹幕到底抓到没有"这种问题，看终端会滚动、进程会被杀，
    只有落进文件里的证据不会骗人：
        文件里有 [抓到] → 抓到了（问题在后面）
        文件里没有     → 根本没抓到（问题在网络层）
    一眼就能把"没抓到"和"抓到了没往前走"分开。

用法：
    from core import logfile
    logfile.写("抓到 弹幕 | 三毛：有货吗")

日志文件在项目根：vtuber/弹幕日志.txt
"""
from __future__ import annotations

import os
import time

# 本文件在 core/ 下 —— 往上退两级就是项目根
路径 = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "弹幕日志.txt",
)


def 写(行: str) -> None:
    """追加一行（自动加时间戳）。

    写失败绝不抛异常 —— 日志只是旁路，不能反过来弄坏主程序。
    """
    try:
        with open(路径, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {行}\n")
    except Exception:
        pass


def 写大标题(标题: str) -> None:
    """每次启动打一条醒目的分隔线，方便把一轮一轮测试分开看。"""
    写("")
    写(f"══════════ {标题} ══════════")
