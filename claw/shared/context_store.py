import os
import json
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "user_queries.json")
MAX_ROUNDS = 10


def _ensure_dir():
    """确保数据目录存在。"""
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_history():
    """读取历史记录。文件不存在、为空或内容损坏时返回空列表。"""
    if not os.path.exists(FILE_PATH):
        return []
    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            if not isinstance(data, list):
                return []
            return data
    except (json.JSONDecodeError, OSError):
        return []


def append_user_input(query: str):
    """
    用户每输入一条，就追加记录到 user_queries.json。
    只保留最近 MAX_ROUNDS 条。
    """
    _ensure_dir()
    history = _load_history()

    history.append({
        "timestamp": datetime.now().isoformat(),
        "query": query
    })

    # 裁剪：只保留最近 MAX_ROUNDS 条
    history = history[-MAX_ROUNDS:]

    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_recent_user_inputs(n: int = 3):
    """
    读取最近 n 条用户输入，按时间顺序返回字符串列表。
    返回值：[本轮, 上一轮, 上上一轮, ...]
    """
    history = _load_history()
    return [item["query"] for item in history[-n:]]


def get_recent_user_inputs_with_index(n: int = 3):
    """
    读取最近 n 条用户输入，带索引编号。
    用于拼 prompt 时标明'第几轮'。
    """
    history = _load_history()
    recent = history[-n:]
    return [
        {"round": i + 1, "query": item["query"]}
        for i, item in enumerate(recent)
    ]


if __name__ == "__main__":
    # 简单自测
    append_user_input("测试输入 A")
    append_user_input("测试输入 B")
    append_user_input("测试输入 C")
    print("最近3条：", get_recent_user_inputs(3))
    print("带索引：", get_recent_user_inputs_with_index(3))
