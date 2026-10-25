"""
记忆沉淀 —— 定时把 dialog buffer 提炼成长期事实，写进 UserMemory。

**为什么不在热路径上做？**
    提炼要调 LLM。如果每轮对话都提炼一次，等于每条弹幕都附一次 LLM 调用，
    延迟和成本都吃不消。所以攒着，定时批处理（跟攒批是一个思路）。

**处理的边界**：每个用户单独提炼，只处理"上次处理过之后新增"的那些行
（_last_seen 记着进度），不会重复提炼。
"""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("distill")

_PROMPT = """从下面这段直播对话里，提炼出这个观众【值得长期记住】的信息。

要求：
- 只提炼跨场次仍然有效的事实（喜好、身份、正在做的事、人际关系）
- 不要记流水账和情绪（"他今天说他很累" ❌ → "他最近在准备考试，压力大" ✅）
- 每条不超过 30 字
- 没有值得记的就返回空数组
- 只输出 JSON 数组，不要任何解释

【已经知道的信息】
{known}

【最近的对话】
{dialog}

输出示例：["他喜欢周杰伦", "他在准备考研"]
"""


class Distiller:
    def __init__(self, shared, memory, llm, interval: float = 1200.0, min_lines: int = 4):
        self.shared = shared
        self.memory = memory
        self.llm = llm
        self.interval = interval
        self.min_lines = min_lines                  # 攒够几条才值得提炼
        self._done: dict[str, int] = {}             # user_id -> 已处理到第几条
        self.runs = 0
        self.written = 0

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("沉淀出错：%s", e)

    async def run_once(self) -> int:
        """跑一轮：把所有用户的新增对话提炼一遍。返回写入的事实条数。"""
        total = 0
        for uid in list(self.shared.dialog.keys()):
            total += await self._distill_user(uid)
        self.runs += 1
        if total:
            log.info("沉淀完成：写入 %d 条事实", total)
        return total

    async def _distill_user(self, uid: str) -> int:
        buf = self.shared.recent(uid)
        done = self._done.get(uid, 0)
        fresh = buf[done:]
        if len(fresh) < self.min_lines:
            return 0

        dialog = "\n".join(m.get("text", "") for m in fresh)
        known = "、".join(self.memory.facts(uid)) or "（还没有）"
        prompt = _PROMPT.format(known=known, dialog=dialog)

        raw = ""
        async for piece in self.llm.stream(prompt):
            raw += piece

        facts = self._parse_facts(raw)
        self._done[uid] = len(buf)                  # 记进度：这批处理过了
        if not facts:
            return 0
        n = await self.memory.write(uid, facts)
        self.written += n
        log.info("  [沉淀] %s → %s", uid, facts)
        return n

    @staticmethod
    def _parse_facts(raw: str) -> list[str]:
        raw = raw.strip()
        if raw.startswith("```"):                    # 容忍模型包 markdown
            raw = raw.strip("`").split("\n", 1)[-1].strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("提炼结果不是合法 JSON：%r", raw[:80])
            return []
        if not isinstance(data, list):
            return []
        return [str(x).strip() for x in data if str(x).strip()]
