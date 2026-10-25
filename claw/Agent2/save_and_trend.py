from ..shared.round_store import write_breakpoint


def save_and_trend(breakpoint_data):
    """断点诊断写入统一轮次记录（当前层的 breakpoint 字段）。"""
    write_breakpoint(breakpoint_data)
