"""
per-user 事实表。

它不是 RAG 库 —— 一个观众的事实量级只有几十条，
用不着向量数据库。第一版零依赖：纯 Python list + 手写余弦。

encoder 是可插拔的异步函数（比如包一层 sentence-transformers 的 encode）。
不传 encoder 时退化成"无记忆"模式，链路照样跑通 —— 这是刻意的，
好让骨架阶段不用先解决模型下载问题。
"""
from __future__ import annotations

import math
import time
from typing import Awaitable, Callable, Optional

# encoder: 文本 -> 向量。必须用 to_thread 包同步模型，见文档 4.1
Encoder = Callable[[str], Awaitable[list[float]]]


class UserMemory:
    def __init__(
        self,
        encoder: Optional[Encoder] = None,
        max_n: int = 200,
        top_k: int = 3,
    ):
        self._encode = encoder
        self.max_n = max_n
        self.top_k = top_k
        self._vecs: dict[str, list[list[float]]] = {}
        self._texts: dict[str, list[str]] = {}
        self._hits: dict[str, list[float]] = {}      # 最后命中时间，淘汰用

    # ── 读：小脑调 ───────────────────────────────────
    async def search(self, user_id: str, text: str) -> list[str]:
        """query 就是观众刚说的话 —— 小脑手上正好有，不用等大脑。"""
        if self._encode is None or not text:
            return []
        vecs = self._vecs.get(user_id)
        if not vecs:
            return []
        q = await self._encode(text)
        scored = [(self._cosine(v, q), i) for i, v in enumerate(vecs)]
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[str] = []
        for score, i in scored[: self.top_k]:
            if score <= 0:
                continue
            out.append(self._texts[user_id][i])
            self._hits.setdefault(user_id, [0.0] * len(vecs))[i] = time.time()
        return out

    # ── 写：大脑调（在异步沉淀任务里，不在热路径上）────
    async def write(self, user_id: str, facts: list[str]) -> int:
        """只追加、不修改 —— 彻底绕开"改一条要重建索引"的坑。"""
        if self._encode is None or not facts:
            return 0
        for f in facts:
            f = (f or "").strip()
            if not f:
                continue
            vec = await self._encode(f)
            self._vecs.setdefault(user_id, []).append(vec)
            self._texts.setdefault(user_id, []).append(f)
            self._hits.setdefault(user_id, []).append(0.0)
        self._prune(user_id)
        return len(facts)

    def _prune(self, user_id: str) -> None:
        """超容量按"最后命中时间"淘汰，保住常被用到的事实。"""
        texts = self._texts.get(user_id, [])
        if len(texts) <= self.max_n:
            return
        hits = self._hits[user_id]
        keep = sorted(range(len(texts)), key=lambda i: hits[i], reverse=True)[: self.max_n]
        keep.sort()                                    # 恢复时间顺序
        self._vecs[user_id] = [self._vecs[user_id][i] for i in keep]
        self._texts[user_id] = [texts[i] for i in keep]
        self._hits[user_id] = [hits[i] for i in keep]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = na = nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0.0 or nb == 0.0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))

    def facts(self, user_id: str) -> list[str]:
        """列出某人已知的全部事实（提炼时用，避免重复记录）。"""
        return list(self._texts.get(user_id, []))

    def stats(self) -> dict:
        return {
            "users": len(self._texts),
            "facts": sum(len(v) for v in self._texts.values()),
        }
