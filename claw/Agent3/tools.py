"""
Agent3 工具注册表。

参考风格：装饰器只负责注册函数到 TOOL_REGISTRY；
工具 schema 单独写成 TOOLS_SCHEMA 列表，直接塞进 LLM payload。
"""

import os
from ..shared.tavily_client import TavilyClient
from ..shared.chunk_retriever import ChunkRetriever


# 工具实例占位符（由 init_tools 注入）
tavily = None
retriever = None

# 调用注册表：name -> func，大模型返回 tool_call 时用来找执行函数
TOOL_REGISTRY = {}


def register_tool(name=None):
    """装饰器：把函数注册到 TOOL_REGISTRY。"""
    def wrapper(func):
        TOOL_REGISTRY[name or func.__name__] = func
        return func
    return wrapper


@register_tool("tavily_search")
async def tavily_search(query: str):
    """联网搜索。"""
    result = await tavily.search(query)
    if isinstance(result, dict) and "error" in result:
        return result.get("error", "搜索失败")
    return result


@register_tool("read_plan")
async def read_plan(query: str):
    """从学习计划中检索相关知识。"""
    result = await retriever.query(query)
    if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) and "error" in result[0]:
        return result[0].get("error", "查询失败")
    return f"与学习 Plan 相关得内容为{result}"


# 给 LLM payload 看的 tools schema 列表
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": "联网搜索，验证事实或补充最新信息。当需要确认外部知识、最新动态或纠正潜在错误时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，建议用具体技术术语"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_plan",
            "description": "从本地学习计划中检索相关知识。当需要结合用户的学习进度、前置知识点或课程计划时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要检索的学习计划内容，例如某个概念、章节或目标"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


def list_tools():
    """返回 tools schema 列表，供 LLM payload 使用。"""
    return TOOLS_SCHEMA


async def init_tools():
    """
    初始化所有工具实例并完成热备。
    在编排层启动时调用一次。
    """
    global tavily, retriever

    tavily = TavilyClient()
    retriever = ChunkRetriever(os.path.join(os.path.dirname(__file__), "data", "plan.md"))
    await retriever.warmup()
