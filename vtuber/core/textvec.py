"""轻量文本向量 —— 零依赖的本地编码器。

用途：给「用户记忆」和「商品知识库」当"文本 → 向量"的编码器。
原理：把文本切成「2 字组合」（bigram），哈希到固定维度，形成稀疏向量。
      两段文本字面越像 → 向量余弦越接近。

为什么不直接上 bge 这类真模型：
    · 装 torch 要 2GB+、加载要几秒 —— 对"型号/品类名"检索是杀鸡用牛刀
    · 这个项目的 query 都是「362L」「砂纸」「抛光液」这类实词，字面匹配就够用
    · 接口和真模型完全一致（文本 → 向量）—— 以后想升级，只换这一个文件

⚠️ 它检索的是「字面像」，不是「意思像」。
   观众说"有没有补划痕的"，字面匹配不到"漆面细修"这种说法。
   要真语义检索就换 bge（本地模型已经有了：~/.cache/modelscope/.../bge-small-zh）。
"""
from __future__ import annotations

import hashlib
import math

维度 = 1024          # 哈希桶数。太小会撞、太大会稀疏，1024 对中文 2-gram 够用


def 编码(文本: str) -> list[float]:
    """2-gram 哈希 → L2 归一化的稀疏向量。

    同步函数 —— 纯本地计算（微秒级），不需要丢线程。
    """
    vec = [0.0] * 维度
    s = "".join(文本.split()).lower()          # 去掉所有空白
    if len(s) < 2:
        return vec
    for i in range(len(s) - 1):
        g = s[i:i + 2]
        idx = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16) % 维度
        vec[idx] += 1.0
    n = math.sqrt(sum(x * x for x in vec))
    if n:
        vec = [x / n for x in vec]
    return vec


async def 异步编码(文本: str) -> list[float]:
    """异步包装 —— UserMemory 的 encoder 接口要求 awaitable。"""
    return 编码(文本)


def 余弦(a: list[float], b: list[float]) -> float:
    """两个已归一化的向量 → 余弦相似度（就是点积）。"""
    return sum(x * y for x, y in zip(a, b))


def 二元组(文本: str) -> set[str]:
    """文本 → 2 字组合的集合（去空白、转小写）。

    比哈希向量精确：没有哈希冲突，可以做"查询覆盖率"——
        query 的 2-gram 有几个在目标文本里出现
    覆盖率的分母只有 query 大小，所以**长文本占不到便宜**，
    这正是检索想要的（不然随便一个长块都能蒙中几个字）。
    """
    s = "".join(文本.split()).lower()
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}
