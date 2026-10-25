"""
Skill —— 一个"才艺模块"的契约。

「可切换」的全部含义就在这个文件里：
    只要某个类实现了 stream()，它就能被行为脑托管。
    想加新才艺（唱歌/跳舞/闲聊），新写一个类扔进去就行，主控一行都不用改。

stream() 是个**异步生成器**：
    每次 yield 一小段文本（一句 / 一段），
    行为脑拿到一段就往下游转发一次（TTS / 推流）。
    这就是"流式吐字"——不是等整段说完才发，是边生成边发。
"""
from __future__ import annotations

from typing import AsyncIterator


class Skill:
    # 每个 skill 自报家门：id 用来切换，name 用来打日志
    id: str = "unnamed"
    name: str = "未命名才艺"

    async def stream(self) -> AsyncIterator[str]:
        """流式吐字。子类必须实现，且必须是 async 生成器（带 yield）。

        约定：
          - 每 yield 一段，行为脑就转发一段
          - 想停就 return（一轮结束）；想一直播就 while True
          - 被抢占时行为脑会直接 break 掉这个生成器，不用你管
        """
        raise NotImplementedError
        yield  # pragma: no cover  ← 让静态检查知道这是生成器

    def __repr__(self) -> str:
        return f"<Skill {self.id}>"
