"""
Tavily 联网搜索工具（通用）。

调用 Tavily API，返回前 N 条搜索结果的标题、摘要、URL，以及可选的总结答案。
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()


class TavilyClient:
    """
    Tavily 搜索客户端。

    默认从 .env 读取 TAVILY_API_KEY，也允许外部传入 api_key 覆盖。
    """

    def __init__(
        self,
        api_key: str = None,
        max_results: int = 3,
        timeout: int = 30,
        include_answer: bool = True
    ):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.max_results = max_results
        self.timeout = timeout
        self.include_answer = include_answer
        self.url = "https://api.tavily.com/search"

    async def search(self, query: str):
        """
        使用 Tavily API 搜索，返回摘要结果。

        Args:
            query: 搜索关键词

        Returns:
            dict: {"success": True, "result": {"answer": ..., "sources": [...]}}
                  或 {"success": False, "error": ...}
        """
        if not self.api_key:
            return {"success": False, "error": "缺少 TAVILY_API_KEY"}

        if not query or not query.strip():
            return {"success": False, "error": "搜索关键词不能为空"}

        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": self.max_results,
            "include_answer": self.include_answer
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=payload)

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Tavily API 错误：{response.status_code}",
                    "detail": response.text[:200]
                }

            data = response.json()
            results = data.get("results", [])
            answer = data.get("answer", "") if self.include_answer else ""

            simplified = []
            for item in results[:self.max_results]:
                simplified.append({
                    "title": item.get("title", "无标题"),
                    "url": item.get("url", ""),
                    "content": item.get("content", item.get("snippet", "无摘要"))[:300]
                })

            return {
                "success": True,
                "result": {
                    "answer": answer,
                    "sources": simplified
                }
            }

        except httpx.TimeoutException:
            return {"success": False, "error": "Tavily 请求超时"}
        except httpx.RequestError as e:
            return {"success": False, "error": f"Tavily 网络错误：{str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Tavily 未知错误：{str(e)}"}


# 默认客户端实例，方便顶层函数直接调用
_default_client = TavilyClient()


async def tavily_search(query: str):
    """兼容旧接口的顶层函数，使用默认客户端。"""
    return await _default_client.search(query)
