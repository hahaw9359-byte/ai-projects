"""TTS —— 火山引擎双向流式语音合成。

对外三个调用：
    初始化音频()          开机一次：把声卡调到和音频一样的格式
    await 合成(text)      一句文本 → (音频字节, 词表)
    播放(音频)            把音频丢给声卡，立刻返回（后台在放）

两条硬约束（踩过坑，记着）：
    ① 混音器必须先 quit 再 init —— pygame.init() 会先开成 44100/立体声，
       之后那句 init 是不生效的（SDL 不理你），不修就会变成 3.7 倍速。
    ② 火山给的是单声道，SDL 只收立体声 —— 每个采样点复制一份。
"""
from __future__ import annotations

import json
import time
import uuid

import numpy as np
import pygame
import websockets

from voice import protocols_
from voice.protocols_ import MsgType, EventType

# ── 配置 ────────────────────────────────────────────
#   ★ 密钥只在 .env 里，代码里一个字都不写（.env 不进 git）
from config import 读env

API_KEY  = 读env("VOLC_API_KEY")                            # 火山 API Key
SPEAKER  = 读env("VOLC_SPEAKER", "zh_female_vv_uranus_bigtts")
RESOURCE = 读env("VOLC_RESOURCE", "seed-tts-2.0")
URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

采样率 = 24000
每样本字节 = 2          # 16 位 = 2 字节


def _检查密钥() -> None:
    if not API_KEY:
        raise RuntimeError(
            "没找到火山语音的密钥。\n"
            "请在 vtuber/.env 里填上：VOLC_API_KEY=\"你的key\"\n"
            "（模板见 .env.example）"
        )


# ── 开机 ────────────────────────────────────────────
def 初始化音频() -> None:
    """把声卡调到 (24000Hz, 16位, 立体声)。开机调一次。"""
    pygame.init()
    pygame.mixer.quit()                                        # ← 必须先关（坑 ①）
    pygame.mixer.init(frequency=采样率, size=-16, channels=2)
    print("      [声卡]", pygame.mixer.get_init(), "（24000, -16, 2 才对）")


# ── 合成 ────────────────────────────────────────────
async def 合成(text: str, 打日志: bool = False) -> tuple[bytes, list]:
    """去火山合成一句，返回 (音频, 词表)。

    词表长这样：[{"word":"你","startTime":0.305,"endTime":0.415}, ...]
    """
    _检查密钥()
    headers = {
        "X-Api-Key": API_KEY,
        "X-Api-Resource-Id": RESOURCE,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    音频块们: list[bytes] = []
    词表: list[dict] = []

    async with websockets.connect(URL, additional_headers=headers) as ws:
        await protocols_.start_connection(ws)
        await protocols_.receive_message(ws)

        sid = str(uuid.uuid4())
        req = {"req_params": {
            "speaker": SPEAKER,
            "audio_params": {
                "format": "pcm",
                "sample_rate": 采样率,
                "enable_subtitle": True,     # ← 不开这个，词表就是空的
            },
            "model": "seed-tts-2.0-standard",
        }}
        await protocols_.start_session(ws, json.dumps(req).encode(), sid)
        await protocols_.receive_message(ws)

        await protocols_.task_request(
            ws, json.dumps({"req_params": {"text": text}}).encode(), sid)
        await protocols_.finish_session(ws, sid)

        while True:
            msg = await protocols_.receive_message(ws)

            if msg.type == MsgType.AudioOnlyServer:
                音频块们.append(msg.payload)                 # 声音：攒起来

            elif msg.event == EventType.TTSSubtitle:          # 时间表：在这儿
                if msg.payload:
                    词表.extend(json.loads(msg.payload).get("words", []))

            if msg.event == EventType.SessionFinished:
                break
            if msg.type == MsgType.Error:
                print("      [TTS 报错]", msg.payload.decode("utf-8", "ignore"))
                break

        await protocols_.finish_connection(ws)

    音频 = b"".join(音频块们)
    if 打日志:
        print(f"      [合成] {len(音频)} 字节 / {len(词表)} 个字"
              f" → {时长(音频):.2f} 秒")
    return 音频, 词表


# ── 播放 ────────────────────────────────────────────
def 时长(音频: bytes) -> float:
    """这段音频有多少秒。"""
    return len(音频) / (采样率 * 每样本字节)


def 播放(音频: bytes):
    """丢给声卡，立刻返回（不占着程序，后台在放）。"""
    立体声 = np.repeat(np.frombuffer(音频, dtype=np.int16), 2).tobytes()  # 坑 ②
    sound = pygame.mixer.Sound(buffer=立体声)
    sound.play()
    return sound


# ── 给「合成完就播」的一步到位版 ──────────────────────
async def 说一句(text: str, 等播完: bool = True) -> list:
    """合成 + 播放 + 等播完。返回词表（给渲染用）。"""
    音频, 词表 = await 合成(text)
    if not 音频:
        return []
    播放(音频)
    if 等播完:
        import asyncio
        await asyncio.sleep(时长(音频))
    return 词表


_ = time  # 预留：以后换真实音频时钟会用到
