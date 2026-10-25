"""
LLM 客户端 —— 可替换。

DeepSeekLLM      真模型：DeepSeek 流式（正在用）
FakeLLM         假模型：按预设台词流式吐字（不花 API 额度时用）
FakeDistillLLM  假提炼模型：返回预设的事实列表
OpenAILLM       备选真模型：需要 pip install openai + API key

换模型只改 pipeline.py 里那一行，其他代码一行不用动。
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

import httpx


# ══════════════════════════════════════════════════════
# 用量记账（估算口径：字符数；中文约 1 字 1 token）
#   谁记账：DeepSeekLLM.stream() —— 三脑（大脑/卖货/沉淀）流量都过它，一处埋点全收
#   谁读账：webapp 的 GET /用量
# ══════════════════════════════════════════════════════
用量账: dict[str, dict[str, int]] = {}       # 标签 → {"调用", "输入字", "输出字"}


def 记一笔(标签: str, 输入字: int, 输出字: int) -> None:
    项 = 用量账.setdefault(标签, {"调用": 0, "输入字": 0, "输出字": 0})
    项["调用"] += 1
    项["输入字"] += 输入字
    项["输出字"] += 输出字


def 账面快照() -> dict:
    """账目拷贝（给 /用量 端点读，防外部乱改）。"""
    return {标签: dict(项) for 标签, 项 in 用量账.items()}


class DeepSeekLLM:
    """真模型 —— DeepSeek 的流式接口（SSE）。

    **为什么必须用流式**：EmotionStreamParser 要"一片一片"地喂。
    等整段生成完再切，首句就得等好几秒（直播会很迟钝）。

    ⚠️ **必须关掉"思考"（reasoning_effort="none"）** —— 实测：
        不关：首字要等 6.0 秒（它先写了 1300 字内心戏），max_tokens 小时正文直接是空的
        关掉：首字 0.8 秒，思考 0 字，正文 42 字
    直播是"话赶话"的场景，等不起思考。卖货/接话也不需要深度推理。
    """

    URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, model: str = "deepseek-v4-flash", api_key: str | None = None,
                 temperature: float = 0.9, max_tokens: int = 800,
                 reasoning_effort: str | None = "none", timeout: float = 60.0,
                 标签: str = "未分组"):
        from config import 读env
        self.model = model
        self.api_key = api_key or 读env("Deepseek_key")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.标签 = 标签          # 用量记账的分组名（"大脑"/"卖货"/"沉淀"）→ /用量 看得到
        if not self.api_key:
            raise RuntimeError("没找到 Deepseek_key —— 请在 vtuber/.env 里填上")

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        输入字 = len(prompt)
        输出字 = 0
        try:
            载荷 = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }
            if self.reasoning_effort:
                载荷["reasoning_effort"] = self.reasoning_effort
            头 = {"Authorization": f"Bearer {self.api_key}",
                  "Content-Type": "application/json"}

            async with httpx.AsyncClient(timeout=self.timeout) as c:
                async with c.stream("POST", self.URL, headers=头, json=载荷) as r:
                    if r.status_code != 200:
                        正文 = (await r.aread()).decode("utf-8", "ignore")
                        raise RuntimeError(f"LLM 返回 {r.status_code}：{正文[:200]}")
                    async for 行 in r.aiter_lines():
                        if not 行 or not 行.startswith("data:"):
                            continue
                        数据 = 行[5:].strip()
                        if 数据 == "[DONE]":
                            break
                        try:
                            片 = json.loads(数据)["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if 片:
                            输出字 += len(片)
                            yield 片
        finally:
            # 正常结束 / 中途取消 / 抛异常，都记一笔（估算口径：字符数）
            记一笔(self.标签, 输入字, 输出字)


class FakeLLM:
    """假模型：把一段带情绪的台词切成小片吐出来，模拟 token 流。"""

    def __init__(self, scripts: list[str] | None = None, chunk: int = 2, gap: float = 0.05):
        self.scripts = scripts or [
            "[开心]谢谢这位朋友的弹幕！[认真]我看看你说的是……嗯，这个问题挺有意思。",
            "[惊讶]哇，感谢老铁的礼物！[开心]太破费了，我记住你了啊。",
            "[认真]刚才那条弹幕说得对，我再补充两句。[开心]大家有问题随时问。",
            "[温柔]欢迎新来的朋友，点个关注不迷路。[开心]我们继续。",
        ]
        self.chunk = chunk
        self.gap = gap
        self._i = 0

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        text = self.scripts[self._i % len(self.scripts)]
        self._i += 1
        for i in range(0, len(text), self.chunk):
            await asyncio.sleep(self.gap)
            yield text[i:i + self.chunk]


class FakeDistillLLM:
    """假提炼模型：吐出一个 JSON 数组（模拟"从对话里提炼事实"）。"""

    def __init__(self, batches: list[list[str]] | None = None,
                 chunk: int = 4, gap: float = 0.02):
        self.batches = batches or [
            ["他喜欢周杰伦", "他最近在准备考研，压力有点大"],
            ["他常听老歌", "他养了一只猫"],
        ]
        self.chunk = chunk
        self.gap = gap
        self._i = 0

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        facts = self.batches[self._i % len(self.batches)]
        self._i += 1
        text = json.dumps(facts, ensure_ascii=False)
        for i in range(0, len(text), self.chunk):
            await asyncio.sleep(self.gap)
            yield text[i:i + self.chunk]


class OpenAILLM:
    """真模型。用到时才 import openai，没装也不影响跑骨架。"""

    def __init__(self, model: str = "gpt-4o-mini", api_key: str | None = None,
                 base_url: str | None = None, temperature: float = 0.8):
        self.model = model
        self.temperature = temperature
        self._kw = {"api_key": api_key, "base_url": base_url}
        self._client = None

    def _get(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(**{k: v for k, v in self._kw.items() if v})
        return self._client

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        resp = await self._get().chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=self.temperature,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
