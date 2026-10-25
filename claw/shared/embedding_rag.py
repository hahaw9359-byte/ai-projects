"""
通用 Embedding RAG 工具。

提供文档加载、切分、向量化、建索引、检索的完整流程。
支持格式：txt、md、json、pdf。
"""

import os
import json
import asyncio
import fitz
import faiss
from sentence_transformers import SentenceTransformer


class Sentence_Rag:
    """
    基于句向量的本地 RAG 工具。

    默认使用 BAAI/bge-small-zh 模型，路径硬编码为本地 ModelScope 缓存位置。
    """

    def __init__(self, model: str = None):
        self.model_path = model or r"C:\Users\49523\.cache\modelscope\hub\models\BAAI\bge-small-zh"
        try:
            self.model = SentenceTransformer(self.model_path)
        except Exception as e:
            print(f"[Sentence_Rag] 模型加载失败: {e}")
            self.model = None

    def load(self, docs: str):
        """
        加载文件，返回 [{source, page, content}, ...]。

        支持：.txt、.md、.json、.pdf
        """
        root, ext = os.path.splitext(docs)
        ext = ext.lower()
        名字 = os.path.basename(root)

        if ext in (".txt", ".md"):
            with open(docs, "r", encoding="utf-8") as f:
                result = f.read()
            return [{"source": 名字, "page": 1, "content": result}]

        elif ext == ".json":
            with open(docs, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 统一把 json 对象转成一段可检索文本
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return [{"source": 名字, "page": 1, "content": text}]

        elif ext == ".pdf":
            doc = fitz.open(docs)
            result = []
            for i, page in enumerate(doc):
                txt = page.get_text()
                result.append({"source": 名字, "page": i + 1, "content": txt})
            return result

        else:
            return [{"error": f"不支持的格式:{ext}"}]

    def split(self, doc, chunk_size: int = 1000, chunk_overlap: int = 100):
        """
        切分文档。

        先按段落切分（\n\n），如果段落不足 2 段，则按字数切分。
        """
        if chunk_size <= 0:
            raise ValueError("chunk_size必须为正数")
        if chunk_overlap < 0:
            raise ValueError("overlap不能为负")
        if chunk_overlap >= chunk_size:
            raise ValueError(f"overlap({chunk_overlap})必须小于size({chunk_size})")
        if chunk_overlap >= chunk_size * 0.5:
            raise ValueError(
                f"overlap不应超过size的50%，当前overlap={chunk_overlap}, size={chunk_size}"
            )

        step = chunk_size - chunk_overlap
        result_tow = []
        for g in doc:
            paragraphs = g["content"].split("\n\n")
            for i, p in enumerate(paragraphs):
                if p.strip():  # 跳过空段落
                    result_tow.append({
                        "source": g["source"],
                        "page": g["page"],
                        "chunk_id": i,
                        "content": p.strip()
                    })

        if len(result_tow) < 2:
            result_three = []
            total = 0
            for q in doc:
                content = q["content"]
                w = 0
                while w < len(content):
                    chunk_text = content[w:w + chunk_size]
                    result_three.append({
                        "source": q["source"],
                        "page": q["page"],
                        "chunk_id": total,
                        "content": chunk_text
                    })
                    total += 1
                    w = w + step
            return result_three

        return result_tow

    def embedding(self, split_doc):
        """把 chunks 转成 float32 向量数组。"""
        if self.model is None:
            return [{"error": "embedding初始化失败"}]

        content_list = [e["content"] for e in split_doc]
        embedding_array = self.model.encode(
            content_list,
            normalize_embeddings=True
        ).astype("float32")

        if embedding_array.ndim == 1:
            embedding_array = embedding_array.reshape(1, -1)

        return embedding_array

    def embed_query(self, query: str):
        """把查询问题转成 float32 向量。"""
        if self.model is None:
            raise RuntimeError("embedding模型未初始化")

        embedding_array = self.model.encode(
            query,
            normalize_embeddings=True
        ).astype("float32")

        if embedding_array.ndim == 1:
            embedding_array = embedding_array.reshape(1, -1)

        return embedding_array

    def build_index(self, vectors):
        """用 FAISS 建索引。"""
        d = vectors.shape[1]
        index = faiss.IndexFlatIP(d)
        index.add(vectors)
        return index

    def retrieve(self, index, chunks, query: str, k: int = 3, threshold: float = 0.1):
        """
        向量检索，返回最相关的 k 个 chunk。

        threshold: 相似度低于该值的会被过滤。
        """
        encode_query = self.embed_query(query)
        distances, indices = index.search(encode_query, k)

        result = []
        for dist, i in zip(distances[0], indices[0]):
            if dist < threshold:
                continue
            result.append(chunks[i])

        if not result:
            return ["文档没有相关内容"]

        return result


class AsyncSentenceRag:
    """
    Sentence_Rag 的异步包装。

    模型加载仍是同步的，检索等 CPU 密集操作通过 asyncio.to_thread 包一层。
    """

    def __init__(self, model: str = None):
        self._rag = Sentence_Rag(model)

    async def aload(self, docs: str):
        return await asyncio.to_thread(self._rag.load, docs)

    async def asplit(self, doc, chunk_size: int = 1000, chunk_overlap: int = 100):
        return await asyncio.to_thread(self._rag.split, doc, chunk_size, chunk_overlap)

    async def aembedding(self, split_doc):
        return await asyncio.to_thread(self._rag.embedding, split_doc)

    async def abuild_index(self, vectors):
        return await asyncio.to_thread(self._rag.build_index, vectors)

    async def aretrieve(self, index, chunks, query: str, k: int = 3, threshold: float = 0.1):
        return await asyncio.to_thread(self._rag.retrieve, index, chunks, query, k, threshold)
