"""
审核器 —— 可插拔的"疑似内容复核"入口。

当前只保留空实现：
    NullAuditor  全部放行（个人直播够用）

为什么不再带 LLM 实现：
    ① 规则层（filters.py 的 KeywordFilter）已经把「疑似」标出来了，
       占比不到 5% —— 不是每条弹幕都要过模型。
    ② 真要接 LLM 复核，**复用 cerebrum/llm.py 的 DeepSeek 通道**即可，
       不必另起一个客户端。原来那份用的是 openai 包 + gpt-4o-mini，
       和项目实际通道不匹配（venv 里也没装 openai），已删除。

设计约定（保留）：**审核失败时放行，不是拦截。**
    直播场景里，审核服务挂了就"什么都不说"，比"偶尔漏一条"严重得多。
"""
from __future__ import annotations

from core.types import RawMessage


class NullAuditor:
    """不审核，全部放行。"""

    async def audit(self, msgs: list[RawMessage]) -> set[int]:
        """返回**安全**的 seq 集合 —— 空实现就是全部安全。"""
        return {m.seq for m in msgs}
