"""
卖货 skill —— 让大模型现想话术（不是念写死的台词）。

跟原来"背稿"的区别：
    原来：for line in self.lines: yield line            ← 念稿
    现在：while True: 让模型说 2~3 句 → 逐句 yield        ← 现想

────────────────────────────────────────────────────────
两个必须想清楚的问题
────────────────────────────────────────────────────────

① **没有"问"的时候，谁触发它开口？**

   卖货不是问答，是**任务**。所以要给它"任务式提示词"，
   而不是"问答式提示词"：

        ❌ 问答式：「观众说了 X，你怎么回？」   ← 没弹幕就没得答
        ✅ 任务式：「你在直播卖货，接着往下说」  ← 没人也能一直说

   触发就是行为脑那个 `while True` —— 它一转，就问模型一句"接着说什么"。

② **它不知道该说多少？**

   **两道闸，缺一不可：**

     闸 1（提示词）：明确写"只输出 2~3 句，每句 15~25 字"
                    —— 不写，模型会写小作文

     闸 2（下游队列）：行为脑往下游吐字，下游队列 maxsize=2，
                      吐满就堵住，等 TTS 播完才放它继续。
                      **队列本身就是刹车** —— 模型不需要知道"该说多久"。

③ **还有一个它会犯的毛病：重复。**

   所以每轮都把"刚才说过的话"喂回提示词里，并明确写"不要重复"。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from cerebrum.brain import EMOTIONS
from cerebrum.parser import EmotionStreamParser
from performance.skill import Skill

# 模型出错或空转时的兜底台词（保证直播不断）
_备用台词 = [
    "欢迎来到直播间，今天给大家带来的是新款好物。",
    "先看这一款，性价比真的很高，价格也给到位了。",
    "大家注意看这个细节，做工是很讲究的。",
    "喜欢的宝子扣个 1，我看看有多少人想要。",
    "3 号链接已经上了，手慢无哦。",
]

_提示词模板 = """你是直播带货主播，正在直播卖货。

【你卖的东西】
{商品文档}

【你刚才已经说过的话】（绝对不要重复它们）
{说过的话}

【要求】
- 顺着往下说，就像直播时一段接一段那样自然
- 只输出 {每轮几句} 句话，每句 15~25 字
- 口语化一点，可以用「家人们」「宝子」这种直播间的说法
- 直接输出台词。不要序号、不要引号、不要任何解释和格式
"""

# ★ 有知识库时用这个：每轮只讲一块（一个产品），轮换着介绍
_轮块模板 = """你是直播带货主播，正在直播卖货。

【这一轮重点介绍的产品】（只依据这里的信息讲，别编价格和参数）
{块内容}

【你刚才已经说过的话】（绝对不要重复它们）
{说过的话}

【要求】
- 围绕上面这个产品讲：它是什么、解决什么问题、有什么规格 —— 就像真主播一个个介绍产品
- 只输出 {每轮几句} 句话，每句 15~25 字
- 口语化一点，可以用「家人们」「宝子」这种直播间的说法
- 直接输出台词。不要序号、不要引号、不要任何解释和格式
"""


class SellSkill(Skill):
    id = "sell"
    name = "卖货"

    def __init__(self, llm=None, doc_path: str | None = None,
                 知识库=None, 每轮几句: int = 3, 记几句: int = 6):
        self.llm = llm                      # 传了就用模型，没传就走备用台词
        self.doc_path = doc_path            # 商品文档（一行一句也认）—— 没知识库时的后备
        self.知识库 = 知识库                 # ★ 有知识库 → 每轮轮换取一块讲（推荐）
        self.每轮几句 = 每轮几句
        self.记几句 = 记几句               # 记住最近说过几句（防重复）

        self.商品文档 = ""
        self.说过的话: list[str] = []
        self.生成轮数 = 0
        self.失败次数 = 0
        self._备用i = 0

    # ── 读商品文档 ───────────────────────────────────
    def load(self) -> None:
        """⚠️ 文档格式定了之后只改这里。"""
        if not self.doc_path:
            self.商品文档 = "（商品文档还没给，先按「直播间里的好物」自由发挥）"
            return
        p = Path(self.doc_path)
        if not p.exists():
            raise FileNotFoundError(f"商品文档不存在：{p}")
        self.商品文档 = p.read_text(encoding="utf-8").strip()

    # ── 造提示词（闸 1 在这儿）────────────────────────
    def _造提示词(self, 本轮块=None) -> str:
        说过 = "\n".join(f"- {s}" for s in self.说过的话) or "（还没说过）"
        if 本轮块 is not None:
            return _轮块模板.format(
                块内容=本轮块.全文(),
                说过的话=说过,
                每轮几句=self.每轮几句,
            )
        return _提示词模板.format(
            商品文档=self.商品文档,
            说过的话=说过,
            每轮几句=self.每轮几句,
        )

    # ── 让模型说：流式收，剥情绪标记，凑够一句吐一句 ──
    async def _让模型说(self, 提示词: str):
        # ★ 过 EmotionStreamParser：剥掉 [情绪] 标记 + 按句切分。
        #   卖货的情绪是上游固定「热情」（见 pipeline 的 塞队列），
        #   这里解析出的情绪名丢弃不用 —— 但标记必须剥掉，绝不能流进 TTS。
        #   （2026-10-16 修：假模型台词带 [开心]，原手写切句不剥标记，被念出来了）
        parser = EmotionStreamParser(allowed=set(EMOTIONS))
        async for 片 in self.llm.stream(提示词):
            for _情绪, 句 in parser.feed(片):
                句 = 句.strip()
                if 句:
                    yield 句
        for _情绪, 句 in parser.flush():      # 流结束：把残留吐干净
            句 = 句.strip()
            if 句:
                yield 句

    def _记住(self, 句: str) -> None:
        self.说过的话.append(句)
        self.说过的话 = self.说过的话[-self.记几句:]

    # ── 流式吐字（这就是关节 ①）──────────────────────
    async def stream(self):
        if not self.知识库 and not self.商品文档:
            self.load()

        while True:
            self.生成轮数 += 1
            # ★ 有知识库 → 这一轮只讲一块（轮换），每次换一个产品介绍
            本轮块 = self.知识库.下一块() if self.知识库 else None
            if 本轮块:
                print(f"      [卖货] 这一轮讲：{本轮块.标题}")
            说了几句 = 0
            try:
                async for 句 in self._让模型说(self._造提示词(本轮块)):
                    说了几句 += 1
                    self._记住(句)
                    yield 句                  # ★ 吐给行为脑 → 队列 → TTS
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.失败次数 += 1
                print(f"      [卖货] 模型出错（{type(e).__name__}: {e}）")

            if 说了几句 == 0:
                # 模型报错 / 空转 → 用备用台词顶上，保证直播不黑屏
                句 = _备用台词[self._备用i % len(_备用台词)]
                self._备用i += 1
                self._记住(句)
                yield 句
                await asyncio.sleep(1.0)

    # ── 给外面看的状态 ───────────────────────────────
    def stats(self) -> dict:
        return {"生成轮数": self.生成轮数, "失败次数": self.失败次数,
                "备用台词用了": self._备用i}
