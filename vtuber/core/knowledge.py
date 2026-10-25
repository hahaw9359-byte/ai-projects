"""商品知识库 —— 把商品文档切块，按需检索。

────────────────────────────────────────────────────
为什么必须切（而不是整个塞进 prompt）
────────────────────────────────────────────────────
文档 6000+ 字，整个塞进 prompt 有三个问题：
    ① 贵 —— 每轮生成都发一遍
    ② 关键信息被稀释 —— 模型抓不住"观众问的那个点"
    ③ 卖货话术会飘 —— 面对整本目录，它反而不知道这轮该讲什么

切块之后：
    · 观众问产品 → 只把「最相关的 1~2 块」给大脑 → 回答有据可依
    · 卖货填充   → 每轮取「下一块」轮换介绍 → 像真主播一个个讲

────────────────────────────────────────────────────
切法（利用文档已有的 markdown 结构）
────────────────────────────────────────────────────
    按 ### 小节切 —— 每个产品 = 一块
    每块记下所属的 ## 大节（"362L"这块要知道自己属于"精密微研磨膜"）
    没有 ### 的大节（如"产品系列速览"）整段自成一块

────────────────────────────────────────────────────
检索
────────────────────────────────────────────────────
    用 core/textvec 的轻量向量（字面相似度）。
    对"型号 / 品类名"这类查询足够准；要语义级检索时换 textvec 即可。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from core import textvec

# 型号串 / 数字串：比 2-gram 可靠得多（"2000" 要找 "P2000"，不该靠 "00" 蒙）
_型号模式 = re.compile(r"[A-Za-z]+\d+[A-Za-z]*|\d{2,}")

# 疑问词：有没有在"问东西"的信号（不含型号也能判出来）
_疑问词 = (
    "有吗", "有没有", "多少钱", "怎么卖", "怎么买", "包邮", "价格", "报价",
    "现货", "库存", "规格", "型号", "尺寸", "适合", "能用", "能磨", "可以磨",
    "怎么用", "区别", "推荐", "哪个", "贵不贵", "便宜",
)


def 像在问产品吗(text: str) -> bool:
    """粗筛：有型号 或 有疑问词 → 值得让模型再看一眼。

    为什么先粗筛、不直接上模型：
        直播间里大部分弹幕是"哈哈""主播好"——不该为它们花一次 LLM 调用。
    漏了怎么办：
        粗筛漏掉的（"你那个能磨不锈钢不"）不会丢信息 —— 大脑仍用**整批文本**
        去检索，只是没提纯，命中率低一点。粗筛只决定"要不要多花一次调用"，
        不决定"有没有信息"。
    """
    if not text:
        return False
    t = text.strip()
    # 纯数字/纯符号（"666" "233" "？？？"）不算产品问题 —— 直播间里这些是刷屏。
    # 漏掉的纯数字提问（"3000？"）会走 L0 整批检索兜底，不丢信息。
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", t):
        return False
    if _型号模式.search(t):
        return True
    return any(w in t for w in _疑问词)


@dataclass
class 块:
    标题: str               # 小节标题（### 那行），没有则用大节名
    章节: str               # 上级大节（## 那行）
    内容: str               # 正文
    标题gram: set = field(default_factory=set)    # 标题的 2-gram 集合
    全文gram: set = field(default_factory=set)    # 标题+章节+内容的 2-gram 集合

    def 全文(self) -> str:
        """给 prompt 用的完整形态（带上下文）。"""
        if self.标题 and self.章节 and self.标题 != self.章节:
            return f"【{self.章节} · {self.标题}】\n{self.内容}"
        return f"【{self.标题}】\n{self.内容}"


class 商品知识库:
    def __init__(self, path: str):
        self.path = path
        self.块们: list[块] = []
        self._轮转 = 0
        self.载入()

    # ── 载入 + 切分 ──────────────────────────────────
    def 载入(self) -> None:
        text = open(self.path, encoding="utf-8").read()
        self.块们 = self._切分(text)
        for b in self.块们:
            # ⚠️ 标题信号「只放标题」——曾经把章节名也加进来，
            #    结果同章节下所有块分数完全一样（都被章节名撑平了），踩过这个坑。
            b.标题gram = textvec.二元组(b.标题)
            b.全文gram = textvec.二元组(b.标题 + " " + b.章节 + " " + b.内容)

    @staticmethod
    def _切分(text: str) -> list[块]:
        """按 ## / ### 层级切块。"""
        块们: list[块] = []
        章节 = ""            # 最近的 ##
        标题 = ""            # 最近的 ###
        缓冲: list[str] = []

        def 收尾():
            内容 = "\n".join(缓冲).strip()
            if 标题 or 内容:                       # 空块（只有标题占位）不要
                if 标题 or 内容:
                    块们.append(块(标题=标题 or 章节, 章节=章节, 内容=内容))

        for line in text.split("\n"):
            if line.startswith("### "):
                收尾()
                标题 = line[4:].strip()
                缓冲 = []
            elif line.startswith("## "):
                收尾()
                章节 = line[3:].strip()
                标题 = ""
                缓冲 = []
            elif line.startswith("# "):
                continue                            # 文档大标题丢掉（没信息量）
            else:
                缓冲.append(line)
        收尾()

        # 过滤掉"只有标题、没内容"的空壳块（比如 ## 大节下面全是 ### 的情况）
        return [b for b in 块们 if b.内容.strip()]

    # ── 检索：观众问产品时用 ─────────────────────────
    def 检索(self, query: str, top_k: int = 2, 最低分: float = 0.10) -> list[块]:
        """打分 = 标题覆盖率 × 2.5 + 全文覆盖率 × 1.0 + 型号命中 × 0.8/个。

        覆盖率 = query 的 2-gram 有几个出现在目标里（分母只有 query 大小）。
        为什么标题权重高：观众问"362L 是什么"时，信号在标题里。

        为什么额外加"型号命中"：2-gram 对数字不敏感（"3000" 和 "2000"
        共享 "00" 会互相污染）。型号/数字串用子串精确匹配，一锤定音。
        """
        if not query or not self.块们:
            return []
        q = textvec.二元组(query)
        if not q:
            return []
        型号们 = [m.group().lower() for m in _型号模式.finditer(query)]
        scored = []
        for b in self.块们:
            标题覆盖 = len(q & b.标题gram) / len(q)
            全文覆盖 = len(q & b.全文gram) / len(q)
            分 = 标题覆盖 * 2.5 + 全文覆盖 * 1.0
            if 型号们:
                正文 = (b.标题 + " " + b.内容).lower()
                分 += 0.8 * sum(1 for m in 型号们 if m in 正文)
            scored.append((分, b))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for s, b in scored[:top_k] if s >= 最低分]

    # ── 轮换：卖货填充时用 ───────────────────────────
    def 下一块(self) -> 块 | None:
        """每次取下一块（循环）—— 让卖货像真主播一样一个个介绍。"""
        if not self.块们:
            return None
        b = self.块们[self._轮转 % len(self.块们)]
        self._轮转 += 1
        return b

    def stats(self) -> dict:
        return {"块数": len(self.块们), "轮转到": self._轮转}


# ══════════════════════════════════════════════════════
# 卖货文档库 —— 「卖货文档/」文件夹里放 .txt，网页上随时切换
#   扫库 / 记住"上次切到哪份"（重启不丢）
# ══════════════════════════════════════════════════════
_当前标记名 = ".当前文档"


def 扫文档库(目录: str) -> dict[str, str]:
    """扫「卖货文档」文件夹：{文件名: 完整路径}。只认 .txt，忽略隐藏文件（.当前文档 这类）。"""
    出: dict[str, str] = {}
    if not os.path.isdir(目录):
        return 出
    for 名 in sorted(os.listdir(目录)):
        if 名.startswith(".") or not 名.lower().endswith(".txt"):
            continue
        出[名] = os.path.join(目录, 名)
    return 出


def 读上次文档(目录: str) -> str | None:
    """读「上次切到哪个」小标记；没有 / 读不出 → None（调用方回退默认）。"""
    try:
        with open(os.path.join(目录, _当前标记名), encoding="utf-8") as f:
            名 = f.read().strip()
        return 名 or None
    except OSError:
        return None


def 记上次文档(目录: str, 名: str) -> None:
    """写「上次切到哪个」小标记（失败不致命，下次回退默认）。"""
    try:
        with open(os.path.join(目录, _当前标记名), "w", encoding="utf-8") as f:
            f.write(名)
    except OSError:
        pass
