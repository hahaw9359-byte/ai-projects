"""voice —— 把「文本」变成「声音 + 嘴型 + 表情」。

对外的几样东西：
    tts.初始化音频()          开机调一次
    await tts.合成(text)      文本 → (音频, 词表)
    tts.播放(音频)            出声

    mouth.造嘴型表(词表)       词表 → [(嘴型, 起, 止), ...]
    mouth.此刻嘴型(表, t)      → (嘴张开, 嘴形)      ← 归音素
    face.情绪到参数(情绪)       → {参数名: 目标值}     ← 归情绪
    board.黑板                 TTS 写、渲染读的那块共享区
"""
from voice import board, face, mouth, tts

__all__ = ["board", "face", "mouth", "tts"]
