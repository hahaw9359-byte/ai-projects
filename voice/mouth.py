"""嘴型翻译 —— 把 TTS 给的「字 + 时间」翻成「两个数字」。

TTS 给的是：  一句话里的每个字，从第几秒到第几秒
渲染要的是：  嘴张多大、嘴什么形状

中间走三跳（详见《渲染层实现清单》）：
    时间 → 字 → 嘴型分类(viseme) → 两个数字
"""
from __future__ import annotations

from pypinyin import pinyin, Style

# 嘴型分类 → (嘴张多大, 嘴什么形状)
#   ParamMouthOpenY: 0 = 闭，   1 = 张很大
#   ParamMouthForm : -1 = 圆唇，+1 = 咧嘴
VISEME_到_参数 = {
    "CLOSED": (0.00, 0.00),
    "AA":     (1.00, 0.00),   # 大张
    "I":      (0.35, 1.00),   # 扁
    "O":      (0.75, -1.00),  # 圆
    "N":      (0.25, 0.00),   # 半开
}


def 字到viseme(词: str) -> str:
    """一个词（可能带标点，如"好，"）→ 嘴型分类。

    依据：拼音里的主元音 —— 元音决定嘴张开成什么形状。
    """
    # 只留汉字，标点丢掉（\u4e00~\u9fff 是汉字的编码范围）
    干净 = "".join(ch for ch in 词 if "\u4e00" <= ch <= "\u9fff")
    if not 干净:
        return "CLOSED"

    拼音 = pinyin(干净[0], style=Style.NORMAL)[0][0]
    if "a" in 拼音:                  # 好 hao、三 san
        return "AA"
    if "o" in 拼音 or "u" in 拼音:    # 我 wo、五 wu
        return "O"
    if "i" in 拼音:                  # 你 ni、是 shi
        return "I"
    return "N"                       # 测 ce、二 er


def 造嘴型表(词表: list) -> list:
    """TTS 的 words → [(嘴型, 起秒, 止秒), ...]"""
    return [
        (字到viseme(w["word"]), w["startTime"], w["endTime"])
        for w in 词表
    ]


def 此刻嘴型(嘴型表: list, t: float) -> tuple[float, float]:
    """t = 这一句已经播了多少秒 → 返回这一刻该摆的两个数。

    渲染主线程每帧调一次。查不到（句首 / 逗号停顿 / 句尾）→ 闭嘴。
    """
    for 嘴型, 起, 止 in 嘴型表:
        if 起 <= t < 止:
            return VISEME_到_参数[嘴型]
    return VISEME_到_参数["CLOSED"]
