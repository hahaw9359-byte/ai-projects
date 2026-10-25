from ..shared.HTTT_llm import LLM_client
from ..shared.round_store import write_emotion
import json
import re

# 情绪指纹是打分任务，flash 足够（原来是默认 pro，慢）
client = LLM_client(model="deepseek-v4-flash", reasoning_effort="low")

async def agent1(messages):
    """
    Agent1：情绪指纹提取。

    messages 由调用方在外部构造，包含 system skill + user prompt。

    返回：解析后的情绪指纹 JSON dict。
    """
    result = await client.send(messages)

    if "error" in result:
        return {"error": result["error"]}

    content = result.get("content", "")
    if not content:
        return {"error": "LLM 返回空内容"}

    try:
        raw_for_debug = content  # 保留原始
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        econtent = json.loads(content.strip())
    except json.JSONDecodeError:
        return {"error": "json解析失败", "raw": repr(raw_for_debug)}

    try:
        write_emotion(econtent)
    except Exception as e:
        return {"error": "write_emotion 失败", "detail": str(e)}

    return econtent
