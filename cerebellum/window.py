"""
攒批窗口 —— "攒够 n 条 或 等满 t 秒，先到先发"。

这是最容易写错的一块，关键点有三个：

1. **先阻塞等第一条，再开始计时。**
   如果一开始就计时，冷场时会不停产出空批次，白白惊动下游。

2. **用 wait_for 卡剩余时间，而不是 sleep。**
   sleep(t) 会让窗口变成"固定 t 秒"而不是"最多 t 秒"，
   消息来早了也在白等。

3. **礼物走插队通道。**
   礼物必须立即响应，不能等窗口攒满。
"""
from __future__ import annotations

import asyncio
import time


class BatchWindow:
    def __init__(self, out_q: asyncio.Queue, n: int = 5, t: float = 5.0):
        self._in: asyncio.Queue = asyncio.Queue()
        self._out = out_q
        self.n = n
        self.t = t

    async def feed(self, msg, urgent: bool = False) -> None:
        """由 filter_loop 调。urgent=True（礼物/@）时插队，立即成一个批次。"""
        if urgent:
            await self._out.put([msg])
            return
        await self._in.put(msg)

    async def run(self) -> None:
        """独立 Task：不停地收集 → 产出批次。"""
        while True:
            batch = await self._collect()
            if batch:
                await self._out.put(batch)

    async def _collect(self) -> list:
        first = await self._in.get()                 # 先等第一条（冷场不产空批次）
        batch = [first]
        deadline = time.monotonic() + self.t
        while len(batch) < self.n:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._in.get(), left))
            except asyncio.TimeoutError:
                break
        return batch
