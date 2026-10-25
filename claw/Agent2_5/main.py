import json
import os

from .LLM_call import agent2_5
from ..shared.round_store import get_current_round, get_recent_guidances, write_emotion, write_breakpoint
from ..shared.profile_utils import format_profile


SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")


def _round_floats(obj, ndigits=2):
    """递归把 dict 里的 float 四舍五入，砍掉 JSON 里的浮点精度冗余。"""
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def _compact_json(obj):
    """紧凑 JSON（无缩进），省空白 token；浮点统一 round 2 位。"""
    return json.dumps(_round_floats(obj), ensure_ascii=False)


def _sparse_emotion(emotion_json):
    """情绪指纹稀疏化：删掉 0 值和空字符串字段，只保留非 0 的情绪信号。"""
    def _clean(o):
        if not isinstance(o, dict):
            return o
        out = {}
        for k, v in o.items():
            if k == "trust_signal":
                out[k] = v
            elif k == "quote":
                if v:
                    out[k] = v
            elif isinstance(v, dict):
                cleaned = _clean(v)
                if cleaned:
                    out[k] = cleaned
            elif isinstance(v, (int, float)) and v != 0:
                out[k] = v
        return out
    return _clean(emotion_json)


def load_skill():
    """读取 SKILL.md 作为 system prompt。"""
    if not os.path.exists(SKILL_PATH):
        return ""
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _load_last_record_text():
    """读最近三段历史指导，转成文本（旧→新，首轮为空）。"""
    guidances = get_recent_guidances(3)
    if not guidances:
        return "（首轮，无历史指导）"
    lines = [f"第 {i + 1} 条：{json.dumps(g, ensure_ascii=False)}" for i, g in enumerate(guidances)]
    return "\n".join(lines)


def build_messages(profile_json=None):
    """
    构造发送给 LLM 的消息。
    从 round_store 读当前层的 emotion + breakpoint。

    profile_json: 画像 dict（可选），转成摘要文本
    """
    current = get_current_round()
    emotion_json = current.get("emotion", {})
    breakpoint_json = current.get("breakpoint", {})
    skill = load_skill()
    profile_text = format_profile(profile_json)
    last_record = _load_last_record_text()

    user_content = f"""请根据以下数据进行认知侦察，输出一个 JSON 教学指导（不要 markdown 代码块包裹）。

## 输入 1：Agent1 情绪指纹（未出现的字段 = 0）
```json
{_compact_json(_sparse_emotion(emotion_json))}
```

## 输入 2：Agent2 断点诊断
```json
{_compact_json(breakpoint_json)}
```

## 输入 3：用户画像摘要
{profile_text}

## 输入 4：最近三段历史指导（旧→新，最后一条是上一轮）
{last_record}
"""

    return [
        {"role": "system", "content": skill},
        {"role": "user", "content": user_content}
    ]


async def run(profile_json=None):
    """Agent2.5 入口。从 round_store 读当前层，输出教学指导。"""
    messages = build_messages(profile_json)
    return await agent2_5(messages)


async def run_from_files(emotion_path, breakpoint_path, profile_path=None):
    """从文件读 sample 数据，写入 round_store 后运行 Agent2.5。"""
    with open(emotion_path, "r", encoding="utf-8") as f:
        write_emotion(json.load(f))
    with open(breakpoint_path, "r", encoding="utf-8") as f:
        write_breakpoint(json.load(f))
    profile_json = None
    if profile_path and os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            profile_json = json.load(f)
    return await run(profile_json)
