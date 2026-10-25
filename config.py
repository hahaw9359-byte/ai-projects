"""配置 —— 从 .env 读密钥。零依赖（不装 python-dotenv）。

查找顺序：先环境变量，再 .env 文件。
.env 不进 git（.gitignore 里已排除），.env.example 是空模板。
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).with_name(".env")


def 读env(名字: str, 默认: str = "") -> str:
    v = os.environ.get(名字)
    if v:
        return v.strip().strip('"').strip("'")
    if not _ENV_PATH.exists():
        return 默认
    for 行 in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        行 = 行.strip()
        if not 行 or 行.startswith("#") or "=" not in 行:
            continue
        键, _, 值 = 行.partition("=")
        if 键.strip() == 名字:
            return 值.strip().strip('"').strip("'")
    return 默认
