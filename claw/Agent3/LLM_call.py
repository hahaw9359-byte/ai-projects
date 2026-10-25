import json

from ..shared.HTTT_llm import LLM_client
from .tools import TOOL_REGISTRY, list_tools


# Agent3 是教学执行：flash 能力够，high 思考给自主性；maxtoken 提到 8000，避免 high 推理链吃光输出预算
client = LLM_client(maxtoken=8000, model="deepseek-v4-flash", reasoning_effort="high")


async def agent3(messages, max_rounds: int = 3):
    """
    Agent3：教学执行核心。

    接收外部组装好的 messages，内部走 ReAct 闭环：
    1. 调用 LLM；
    2. 若返回 tool_calls，执行工具并把结果追加到 messages；
    3. 再次调用 LLM；
    4. 重复直到 LLM 给出最终教学内容，或达到最大轮次后强制最终回应。

    Args:
        messages: 外部组装好的 OpenAI 格式消息列表（会被防御性复制）
        max_rounds: 最大工具调用轮数，防止死循环

    Returns:
        dict: {"content": str} 或 {"error": str, ...}
    """
    messages = list(messages)              # 防御性复制，避免污染外部列表
    tools_schema = list_tools()

    # 第一次调用 LLM
    response = await client.send(messages, tools=tools_schema)
    if "error" in response:
        return response

    # ReAct 循环
    for _ in range(max_rounds):
        content = response.get("content", "")
        tool_calls = response.get("tool_calls")

        # LLM 没有调用工具：直接返回教学内容
        if not tool_calls:
            if not content:
                return {"error": "empty_content", "detail": "LLM 返回空内容"}
            return {"content": content}

        # 有 tool_calls：追加 assistant 的 tool_calls 消息
        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls
        })

        # 执行每个工具，并把结果追加到 messages
        for tool_call in tool_calls:
            tool_id = tool_call.get("id")
            function_info = tool_call.get("function", {})
            tool_name = function_info.get("name")
            tool_args_str = function_info.get("arguments", "{}")

            tool_result = await _run_tool(tool_name, tool_args_str)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_id,
                "name": tool_name,
                "content": json.dumps(tool_result, ensure_ascii=False)
            })

        # 带着工具结果再次调用 LLM
        response = await client.send(messages, tools=tools_schema)
        if "error" in response:
            return response

    # 轮次用完仍未结束：不带 tools 强制生成最终教学内容
    final_response = await client.send(messages, tools=None)
    if "error" in final_response:
        return final_response

    final_content = final_response.get("content", "")
    if not final_content:
        return {"error": "empty_content", "detail": "强制最终回应仍为空"}

    return {"content": final_content}


async def _run_tool(tool_name: str, tool_args_str: str):
    """
    执行单个工具，并返回结构化结果。

    所有异常都被捕获并转换为错误字典返回给 LLM，让 LLM 决定如何继续。
    """
    # 1. 参数 JSON 解析
    try:
        tool_args = json.loads(tool_args_str)
    except json.JSONDecodeError as e:
        return {
            "error": "json_decode_error",
            "detail": str(e),
            "received": tool_args_str
        }

    if not isinstance(tool_args, dict):
        return {
            "error": "invalid_arguments_type",
            "detail": "工具参数必须是 JSON object",
            "received": tool_args_str
        }

    # 2. 工具名检查
    if tool_name not in TOOL_REGISTRY:
        return {
            "error": "unknown_tool",
            "name": tool_name,
            "available": list(TOOL_REGISTRY.keys())
        }

    # 3. 执行工具
    try:
        return await TOOL_REGISTRY[tool_name](**tool_args)
    except TypeError as e:
        return {
            "error": "missing_or_invalid_parameter",
            "tool": tool_name,
            "detail": str(e)
        }
    except Exception as e:
        return {
            "error": "tool_execution_failed",
            "tool": tool_name,
            "detail": str(e)
        }
