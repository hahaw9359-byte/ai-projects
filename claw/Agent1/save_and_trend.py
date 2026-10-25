from ..shared.round_store import write_emotion


def save_and_trend(emotion_data):
    """情绪指纹写入统一轮次记录（当前层的 emotion 字段）。"""
    write_emotion(emotion_data)
