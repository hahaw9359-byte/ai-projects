"""
保存 Agent3 生成的最终教学回应。
"""

import os
from datetime import datetime


DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def save_response(content: str):
    """将最终回应保存到 data/response_latest.md。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    now = datetime.now().isoformat()

    current = f"""---
timestamp: {now}
---

{content}
"""
    with open(f"{DATA_DIR}/response_latest.md", "w", encoding="utf-8") as f:
        f.write(current)
