"""
统一的分层轮次记录。

文件：claw/data/round_record.json
每条记录 = 一轮的 {round_id, timestamp, emotion, breakpoint, guidance}

三个字段由三个 Agent 按顺序写入（天然串行，无并发冲突）：
  Agent1   → emotion（情绪指纹）
  Agent2   → breakpoint（断点诊断，三路合并）
  Agent2.5 → guidance（教学指导，6 字段）

分层机制：每轮开始时，若最后一条记录已完整（有 guidance），
则 append 新层；否则继续填当前层。
"""

import os
import json
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FILE_PATH = os.path.join(DATA_DIR, "round_record.json")


def _load():
    if not os.path.exists(FILE_PATH):
        return []
    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(records):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _current_round(records):
    """返回当前轮记录（最后一条未完成的）。若最后一条已完成，append 新层。"""
    if records and "guidance" not in records[-1]:
        return records[-1]
    new = {"round_id": len(records) + 1, "timestamp": datetime.now().isoformat()}
    records.append(new)
    return new


def write_emotion(emotion):
    """Agent1 写入：当前轮的情绪指纹。"""
    records = _load()
    cur = _current_round(records)
    cur["emotion"] = emotion
    _save(records)


def write_breakpoint(breakpoint_data):
    """Agent2 写入：当前轮的断点诊断。"""
    records = _load()
    cur = _current_round(records)
    cur["breakpoint"] = breakpoint_data
    _save(records)


def write_guidance(guidance):
    """Agent2.5 写入：当前轮的教学指导。写完后这一层完整。"""
    records = _load()
    cur = _current_round(records)
    cur["guidance"] = guidance
    _save(records)


def get_last_guidance():
    """读最近一条已完成记录的 guidance。没有则返回 None。"""
    records = _load()
    for rec in reversed(records):
        if "guidance" in rec:
            return rec["guidance"]
    return None


def get_recent_guidances(n=3):
    """读最近 N 条已完成记录的 guidance，按时间顺序（旧→新）返回。不足 N 条则返回全部。"""
    records = _load()
    guidances = [rec["guidance"] for rec in records if "guidance" in rec]
    return guidances[-n:]


def get_current_round():
    """读当前轮（emotion + breakpoint，可能还没 guidance）。"""
    records = _load()
    return records[-1] if records else {}


def get_previous_round():
    """读上一轮完整记录（倒数第二条）。不足两条则返回 None。"""
    records = _load()
    if len(records) < 2:
        return None
    return records[-2]


def reset():
    """清空记录文件（测试用，让每个用例独立跑）。"""
    if os.path.exists(FILE_PATH):
        os.remove(FILE_PATH)
