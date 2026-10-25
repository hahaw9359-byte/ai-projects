from ..shared.round_store import write_guidance, get_last_guidance


def save_state(guide: dict):
    """教学指导写入统一轮次记录（当前层的 guidance 字段）。"""
    write_guidance(guide)


def load_last_record() -> dict:
    """读上一轮的教学指导。没有则返回空 dict。"""
    return get_last_guidance() or {}
