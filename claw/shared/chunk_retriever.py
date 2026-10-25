"""
Chunk Retriever — 本地知识库检索组合。

把"加载 → 切分 → embedding → 建索引 → 检索"封装成一个类。

两个输入：
- 本地输入：知识库文件路径（初始化时传入，LLM 不可见）
- LLM 输入：查询问题（query 方法传入）

内部自动处理 float32 格式和 reshape(1, -1)，满足 FAISS 要求。
"""

import os
import numpy as np
from .embedding_rag import AsyncSentenceRag


class ChunkRetriever:
    """
    本地文件知识库检索器。

    用法：
        retriever = ChunkRetriever("Agent3/data/plan.json")
        results = await retriever.query("asyncio queue 怎么入队", top_k=3)
    """

    def __init__(self, file_path: str):
        """
        本地输入：知识库文件路径。

        Args:
            file_path: 知识库文件路径，支持 txt / md / json / pdf
        """
        self.file_path = os.path.abspath(file_path)
        self._rag = AsyncSentenceRag()
        self._chunks = None
        self._index = None
        self._built = False

    async def build(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        构建检索索引。

        流程：加载文件 → 切分 chunk → embedding → FAISS 建索引

        Args:
            chunk_size: 每个 chunk 最大字符数
            chunk_overlap: chunk 之间重叠字符数

        Returns:
            self
        """
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"知识库文件不存在：{self.file_path}")

        doc = await self._rag.aload(self.file_path)
        self._chunks = await self._rag.asplit(doc, chunk_size, chunk_overlap)

        if not self._chunks:
            raise ValueError("文件内容为空或切分后没有 chunk")

        vectors = await self._rag.aembedding(self._chunks)

        # embedding_rag 内部已经做了 float32 + reshape，这里做兜底检查
        if not isinstance(vectors, np.ndarray):
            vectors = np.array(vectors, dtype="float32")
        if vectors.dtype != np.float32:
            vectors = vectors.astype("float32")
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)

        self._index = await self._rag.abuild_index(vectors)
        self._built = True

        return self

    async def warmup(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """
        热备：一次性完成加载/切分/embedding/建索引。

        语义上等价于 build()，放在入口里更直观。
        """
        return await self.build(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    @property
    def is_ready(self) -> bool:
        """索引是否已构建完成。"""
        return self._built

    async def query(self, question: str, top_k: int = 3, threshold: float = 0.1):
        """
        根据问题检索最相关的 chunks。

        LLM 输入：查询问题。

        Args:
            question: 查询问题
            top_k: 返回最相关的几条
            threshold: 相似度阈值，低于该值的会被过滤

        Returns:
            list: 相关 chunk 列表；如果没有命中，返回 ["文档没有相关内容"]
        """
        if not question or not question.strip():
            raise ValueError("查询问题不能为空")

        if not self._built:
            await self.build()

        return await self._rag.aretrieve(
            self._index,
            self._chunks,
            question.strip(),
            k=top_k,
            threshold=threshold
        )
