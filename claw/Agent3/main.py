import os
import json

from .LLM_call import agent3
from . import tools
from .tools import init_tools
from ..shared.round_store import get_current_round, get_previous_round


SKILL_PATH = os.path.join(os.path.dirname(__file__), "SKILL.md")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "dialogue_history.json")

EMOTION_CN = {
    "calm": "平静", "confused": "困惑", "frustrated": "挫败",
    "annoyed": "烦躁", "anxious": "焦虑", "confident": "自信",
}
SUB_CN = {
    "curious": "好奇", "blocked": "卡住", "lost": "迷失", "stall": "停滞",
    "anger_at_ai": "对AI不满", "self_sad": "自我否定", "numb": "麻木",
    "wrong_method": "觉得方法不对", "unclear_explanation": "觉得讲不清", "too_slow": "嫌太慢",
    "bad_state": "状态差", "restless": "坐不住", "unclear": "说不清",
    "rushing": "着急", "doubt_direction": "怀疑方向", "doubt_self": "自我怀疑",
    "confirming": "在确认", "advancing": "在推进",
}
SUB_MAP = {
    "confused": "confused_sub",
    "frustrated": "frustrated_sub",
    "annoyed": "annoyed_sub",
    "anxious": "anxious_sub",
    "confident": "confident_sub",
}


def load_skill():
    """读取 SKILL.md 作为 system prompt。"""
    if not os.path.exists(SKILL_PATH):
        return ""
    with open(SKILL_PATH, "r", encoding="utf-8") as f:
        return f.read()


def load_history(file_path: str = HISTORY_PATH, max_turns: int = 1):
    """
    从历史文件读取最近 N 轮对话。

    Args:
        file_path: 历史文件路径
        max_turns: 保留最近几轮（每轮 = user + assistant）

    Returns:
        list: messages 格式的历史记录
    """
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            history = json.loads(content)
        if not isinstance(history, list):
            return []
    except (json.JSONDecodeError, OSError):
        return []
    return history[-max_turns * 2:]


def save_history(user_input: str, assistant_content: str, file_path: str = HISTORY_PATH):
    """
    把新一轮对话追加到历史文件。

    Args:
        user_input: 用户输入
        assistant_content: Agent3 的回应内容
        file_path: 历史文件路径
    """
    history = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    loaded = json.loads(content)
                    if isinstance(loaded, list):
                        history = loaded
        except (json.JSONDecodeError, OSError):
            history = []

    history.append({"role": "user", "content": user_input})
    history.append({"role": "assistant", "content": assistant_content})

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _emotion_short(emotion):
    """情绪指纹 → 简化版（主类, 子类）中文元组。无情绪返回 (None, None)。"""
    if not emotion or not isinstance(emotion, dict):
        return (None, None)
    emotions = emotion.get("emotion", {})
    if not emotions:
        return (None, None)
    scored_main = {k: v for k, v in emotions.items() if isinstance(v, (int, float)) and v != 0}
    if not scored_main:
        return ("平静", None)
    main_key = max(scored_main, key=scored_main.get)
    main_cn = EMOTION_CN.get(main_key, main_key)
    sub_cn = None
    sub_key = SUB_MAP.get(main_key)
    if sub_key:
        sub = emotion.get(sub_key, {})
        scored_sub = {k: v for k, v in sub.items() if isinstance(v, (int, float)) and v != 0}
        if scored_sub:
            top_sub = max(scored_sub, key=scored_sub.get)
            sub_cn = SUB_CN.get(top_sub, top_sub)
    return (main_cn, sub_cn)


def _emotion_feedback_text():
    """多轮情绪反馈（人话版）：只给上一轮/本轮情绪的简化版主类子类。"""
    prev = get_previous_round()
    if not prev:
        return "（首轮，无上一轮情绪）"
    cur = get_current_round()

    def _fmt(tag, emo):
        main_cn, sub_cn = _emotion_short(emo)
        if main_cn is None:
            return f"{tag}：无"
        if sub_cn:
            return f"{tag} 主类：{main_cn} 子类：{sub_cn}"
        return f"{tag} 主类：{main_cn}"

    return "\n".join([
        _fmt("上一轮情绪", prev.get("emotion", {})),
        _fmt("本轮情绪", cur.get("emotion", {})),
    ])


def build_messages(user_input: str, guidance: str, history: list = None):
    """
    构造 Agent3 的消息。

    Args:
        user_input: 本轮用户输入
        guidance: Agent2.5 输出的教学指导（6 字段 JSON）
        history: 历史对话记录，默认 None

    Returns:
        list: messages
    """
    if history is None:
        history = []

    skill = load_skill()
    emotion_feedback = _emotion_feedback_text()

    messages = [
        {"role": "system", "content": skill},
        {"role": "user", "content": (
            f"## 本轮教学指导\n{guidance}\n\n"
            f"## 多轮情绪反馈\n{emotion_feedback}\n\n"
            f"请基于以上内容进行教学。"
        )},
    ]

    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    return messages


async def run(user_input: str, guidance: str, history: list = None):
    """
    Agent3 入口。

    接收用户输入、Agent2.5 教学指导、可选历史对话，返回最终教学回应。
    首次调用时会触发 init_tools() 完成热备。
    """
    if tools.retriever is None:
        await init_tools()

    messages = build_messages(user_input, guidance, history)
    return await agent3(messages)


async def run_with_history(user_input: str, guidance: str, max_turns: int = 1):
    """
    Agent3 自动维护历史版本。

    调用前自动读取最近 N 轮历史，调用成功后自动把本轮对话追加到历史文件。
    """
    if tools.retriever is None:
        await init_tools()

    history = load_history(HISTORY_PATH, max_turns)
    messages = build_messages(user_input, guidance, history)
    result = await agent3(messages)

    if "content" in result and "error" not in result:
        save_history(user_input, result["content"])

    return result


async def run_from_files(user_input: str, guidance_path: str, history: list = None):
    """从文件读取 Agent2.5 教学指导，运行 Agent3。"""
    with open(guidance_path, "r", encoding="utf-8") as f:
        guidance = f.read()
    return await run(user_input, guidance, history)
