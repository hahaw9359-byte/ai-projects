"""
弹幕记忆 —— 按人查"这个观众之前说过什么"。

心脏换了（2026-10-22 重构）：
    旧：启动读整个 弹幕日志.txt → 正则解析 → dict[名字, 50 条] 全量常驻 → 每人截断
        内存 = O(人数 × 50 条)，人数无上限 → 跑久了吃光内存
    新：收一条写一条（SQLite）→ 查谁取谁（LIMIT 12）
        内存 = O(1)，一次只装查出来的十几条，拼完 prompt 就扔

**删掉的四样补丁**（它们存在的唯一理由就是"全量必须在内存"）：
    _扫新增()   按字节偏移增量读文件
    _吃()       正则逐行解析
    _截断()     每人只留 50 条
    self.发言   常驻内存的那个 dict

接口只留真正在用的：
    记录 / 检索 / 统计 / 有谁 / 最近的人 / 清理 / 关

弹幕日志.txt 继续写 —— 那是给人看的排查证据，**不参与任何逻辑**。
"""
from __future__ import annotations

import os

from core.db import 记忆库

# 默认库文件：vtuber/记忆.db（和 弹幕日志.txt 并排，两个东西两种职责）
_项目根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
默认库路径 = os.path.join(_项目根, "记忆.db")


class 弹幕记忆:
    """基于 SQLite 的记忆空间。

    :param 库路径: 记忆库文件路径（默认 vtuber/记忆.db）
    """

    def __init__(self, 库路径: str | None = None):
        self.库路径 = 库路径 or 默认库路径
        self.库 = 记忆库(self.库路径)
        self.可用 = self.库.可用

    # ── 写 ────────────────────────────────────────────
    def 记录(self, uid: str, 用户: str, 内容: str, 时刻: str | None = None) -> None:
        """收一条弹幕（弹幕源收到时调，和 logfile.写 并排双写）。

        ★ 第一个参数是 **uid**（B站那串数字），不是昵称 ——
          同名观众不会串台，改昵称也不会断历史。
        """
        self.库.记一条(uid, 用户, 内容, 时刻)

    # ── 读（按 uid）────────────────────────────────────
    def 检索(self, uid: str, 最近几条: int = 12) -> list[tuple[str, str]]:
        """返回这个人最近说过的话：[(时间显示, 内容), ...]，旧的在前。"""
        return self.库.查某人(uid, 最近几条)

    def 有谁(self) -> list[str]:
        """记忆里出现过的人（说话多的在前）。"""
        return self.库.有谁()

    def 最近的人(self, 最多: int = 10) -> list[dict]:
        """控制台看板：最近说过话的人 + 条数 + 最近时间。"""
        return self.库.最近的人(最多)

    def 统计(self) -> dict:
        return self.库.统计()

    # ── 维护 ──────────────────────────────────────────
    def 清理(self, 保留天数: int = 90) -> int:
        return self.库.清理(保留天数)

    def 关(self) -> None:
        self.库.关()
