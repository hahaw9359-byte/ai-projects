"""
小脑与大脑之间的数据契约。

设计要点：
- verdict 三态（PASS/DROP/SUSPECT）挂在消息上，让"硬过滤"和"LLM 审核"
  这两步能分开做（快路径 / 慢路径），互不阻塞。
- seq 单调递增，是为了让 LLM 审核能按序号回填结果 —— 一批里只有 SUSPECT
  的那几条会被送出去，回来时靠 seq 认领。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

# ── 过滤判定：三态 ────────────────────────────────────
PASS = "pass"          # 确定干净，直接进批次（绝大多数走这里）
DROP = "drop"          # 确定垃圾，当场丢弃（本地就能判，不花一分钱）
SUSPECT = "suspect"    # 疑似违规，标记后送 LLM 复核


@dataclass(slots=True)
class RawMessage:
    """一条弹幕 / 一个礼物，小脑的输入单位。"""

    seq: int                       # 单调递增，全局唯一
    user_id: str
    user_name: str
    text: str
    kind: str = "danmaku"          # danmaku / gift / superchat / like（点赞）
                                   # ⚠️ like 在「源层」就该聚合：每攒 N 个赞
                                   #    才产出一条消息（B站点赞量很大，逐个触发会刷屏）
                                   # 非 danmaku 的都会走小脑的「插队通道」（不参与攒批）
    value: int = 0                 # 礼物价值 / 点赞数，普通弹幕为 0
    ts: float = field(default_factory=time.time)
    verdict: str = PASS            # 由过滤管道填，不是弹幕源填


@dataclass(slots=True)
class BrainPayload:
    """小脑交给大脑的东西：干净原文 + 记忆 + 认人信息。

    注意 messages 里全是**原文**，没有任何加工 —— 加工会丢信息，
    也会让大脑分不清"观众说了什么"和"小脑以为观众说了什么"。
    """

    messages: list[RawMessage]     # 已过审的消息
    memories: list[str]            # primary_user 的历史事实（检索结果）
    primary_user: str              # 这批里应该被回应的那个人
    primary_name: str
    ts: float = field(default_factory=time.time)
    # 小脑开智提纯出的"观众想问的产品"（空 = 没检测到 / 没开智）
    #   ⚠️ 它**不替代** messages：原文永远是真相，这只是给检索用的一个"更干净的 query"
    产品线索: str = ""

    @property
    def text(self) -> str:
        """primary_user 在这批里说过的所有话，拼成一段（给大脑当 query 用）。"""
        return " / ".join(m.text for m in self.messages if m.user_id == self.primary_user)
