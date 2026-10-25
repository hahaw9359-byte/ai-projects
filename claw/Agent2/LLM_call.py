from ..shared.HTTT_llm import LLM_client
import json
import re

# 拆分后三个 Agent2 分支都走 flash —— 各自只做一件事，负载最小
# maxtoken 8000：flash 偶发生成占满 max_tokens 时 content 会空（截断），给足空间避免
# reasoning_effort=low：限制思考深度，避免 flash 思考几万 token 拖时间
flash_client = LLM_client(maxtoken=8000, model="deepseek-v4-flash", reasoning_effort="low")
# 2c 知识流是纯摘录任务，用 low（minimal 非官方档位，可能被 API 忽略走默认反而更慢）
flash_client_2c = LLM_client(maxtoken=8000, model="deepseek-v4-flash", reasoning_effort="low")


async def _call_and_parse(client, messages, max_empty_retries: int = 2):
    """
    通用：调用 LLM + 解析 JSON。
    client 由调用方指定。
    返回：解析后的 JSON dict（不持久化，持久化由 main.py 合并后统一做）。
    """
    for attempt in range(max_empty_retries + 1):
        result = await client.send(messages)
        print(f"DEBUG result (attempt {attempt + 1}):", result)

        if "error" in result:
            return {"error": result["error"]}

        content = result.get("content", "")
        if content and content != "无内容":
            break

        if attempt < max_empty_retries:
            print(f"返回空内容，第 {attempt + 1} 次重试...")
            continue
        else:
            return {"error": "LLM 返回空内容，已重试多次仍失败"}

    raw_for_debug = content
    try:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        parsed = json.loads(content.strip())
    except json.JSONDecodeError:
        return {"error": "json解析失败", "raw": repr(raw_for_debug)}

    return parsed


async def agent2(messages, max_empty_retries: int = 2):
    """Agent2a：断点诊断（只判断 type + subtype + confidence）。"""
    return await _call_and_parse(flash_client, messages, max_empty_retries)


async def agent2b(messages, max_empty_retries: int = 2):
    """Agent2b：优势识别（输出 strengths）。"""
    return await _call_and_parse(flash_client, messages, max_empty_retries)


async def agent2c(messages, max_empty_retries: int = 2):
    """Agent2c：知识流提取（输出 knowledge_flow）。纯摘录，用 minimal 思考。"""
    return await _call_and_parse(flash_client_2c, messages, max_empty_retries)
