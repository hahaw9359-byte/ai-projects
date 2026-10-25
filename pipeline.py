"""流水线 —— 小脑 + 大脑 + 行为脑 + TTS。

**这一整套，就是「子线程」里跑的东西。**

主线程只负责画（stage/render.py）。两边通过 voice/board.py 那块黑板联系。

⚠️ 这里不初始化声卡 —— 那是主线程启动时干的（pygame 的东西统一由主线程管）。

┌──────────────────────────────────────────────────────────┐
│  B站弹幕源 → 小脑 → brain_q → 大脑 ─┐                     │
│  （.env 有房间号就连真弹幕，          ├─→ 队列 → TTS 工人   │
│    没有就退化成安静源）   共享层/记忆 ← 行为脑 ─┘    ↓      │
│                    ↑                      黑板 → 主线程画  │
│              沉淀任务（定时提炼对话）                       │
└──────────────────────────────────────────────────────────┘

三条链共用一个 TTS 队列是安全的：抢画面的机制保证了
**同一时刻只有一个人在说话**（行为脑被压制时它不吐字）。
"""
from __future__ import annotations

import asyncio
import os
import time

from core import textvec
from core.danmaku_memory import 弹幕记忆
from core.knowledge import 读上次文档, 扫文档库, 商品知识库
from core.memory import UserMemory
from core.shared import SharedState
from cerebellum import BilibiliSource, Cerebellum, SilentSource
from cerebrum import Brain, DeepSeekLLM, Distiller, FakeLLM
from config import 读env
from performance import PerformBrain, SellSkill
from voice import board, mouth, tts


# ══════════════════════════════════════════════════════
# TTS 工人 —— 从队列取句子，一句一句说
#   队列里每一项是 (谁说的, 文本, 情绪)：
#       "卖货"  = 行为脑的填充话术（随时可丢）  情绪固定"热情"
#       "回应"  = 大脑对弹幕的回应（不能丢）    情绪来自 LLM 的 [标记]
#   情绪 → 挂黑板 → 渲染层查表 → 驱动眼/眉/头/脸红（voice/face.py）
# ══════════════════════════════════════════════════════
async def 合成工人(文本队列: asyncio.Queue, 音频队列: asyncio.Queue) -> None:
    """TTS 第一阶段：**持续往前合成**。

    为什么拆两段（2026-10-22）：
        旧版是串行 —— 合成 1.78 秒 → 播放 5.4 秒 → 再合成 1.78 秒，
        **每句之间固定静默 1.78 秒**（实测数据）。
        拆开之后，播放第 N 句时第 N+1 句已经在合成：
        只要"合成比播放快"，句间空档就是 0。
    """
    while True:
        项 = await 文本队列.get()             # 队列空 → 挂起等着（不烧 CPU）
        if 项 is None:
            await 音频队列.put(None)          # 结束信号往下传
            return
        来源, 文本, 情绪 = 项

        try:
            print(f"\n  [TTS合成·{来源}｜{情绪 or '中性'}] {文本}")
            音频, 词表 = await tts.合成(文本, 打日志=True)
            if not 音频:
                continue
            嘴型表 = mouth.造嘴型表(词表)
            # ★ 音频队列满了就等 —— 这就是背压：最多领先 2 句，不白花合成额度
            await 音频队列.put((来源, 情绪, 音频, 嘴型表, 文本))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # ★ 火山 TTS 网络抖动只跳过这一句，绝不能死 ——
            #   这条工人一死，TaskGroup 会带走整个子线程（表现：弹幕全部没人回）
            print(f"      [TTS] 这一句合成失败（{type(e).__name__}: {e}）—— 跳过继续")


async def 播放工人(音频队列: asyncio.Queue) -> None:
    """TTS 第二阶段：**只负责放**。播完立刻取下一句（那时它已经合成好了）。"""
    while True:
        件 = await 音频队列.get()
        if 件 is None:
            return
        来源, 情绪, 音频, 嘴型表, 文本 = 件

        try:
            # ★ 黑板在"播放时"写，不在"合成时"写 ——
            #   嘴型表的起点必须是真正出声的那一刻，不然嘴和声音对不上。
            #   嘴型表 → 管嘴（每个字一个形状）；情绪 → 管脸（眼/眉/头/脸红）
            board.播一句(嘴型表, time.time(), 情绪)
            print(f"      [黑板] 挂上 {len(嘴型表)} 行嘴型表："
                  + "  ".join(f"{v}@{起:.1f}~{止:.1f}" for v, 起, 止 in 嘴型表[:4])
                  + (" ..." if len(嘴型表) > 4 else ""))

            tts.播放(音频)
            await asyncio.sleep(tts.时长(音频))    # 等这一句放完
            board.说完了()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"      [TTS] 播放失败（{type(e).__name__}: {e}）—— 跳过继续")
            board.说完了()                         # 让嘴复位，别停在最后一个口型


# ══════════════════════════════════════════════════════
# 抢画面时，把队列里排着的旧话丢掉
# ══════════════════════════════════════════════════════
def _清掉卖货(队列: asyncio.Queue) -> int:
    """把队列里"卖货"的项丢掉，其余放回去。返回丢了几条。

    文本队列的项是 (来源, 文本, 情绪)，音频队列的是
    (来源, 情绪, 音频, 嘴型表, 文本) —— 两者的 项[0] 都是来源，所以能共用。
    """
    保留: list = []
    丢了 = 0
    while True:
        try:
            项 = 队列.get_nowait()
        except asyncio.QueueEmpty:
            break
        if 项 and 项[0] == "卖货":
            丢了 += 1
        else:
            保留.append(项)
    for 项 in 保留:
        try:
            队列.put_nowait(项)
        except asyncio.QueueFull:       # 理论上不会，兜一下
            break
    return 丢了


class 抢画面时清队列:
    """给行为脑套一层。

    **为什么必须清**：抢画面的意思是"填充话术不用说了"。
    可队列里还排着没播的卖货（一句要放 4~6 秒），
    不清的话，大脑的回应要排在它们后面 —— 十几秒的冷场。

    **⚠️ 但只丢"卖货"，不能丢"回应"**：
    弹幕每 3 秒来一批，而 TTS 说一句要 5 秒 ——
    如果新的一次抢画面把上一批"大脑的话"也丢了，
    那就永远轮不到大脑说话（实测过：一句都听不到）。

    **要清两个队列（2026-10-22）**：
        拆了预合成之后，句子会同时存在于两处 ——
        文本队列（还没合成）和音频队列（已经合成、还没播）。
        只清一个，另一处的卖货还会播出来。

    用法：Brain(..., perform=抢画面时清队列(表演, 队列, 音频队列))
    （Brain 只会调 interrupt / resume 这两个方法）
    """

    def __init__(self, 真身, 队列: asyncio.Queue, 音频队列: asyncio.Queue | None = None):
        self._真身 = 真身
        self._队列 = 队列
        self._音频队列 = 音频队列

    async def interrupt(self) -> int:
        """停吐字 + 清掉排队的卖货（文本队列 + 音频队列）。返回丢了几条。

        大脑抢画面走它；网页「暂停」按钮也走它（同一套队列规则：
        "卖货"随时可丢，"回应"永远保留）。
        """
        await self._真身.interrupt()

        丢文本 = _清掉卖货(self._队列)
        丢音频 = _清掉卖货(self._音频队列) if self._音频队列 is not None else 0
        if 丢文本 or 丢音频:
            print(f"      [队列] 丢掉 {丢文本} 句待合成卖货 + {丢音频} 段已合成音频"
                  f"（回应保留）")
        return 丢文本 + 丢音频

    async def resume(self) -> None:
        await self._真身.resume()

    # 其他属性原样转发（比如以后要用 行为脑.emitted 统计）
    def __getattr__(self, name):
        return getattr(self._真身, name)


# 记忆的编码器用 core/textvec 的「轻量文本向量」（2-gram 哈希）。
# 原来是 md5 假向量（检索等于随机）——已换掉。
# 想升级成语义级（比如本地 bge 模型），只换 core/textvec.py 里的编码函数即可。


# ══════════════════════════════════════════════════════
# 零件盒：装好的流水线（谁要用哪个部件，就从这儿拿）
#   建它的是 装好流水线()；用它的有：
#     webapp 的 lifespan（建六个任务）、各个端点（读状态/下指令）、打统计（收场报表）
# ══════════════════════════════════════════════════════
class 流水线组件:
    """流水线的零件盒 —— 五个脑 + 各种引用。"""

    def __init__(self, *, 队列, 音频队列, 表演, 表演开关, 小脑, 大脑, 沉淀, 弹幕源, 卖货, 记忆, 模型名):
        self.队列 = 队列
        self.音频队列 = 音频队列  # 预合成：合成好的成品排队等播
        self.表演 = 表演
        self.表演开关 = 表演开关  # 行为脑的"壳"：interrupt 顺带清排队卖货（抢画面/网页暂停共用）
        self.小脑 = 小脑
        self.大脑 = 大脑
        self.沉淀 = 沉淀
        self.弹幕源 = 弹幕源      # /弹幕 端点用
        self.卖货 = 卖货          # 打统计用
        self.记忆 = 记忆          # 打统计用
        self.模型名 = 模型名      # 打统计用


# ══════════════════════════════════════════════════════
# 装好流水线 —— 原 流水线() 的前半段：造队列、四个脑、弹幕源、知识库……
#   只装配、不启动。启动（建任务）由调用方决定：
#     正式直播 → webapp 的 lifespan 里 create_task ×5
#     命令行   → 流水线()（薄壳）里 TaskGroup
# ══════════════════════════════════════════════════════
def 装好流水线(用假模型: bool = False) -> 流水线组件:
    """装配整条流水线，返回零件盒。纯同步，几毫秒搞定。"""

    # ── 造模型（想换模型就改这两行）────────────────────
    def 造对话模型(标签: str, key名: str = "Deepseek_key"):
        """标签 = 用量记账的分组名（"大脑"/"卖货"/"沉淀"/"小脑开智"）→ 网页 /用量 看得到。

        key名 默认主 key；小脑开智可以传 Deepseek_key_小脑（独立并发配额）。
        ★ 没配专 key 就回落主 key —— 不能因为少配一项就让功能挂掉。
        """
        if 用假模型:
            return FakeLLM()
        专key = 读env(key名) if key名 != "Deepseek_key" else ""
        return DeepSeekLLM(model="deepseek-v4-flash", 标签=标签,
                           api_key=专key or None)
    模型名 = "假模型" if 用假模型 else "DeepSeek(deepseek-v4-flash)"

    # ★ 队列：谁抢到画面谁往这儿放，TTS 合成工人从这儿取
    #   maxsize=2 就是「背压」—— 排满 2 句，说话的人就得停下来等
    #   ★ 它同时也是"说多少"的刹车：模型不需要知道该说多久，堵住自然就停
    队列: asyncio.Queue = asyncio.Queue(maxsize=2)

    # ★ 音频队列（预合成的关键）：合成好的成品排队等播
    #   为什么也要 maxsize=2：最多领先 2 句 ——
    #     再大就是浪费（被打断时那几句的合成额度白花），
    #     太小（1）失去预合成意义（播放期间只能合 1 句，遇到长句仍会空档）
    音频队列: asyncio.Queue = asyncio.Queue(maxsize=2)

    # ★★★ 关节 ② 的接线动作：两个脑的出口都接到这个队列 ★★★
    #   队列项 = (谁说的, 文本, 情绪) —— 谁抢到画面谁说话
    #   strip() 是因为模型可能在 [情绪] 标记后面留个空格
    async def 塞队列(文本: str) -> None:
        """行为脑的出口 —— 卖货填充，抢画面时可以被丢。

        卖货固定用「热情」情绪（带货主播该有的脸）。
        """
        文本 = 文本.strip()
        if 文本:
            await 队列.put(("卖货", 文本, "热情"))

    async def 塞队列带情绪(情绪: str, 文本: str) -> None:
        """大脑的出口 —— 情绪跟着文本一起进队列。

        情绪去哪了：TTS 工人会把它挂到黑板上，渲染层每帧读它驱动表情
        （voice/face.py 里的"情绪 → 脸部参数"表）。
        """
        文本 = 文本.strip()
        if 文本:
            await 队列.put(("回应", 文本, 情绪))

    # ── 共享资源：三个脑拿的是同一份 ──────────────────
    shared = SharedState()
    memory = UserMemory(encoder=textvec.异步编码)   

    # ── 卖货文档库（切块 + 检索）──────────────────────
    #   文档放在 vtuber/卖货文档/ 文件夹（.txt，多份可切换，改内容不用动代码）
    #   启动选哪份：优先"上次切过的"（.当前文档 小标记），否则按文件名第一份
    #   运行中切换：网页 POST /文档（换 kb 引用，下一轮话术生效）
    #   切分带来两件事：
    #     · 观众问产品 → 大脑只拿「最相关的 1~2 块」回答（不塞整本目录）
    #     · 卖货填充   → 每轮取「下一块」轮换介绍（像真主播一个个讲）
    项目目录 = os.path.dirname(os.path.abspath(__file__))
    文档目录 = os.path.join(项目目录, "卖货文档")
    文档们 = 扫文档库(文档目录)
    kb = None
    if 文档们:
        选中 = 读上次文档(文档目录)
        if 选中 not in 文档们:
            选中 = sorted(文档们)[0]
        kb = 商品知识库(文档们[选中])
        print(f"      [知识库] 已载入「{选中}」{kb.stats()['块数']} 块"
              f"（卖货文档/ 共 {len(文档们)} 份，网页可切换）")
    else:
        # 兼容旧位置（vtuber/商品文档.txt）——建议搬进「卖货文档/」文件夹
        旧路径 = os.path.join(项目目录, "商品文档.txt")
        if os.path.exists(旧路径):
            kb = 商品知识库(旧路径)
            print("      [知识库] 已载入旧位置商品文档（建议搬进「卖货文档/」文件夹）")
        else:
            print("      [知识库] ⚠️「卖货文档/」里没有 .txt → 先自由发挥")

    # ── 行为脑（画面的默认持有者）────────────────────
    卖货 = SellSkill(llm=造对话模型("卖货"), 知识库=kb)
    表演 = PerformBrain(shared=shared, on_text=塞队列)
    表演.register(卖货)
    表演.switch_to("sell")

    # ── 小脑开智（可选）：粗筛命中"产品问题"时，提纯成一句话 ─────────
    #   开关在 .env：小脑开智=1 → 启用；不填/0 → 关（不会悄悄花钱）
    #   key 走 Deepseek_key_小脑（没配就回落主 key，避免和大脑抢并发）
    开智 = None
    if (读env("小脑开智") or "").strip() in ("1", "true", "True", "开", "是"):
        开智 = 造对话模型("小脑开智", key名="Deepseek_key_小脑")
        print("      [小脑] 开智已启用（粗筛命中才调用，闲聊不花钱）")
    else:
        print("      [小脑] 开智未启用（.env 里设 小脑开智=1 打开）")

    # ── 弹幕记忆：SQLite 单文件（core/db.py）────────────
    #   作用：大脑回应时会带上"这个人之前说过什么"
    #   ★ 全局唯一的"落盘记忆" —— 重启不丢；而且**不常驻内存**（查几条读几条）
    #   ★ 必须先于"弹幕源"创建：源收到弹幕时要往库里写（双写）
    弹幕记忆例 = 弹幕记忆()
    清了几条 = 弹幕记忆例.清理(保留天数=90)      # 弹幕按时间衰减；用户事实不在这里清
    if 清了几条:
        print(f"      [记忆] 已清理 {清了几条} 条 90 天前的旧弹幕")
    忆统计 = 弹幕记忆例.统计()
    if 忆统计["弹幕条数"]:
        print(f"      [记忆] 库已就绪：{忆统计['人数']} 人说过话（共 {忆统计['弹幕条数']} 条）"
              f" → {弹幕记忆例.库路径}")
    else:
        print(f"      [记忆] 库是空的（第一次跑正常）→ {弹幕记忆例.库路径}")

    # ── 小脑（弹幕 → 过滤 → 攒批 → 投递）─────────────
    #   弹幕源怎么选：看 .env 里有没有 BILI_ROOM_ID
    #     有 → BilibiliSource：连你直播间，收真弹幕/礼物/点赞
    #     没有 → SilentSource：永远没输入，只剩卖货填充（不会报错）
    房间号 = (读env("BILI_ROOM_ID") or "").strip()
    if 房间号:
        print(f"      [弹幕] 接入 B站房间 {房间号}（真弹幕 / 礼物 / 点赞）")
        弹幕源 = BilibiliSource(room_id=int(房间号), 记忆=弹幕记忆例)
    else:
        print("      [弹幕] .env 没配 BILI_ROOM_ID → 安静模式（只有卖货，不响应弹幕）")
        弹幕源 = SilentSource()

    brain_q: asyncio.Queue = asyncio.Queue(maxsize=100)
    小脑 = Cerebellum(
        source=弹幕源,
        out_q=brain_q,
        memory=memory,
        弹幕记忆=弹幕记忆例,
        开智=开智,
        shared=shared,
        # 攒批规则（"几条一抓、几秒一放"）：
        #   够 batch_n 条 或 距第一条满 batch_t 秒，先到先发
        #   3 条/3 秒太钝（等你 3 秒 + 合成 1.5 秒 = 5 秒才出声），调成 2 条/2 秒
        batch_n=2,
        batch_t=2.0,
    )

    # ── 大脑（抢画面 → 生成 → 释放）──────────────────
    #   ★ perform 传的是"套了一层"的行为脑：它被抢的瞬间会清空队列，
    #     好让大脑的话立刻能说（不然要排在 2 句卖货后面，空窗十几秒）
    #   ★ 这个"壳"网页的「暂停」按钮也用（停吐字 + 清排队卖货，同一套规则）
    表演开关 = 抢画面时清队列(表演, 队列, 音频队列)
    大脑 = Brain(
        in_q=brain_q, shared=shared, memory=memory,
        llm=造对话模型("大脑"),                          # 真模型：看弹幕现回话
        perform=表演开关,
        on_text=塞队列带情绪,
        kb=kb,                                           # ★ 商品知识库：弹幕问产品时检索
    )

    # ── 记忆沉淀（定时把对话提炼成长期事实）────────────
    沉淀 = Distiller(
        shared=shared, memory=memory,
        llm=造对话模型("沉淀"),                           # ★ 真模型提炼（原来是假返回的 FakeDistillLLM）
        interval=300.0,                                  # 5 分钟一次
        min_lines=4,
    )

    # ── 装配完成，把零件放进盒子 ──────────────────────
    return 流水线组件(
        队列=队列, 音频队列=音频队列,
        表演=表演, 表演开关=表演开关, 小脑=小脑, 大脑=大脑, 沉淀=沉淀,
        弹幕源=弹幕源, 卖货=卖货, 记忆=memory, 模型名=模型名,
    )


# ══════════════════════════════════════════════════════
# 打统计 —— 原 流水线() 的尾部：收场报表
#   lifespan 的关闭段 / 薄壳 都在这儿调一下，直播结束打一份小结
# ══════════════════════════════════════════════════════
def 打统计(组件: 流水线组件) -> None:
    print(f"\n=== 结束 ｜ 对话模型：{组件.模型名} ===")
    print(f"  行为脑：吐字 {组件.表演.emitted} 段，被抢 {组件.表演.interrupts} 次")
    print(f"  卖货  ：{组件.卖货.stats()}")
    print(f"  小脑  ：{组件.小脑.stats} | 丢弃原因：{组件.小脑.pipeline.简报()}")
    print(f"  大脑  ：处理 {组件.大脑.handled} 批")
    print(f"  记忆  ：{组件.记忆.stats()}")
    print("黑板最后状态：",
          {k: (v if k != "嘴型表" else f"{len(v)} 行") for k, v in board.黑板.items()})


# ══════════════════════════════════════════════════════
# 流水线（薄壳）—— 无 Web 的跑法（run_talk.py 等命令行在用）
#   正式直播走 webapp.启动服务器()；这里保持老行为：
#   在"当前循环"里把六个任务跑起来（TaskGroup，含共患难）
# ══════════════════════════════════════════════════════
async def 流水线(秒数: float | None = None, 用假模型: bool = False) -> None:
    """跑 小脑 + 大脑 + 行为脑 + TTS 工人。秒数=None 就跑个不停。

    用假模型=True  → 不花 API 额度，跑预设台词（只验链路时用）
    用假模型=False → DeepSeek 真模型（默认）
    """
    组件 = 装好流水线(用假模型=用假模型)

    async def 五个一起跑():
        async with asyncio.TaskGroup() as tg:
            tg.create_task(组件.表演.loop(), name="行为脑")
            tg.create_task(组件.小脑.run(), name="小脑")
            tg.create_task(组件.大脑.loop(), name="大脑")
            tg.create_task(组件.沉淀.loop(), name="沉淀")
            # TTS 拆两段：合成一直在跑，播放拿到就放 —— 句间空档归零
            tg.create_task(合成工人(组件.队列, 组件.音频队列), name="tts合成")
            tg.create_task(播放工人(组件.音频队列), name="tts播放")

    try:
        if 秒数:
            async with asyncio.timeout(秒数):
                await 五个一起跑()
        else:
            await 五个一起跑()
    except TimeoutError:
        pass

    打统计(组件)
