"""
记忆库 —— SQLite 单文件（弹幕档案层）。

它解决的真问题（不是"查询不方便"，是**内存**）：
    旧方案启动时把整个日志读进内存 dict —— `dict[名字, 50 条]`，
    **人数 × 50 条全部常驻，人数还没有上限**，跑久了把机器吃光。
    换成按需查库之后：内存 = O(1)，一次只装查出来的十几条，拼完 prompt 就扔。

★ 主键是 uid，不是昵称（2026-10-22 修）：
    · 两个同名观众（"小明"）→ 按名字查会串台
    · 观众改昵称 → 按名字查历史全断
    uid 是 B 站给的那串数字，改不掉也不会重复 —— 和 shared / UserMemory 用同一套身份。
    用户名只用来**展示**（存最近一次看到的昵称）。

三条职责边界（别混）：
    真相（弹幕原文）        → 这里，落盘
    人类日志（弹幕日志.txt）→ 继续写，用于排查"没抓到 vs 抓到没受理"，**不当记忆**
    用户画像（UserMemory）  → 内存里的提炼事实，另一个东西

线程约定（一条硬规矩）：
    sqlite3 连接**绑定创建它的线程**。写入（弹幕源）和查询（小脑）都在同一个
    子线程的事件循环里 → 一个连接够用，**不需要加锁**。
    ★ 连接不跨线程传（将来要 to_thread 跑大查询，就在那个线程里另开连接）。

失败降级（记忆是旁路，不能拖死直播）：
    打不开库 → 打一行日志 → 退化成"空记忆" → 直播继续。
"""
from __future__ import annotations

import sqlite3
import time

_建表 = """
CREATE TABLE IF NOT EXISTS 弹幕 (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,   -- 自增身份证；按 id 排序 = 按到达顺序
  uid   TEXT NOT NULL,                       -- ★ 主键身份：改昵称、同名都靠它区分
  用户  TEXT NOT NULL,                       -- 展示用（最近一次看到的昵称）
  时间  TEXT NOT NULL,                       -- SQLite 没有 datetime 类型 → 存 ISO 字符串
  内容  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_弹幕_uid ON 弹幕(uid);   -- 只给"现在真的会查"的列建
"""


def 现在() -> str:
    """统一时间格式：2026-10-22 13:50:05（字典序 = 时间序）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def 显示(时刻: str) -> str:
    """2026-10-22 13:50:05 → 10-22 13:50（给 prompt 用）。"""
    return 时刻[5:16] if len(时刻) >= 16 else 时刻


class 记忆库:
    """一张表 + 六个动作：记一条 / 查某人 / 有谁 / 最近的人 / 统计 / 清理。"""

    def __init__(self, 路径: str):
        self.路径 = 路径
        self._db: sqlite3.Connection | None = None
        self._异常 = ""
        try:
            # check_same_thread 保持默认 True：跨线程用会立刻抛错 —— 那是好事，
            # 违规当场暴露，而不是悄悄写坏数据。
            self._db = sqlite3.connect(路径)

            # ── 两条 PRAGMA：解决"每条 commit 都 fsync 卡住事件循环" ──
            #   WAL   ：写只追加日志、不锁读者；★ 配 NORMAL 才安全
            #   NORMAL：不必每次提交都 fsync —— 最坏丢最后几条，但库不会坏
            #   （单独用 NORMAL + 默认 journal 模式是有风险的：崩溃可能损坏库）
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")

            # ★ 顺序很重要：**先**自愈旧表，**再**建表/建索引。
            #   反过来的话，旧表（没有 uid 列）会让 CREATE INDEX ... (uid) 直接报
            #   "no such column: uid"，整个初始化就失败了。
            self._自愈旧表()
            self._db.executescript(_建表)
            self._db.commit()
        except Exception as e:
            self._异常 = repr(e)
            self._db = None
            print(f"      [记忆] ⚠️ 打开记忆库失败（{e}）→ 本次运行记忆为空，直播继续")

    def _自愈旧表(self) -> None:
        """旧版表（只有 用户、没有 uid）→ 直接删掉，建表交给调用方。

        为什么敢删：弹幕记忆是**可重建的旁路数据**，而旧表按昵称存，
        日志里没有 uid，**根本没法迁**。与其启动时报 no such column，不如重建。
        """
        if self._db is None:
            return
        try:
            列 = {r[1] for r in self._db.execute("PRAGMA table_info(弹幕)").fetchall()}
            if 列 and "uid" not in 列:
                print("      [记忆] 检测到旧结构（无 uid）→ 重建表（弹幕记忆可重建）")
                self._db.execute("DROP TABLE 弹幕")
                self._db.commit()
        except Exception:
            pass

    @property
    def 可用(self) -> bool:
        return self._db is not None

    # ── 写 ────────────────────────────────────────────
    def 记一条(self, uid: str, 用户: str, 内容: str, 时刻: str | None = None) -> None:
        """收一条弹幕。参数化查询（? 占位），永远不拼字符串。"""
        if self._db is None or not uid or not 内容:
            return
        try:
            self._db.execute(
                "INSERT INTO 弹幕 (uid, 用户, 时间, 内容) VALUES (?, ?, ?, ?)",
                (uid, 用户 or uid, 时刻 or 现在(), 内容),
            )
            self._db.commit()
        except Exception as e:
            print(f"      [记忆] ⚠️ 写入失败：{e}")

    # ── 读（全部按 uid）────────────────────────────────
    def 查某人(self, uid: str, 最近几条: int = 12) -> list[tuple[str, str]]:
        """这个人最近说过的话：[(时间显示, 内容), ...]，旧的在前。

        先 ORDER BY id DESC LIMIT N 拿最新的 N 条，再用 reversed 恢复"旧的在前"。
        为什么按 id 不按时间：同一秒内的多条时间会平局，id 永远不重复。
        """
        if self._db is None or not uid:
            return []
        try:
            rows = self._db.execute(
                "SELECT 时间, 内容 FROM 弹幕 WHERE uid = ? ORDER BY id DESC LIMIT ?",
                (uid, max(1, int(最近几条))),
            ).fetchall()
        except Exception:
            return []
        return [(显示(t), c) for t, c in reversed(rows)]

    def 有谁(self) -> list[str]:
        """记忆里出现过的人（按 uid 分组，名字取任意一条 —— 展示用）。"""
        if self._db is None:
            return []
        try:
            rows = self._db.execute(
                "SELECT 用户 FROM 弹幕 GROUP BY uid ORDER BY COUNT(*) DESC"
            ).fetchall()
        except Exception:
            return []
        return [r[0] for r in rows]

    def 最近的人(self, 最多: int = 10) -> list[dict]:
        """最近说过话的人（给控制台看板）：条数 + 最近时间。"""
        if self._db is None:
            return []
        try:
            rows = self._db.execute(
                "SELECT uid, MAX(用户) AS 名, COUNT(*) AS 条数, MAX(时间) AS 最近 "
                "FROM 弹幕 GROUP BY uid ORDER BY 最近 DESC LIMIT ?",
                (max(1, int(最多)),),
            ).fetchall()
        except Exception:
            return []
        return [{"uid": u, "用户": n, "条数": c, "最近": 显示(t)} for u, n, c, t in rows]

    def 统计(self) -> dict:
        if self._db is None:
            return {"人数": 0, "弹幕条数": 0}
        try:
            n = self._db.execute("SELECT COUNT(*) FROM 弹幕").fetchone()[0]
            u = self._db.execute("SELECT COUNT(DISTINCT uid) FROM 弹幕").fetchone()[0]
            return {"人数": u, "弹幕条数": n}
        except Exception:
            return {"人数": 0, "弹幕条数": 0}

    # ── 维护 ──────────────────────────────────────────
    def 清理(self, 保留天数: int = 90) -> int:
        """按时间清旧弹幕（启动时调一次就够）。

        为什么用"天"而不是"总条数上限"：
            总量上限会让热门直播间失忆（一天就顶满，只剩今天的），
            而弹幕的价值本来随时间衰减 —— 按时间清才符合它的价值曲线。
        ★ 用户事实不在这里清：它不随时间衰减，只去重。
        ★ 现在这条 DELETE 走全表扫（只有 uid 索引）。量小无所谓；
          将来表上百万行时补一行 idx_弹幕_时间 即可。
        """
        if self._db is None or 保留天数 <= 0:
            return 0
        try:
            线 = time.strftime("%Y-%m-%d %H:%M:%S",
                              time.localtime(time.time() - 保留天数 * 86400))
            cur = self._db.execute("DELETE FROM 弹幕 WHERE 时间 < ?", (线,))
            self._db.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        except Exception:
            return 0

    def 关(self) -> None:
        """优雅退出时调（不调也行，进程结束自动释放）。"""
        try:
            if self._db is not None:
                self._db.close()
        except Exception:
            pass
