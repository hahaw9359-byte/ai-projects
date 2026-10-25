import json
import re

from ..shared.HTTT_llm import LLM_client
from ..shared.round_store import write_guidance

# Agent2.5 用 pro + low：低思考深度换速度，应对复杂输入时思考链暴涨的风险
client = LLM_client(maxtoken=8000, model="deepseek-v4-pro", reasoning_effort="low")


def _parse_json(content: str):
    """从 LLM 输出里解析出教学指导 JSON。失败返回 None。"""
    if not content:
        return None
    text = content.strip()
    # 去掉可能的 ```json ... ``` 包裹
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # 从任意文字里截取第一个 { 到最后一个 }（容错前后解释文字）
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def agent2_5(messages, max_retries: int = 2):
    """
    Agent2.5：认知侦察 → 教学指导。

    返回 {"content": 教学指导 JSON 字符串}；解析失败自动重试。
    """
    for attempt in range(max_retries + 1):
        result = await client.send(messages)

        if "error" in result:
            return {"error": result["error"]}

        data = _parse_json(result.get("content", ""))
        if data is not None:
            write_guidance(data)
            return {
                "content": json.dumps(data, ensure_ascii=False),
                "prompt_token": result.get("prompt_token", 0),
                "completion_token": result.get("completion_token", 0),
            }

        # 解析失败：打印原始输出，方便诊断 pro 到底吐了什么
        raw = result.get("content", "")
        print(f"[Agent2.5] 解析失败，原始输出（前 600 字）:\n{raw[:600]}")
        if attempt < max_retries:
            print(f"Agent2.5 输出解析失败，第 {attempt + 1} 次重试...")
            continue

    return {"error": "LLM 输出无法解析为教学指导 JSON，已重试多次"}
