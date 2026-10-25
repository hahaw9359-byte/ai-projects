"""
硬过滤管道 —— 三态输出。

为什么必须是三态，不是"通过 / 不通过"两态？
    两态意味着"不通过"要由 LLM 判 —— 等于每条弹幕都得走一次 LLM。
    三态把「确定干净」和「确定垃圾」都在本地判掉（微秒级），
    只有「疑似」才付 LLM 的钱。真实直播间里 SUSPECT 通常不到 5%。

过滤器是有状态的（按 user_id 记历史），所以每个 Filter 都提供 gc()
定期清理 —— 不然跑一晚上 dict 里会涨到几万个用户。
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from typing import Iterable

from core.types import DROP, PASS, SUSPECT, RawMessage


class BaseFilter:
    def check(self, msg: RawMessage) -> str:
        return PASS

    def gc(self, now: float) -> None:
        """清理过期状态。now 是 time.monotonic()。"""


class LengthFilter(BaseFilter):
    """太短（空、单字）或太长（粘贴长文）都丢。"""

    def __init__(self, min_len: int = 1, max_len: int = 40):
        self.min_len = min_len
        self.max_len = max_len

    def check(self, msg: RawMessage) -> str:
        n = len(msg.text.strip())
        if n < self.min_len or n > self.max_len:
            return DROP
        return PASS


class DedupFilter(BaseFilter):
    """同一用户 N 秒内发一模一样的 → 只留第一条。"""

    def __init__(self, window: float = 30.0):
        self.window = window
        self._last: dict[str, tuple[str, float]] = {}

    def check(self, msg: RawMessage) -> str:
        now = time.monotonic()
        prev = self._last.get(msg.user_id)
        self._last[msg.user_id] = (msg.text, now)
        if prev and prev[0] == msg.text and now - prev[1] < self.window:
            return DROP
        return PASS

    def gc(self, now: float) -> None:
        ttl = self.window * 4
        for uid in [u for u, (_, t) in self._last.items() if now - t > ttl]:
            self._last.pop(uid, None)


class RateLimitFilter(BaseFilter):
    """同一用户 N 秒内超过 K 条 → 丢。防刷屏。"""

    def __init__(self, window: float = 10.0, limit: int = 5):
        self.window = window
        self.limit = limit
        self._hist: dict[str, deque[float]] = defaultdict(deque)

    def check(self, msg: RawMessage) -> str:
        now = time.monotonic()
        q = self._hist[msg.user_id]
        while q and now - q[0] > self.window:
            q.popleft()
        q.append(now)
        return DROP if len(q) > self.limit else PASS

    def gc(self, now: float) -> None:
        for uid in list(self._hist):
            q = self._hist[uid]
            while q and now - q[0] > self.window:
                q.popleft()
            if not q:
                self._hist.pop(uid, None)


class SpamFilter(BaseFilter):
    """纯符号（!!!!!）/ 单字复读（啊啊啊啊啊）都丢。"""

    _REPEAT = re.compile(r"^(.)\1{4,}$")            # 同一个字符重复 5 次以上
    _PUNCT = re.compile(r"^[\W_]+$")                # 全是非文字字符

    def check(self, msg: RawMessage) -> str:
        t = msg.text.strip()
        if self._REPEAT.match(t) or self._PUNCT.match(t):
            return DROP
        return PASS


class KeywordFilter(BaseFilter):
    """命中敏感词表 → 标 SUSPECT 送 LLM 复核。

    刻意**不直接 DROP** —— 关键词会误伤（"赌博"可能出现在"别赌博"里），
    让 LLM 看上下文再判，成本可以接受。
    词表上千条时应该换成 Aho-Corasick（pyahocorasick）。
    """

    def __init__(self, words: Iterable[str]):
        self._words = [w for w in words if w]

    def check(self, msg: RawMessage) -> str:
        for w in self._words:
            if w in msg.text:
                return SUSPECT
        return PASS


# 过滤器英文类名 → 中文名（打印给人看的时候用）
_中文名 = {
    "LengthFilter": "长度",
    "SpamFilter": "刷屏",
    "DedupFilter": "重复",
    "RateLimitFilter": "限流",
    "KeywordFilter": "敏感词",
}


class FilterPipeline:
    """链式跑。DROP 一票否决，SUSPECT 只记录不中断（后面还有过滤器要跑完）。

    ★ 带"丢弃原因"统计 —— 因为静默丢弃是最难查的问题：
      观众那边表现就是"我发的弹幕没人理"，而终端什么都不说。
      现在每条丢弃都能说出是被哪一环、因为什么丢的。
    """

    def __init__(self, filters: list[BaseFilter]):
        self.filters = filters
        self.stats = {"pass": 0, "drop": 0, "suspect": 0}
        self.丢弃统计: dict[str, int] = {}      # 中文名 → 次数
        self.上次丢弃原因 = ""                   # 最近一条被丢的原因

    def run(self, msg: RawMessage) -> str:
        worst = PASS
        for f in self.filters:
            verdict = f.check(msg)
            if verdict == DROP:
                self.stats["drop"] += 1
                名 = _中文名.get(type(f).__name__, type(f).__name__)
                self.丢弃统计[名] = self.丢弃统计.get(名, 0) + 1
                self.上次丢弃原因 = 名
                return DROP
            if verdict == SUSPECT:
                worst = SUSPECT
        self.stats["suspect" if worst == SUSPECT else "pass"] += 1
        return worst

    def 简报(self) -> str:
        """一句话说清丢过什么，给终端统计行用。"""
        if not self.丢弃统计:
            return "没丢过"
        return "、".join(f"{k}{v}条" for k, v in self.丢弃统计.items())

    def gc(self) -> None:
        now = time.monotonic()
        for f in self.filters:
            f.gc(now)


def default_pipeline() -> FilterPipeline:
    """默认过滤器链：从便宜到贵排序，先用最省的判断挡掉大部分。

    阈值是按"真直播间"调的（下面是调过之后的数，调之前吃过亏）：
      限流 5 条/10 秒 太紧 —— 实测连发 10 句会被砍掉一半
      → 现在 20 条/10 秒（≈ 每秒 2 条），只有真刷屏才会被限
      去重 30 秒 → 10 秒（原30秒会让"重问一遍"被静默吃掉）
      长度上限 40 字 → 60（观众问产品经常写超）
    """
    return FilterPipeline([
        LengthFilter(min_len=1, max_len=60),
        SpamFilter(),
        DedupFilter(window=10.0),
        RateLimitFilter(window=10.0, limit=20),
        KeywordFilter(words=["赌博", "加微信", "加vx", "代刷", "色情", "裸聊"]),
    ])
