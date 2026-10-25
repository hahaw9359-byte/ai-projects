"""
弹幕源 —— 小脑的输入口，做成可替换接口。

    DanmakuSource   抽象接口，只要求能 `async for msg in source`
    MockSource      假弹幕，随机产出各种"应该被过滤"的样本，用来跑通骨架
    SilentSource    安静源（永远不产消息）—— 正式直播但还没接真弹幕时用
    BilibiliSource  B站真弹幕（WebSocket 实时流 + 点赞/礼物聚合）

接口只约定一件事：**吐 RawMessage**。所以换源不影响小脑任何其他代码。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import random
import struct
import time
import zlib

try:
    import brotli                     # B站弹幕的新协议用 brotli 压缩
except ImportError:                   # 没装也能跑：认证时自动降级要 zlib（标准库自带）
    brotli = None

import httpx
import websockets

from core import logfile
from core.types import RawMessage

# ── B站弹幕协议：包格式与工具 ────────────────────────────
#   每个包 = 16 字节头（全部大端） + 负载
#       [总长 4B][头长 2B=16][协议版本 2B][操作码 4B][序号 4B][负载...]
#   协议版本：0=明文JSON  1=人气值(裸int)  2=zlib压缩  3=brotli压缩
#   操作码：  2=心跳(我发)  3=心跳回应(人气值)  5=消息  7=认证(我发)  8=认证回应
_BILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")


def _打包(op: int, body: bytes = b"", ver: int = 1) -> bytes:
    return struct.pack(">IHHII", 16 + len(body), 16, ver, op, 1) + body


def _拆包(buf: bytes, 层数: int = 0) -> list[tuple[int, bytes]]:
    """把一坨字节拆成 [(操作码, 负载)]。压缩包会递归解开（zlib / brotli）。"""
    if 层数 > 3:
        return []
    出: list[tuple[int, bytes]] = []
    off, n = 0, len(buf)
    while off + 16 <= n:
        plen, hlen, ver, op, _ = struct.unpack(">IHHII", buf[off:off + 16])
        if plen < 16 or off + plen > n:
            break
        body = buf[off + hlen: off + plen]
        off += plen
        if ver == 2:
            出 += _拆包(zlib.decompress(body), 层数 + 1)
        elif ver == 3:
            if brotli is None:
                raise RuntimeError("收到 brotli 压缩包但没装 brotli 库：pip install brotli")
            出 += _拆包(brotli.decompress(body), 层数 + 1)
        else:
            出.append((op, body))
    return 出


class DanmakuSource:
    """弹幕源接口。子类实现 __anext__ 即可。"""

    def __aiter__(self):
        return self

    async def __anext__(self) -> RawMessage:
        raise StopAsyncIteration


class MockSource(DanmakuSource):
    """假弹幕源。

    刻意混杂了各种"该被过滤"的样本，这样一跑起来就能看到
    DROP / SUSPECT / PASS 三条分支各自的效果。

    ⚠️ 只用于测试链路。正式直播时换成 SilentSource（没弹幕源）
       或者 BilibiliSource（接了真弹幕）。
    """

    NORMAL = [
        "主播唱得真好", "点首歌呗", "今天状态不错啊",
        "刚进来，主播在干嘛", "这首我听过", "声音好好听",
        "什么时候下播", "来首周杰伦的", "666 好听",
    ]

    def __init__(self, users: int = 6, rate: float = 2.0, seed: int | None = None):
        self._rng = random.Random(seed)
        self._seq = 0
        self._rate = rate                     # 平均每秒几条（指数分布）
        self._users = [(f"u{i:03d}", f"观众{i}号") for i in range(users)]

    async def __anext__(self) -> RawMessage:
        await asyncio.sleep(self._rng.expovariate(self._rate))
        self._seq += 1
        uid, uname = self._rng.choice(self._users)
        r = self._rng.random()

        if r < 0.05:                                   # 礼物 → urgent 通道
            text, kind, value = "主播666", "gift", 30
        elif r < 0.11:                                 # 复读 → DedupFilter
            text, kind, value = "好听好听", "danmaku", 0
        elif r < 0.17:                                 # 纯符号 → SpamFilter
            text, kind, value = "!!!!!!!!", "danmaku", 0
        elif r < 0.22:                                 # 单字复读 → SpamFilter
            text, kind, value = "啊啊啊啊啊啊", "danmaku", 0
        elif r < 0.27:                                 # 超长 → LengthFilter
            text, kind, value = "这首歌" * 30, "danmaku", 0
        elif r < 0.32:                                 # 敏感词 → SUSPECT → LLM
            text, kind, value = "加微信xxxxx", "danmaku", 0
        else:                                          # 正常
            text, kind, value = self._rng.choice(self.NORMAL), "danmaku", 0

        return RawMessage(
            seq=self._seq, user_id=uid, user_name=uname,
            text=text, kind=kind, value=value, ts=time.time(),
        )


class SilentSource(DanmakuSource):
    """安静源 —— 永远等待，不产生任何弹幕。

    用途：**正式直播、但还没接真弹幕**的阶段。
    小脑结构完整保留（过滤 / 攒批 / 审核 / 投递都在），只是永远没有输入，
    所以大脑永远不会被触发 —— 画面完全交给行为脑（卖货话术）。

    接真弹幕时，只换这一处：
        source=SilentSource()   →   source=BilibiliSource(room_id=xxx)
    """

    async def __anext__(self) -> RawMessage:
        await asyncio.Future()        # 永远挂起：不占 CPU，也不产消息


class BilibiliSource(DanmakuSource):
    """B站直播真实弹幕源。

    工作方式（一条后台任务全包了）：
      ① HTTP 拿 token + 弹幕服务器列表（老接口 getConf，匿名可用；
         新接口 getDanmuInfo 对无 cookie 请求会风控 -352）
      ② WebSocket 连上去 → 发认证包（op=7，带 token）
      ③ 一直收包 → 拆包解压 → 解析 → 认得的转成 RawMessage 丢进内部队列
      ④ 每 30 秒发一次心跳（op=2）—— 不发会被服务器踢掉
      ⑤ 断线自动重连（外面包一层 while）

    聚合规则（必须在源层做，不然会刷屏）：
        点赞：B站点赞量极大，逐个转发会让大脑被淹没 → 攒 6 秒发一条汇总
        礼物：连击会反复推（num 递增）→ 等 2.5 秒不再更新才发一条（合并连击）
        弹幕 / 醒目留言：即时上抛

    ⚠️ 认不出来的命令（进房提示、榜单更新等）一律忽略 —— 只保留四类：
       DANMU_MSG（弹幕）/ SEND_GIFT（礼物）/ SUPER_CHAT_MESSAGE（SC）/
       LIKE_INFO_V3_CLICK（点赞）
    """

    def __init__(self, room_id: int, 点赞攒多久: float = 6.0, 礼物等多久: float = 2.5,
                 打日志: bool = True, 记忆=None):
        self.room_id = int(room_id)
        # ★ 真实房间号：直播间 URL 里的号可能是"短号"（比如房间 6 的真实号是 7734200）。
        #   token 和认证包都只认真实号 —— 传短号 = 连接能建立、心跳正常，但广播对不上。
        #   构造时先等于原值，连上前会向 B站解析一次（blivedm 同样这么做）。
        self.真实房间号 = int(room_id)
        self.人气 = 0
        # 打日志=True：每收到一条原始消息就打一行 [抓到]（在过滤之前）——
        # 排查"弹幕到底抓没抓到"时全靠它
        self.打日志 = 打日志
        # ★ 记忆（core.danmaku_memory.弹幕记忆）：收到弹幕就入库 —— 和 logfile.写 双写。
        #   为什么写在"源层"而不是"小脑处理时"：
        #     源层 = 抓到的全量（和日志口径一致）；小脑 = 过滤之后（口径会变）
        #   记忆是旁路：写失败不能影响收弹幕，所以下面 try 掉。
        self.记忆 = 记忆
        self._上次弹幕 = 0.0        # 最近一条"用户消息"（弹幕/礼物/SC/点赞）的时间，报平安用
        self._q: asyncio.Queue[RawMessage] = asyncio.Queue()
        self._seq = itertools.count(1)
        self._task: asyncio.Task | None = None

        self._点赞攒多久 = 点赞攒多久
        self._礼物等多久 = 礼物等多久
        # 60 秒报账统计 —— "到底收到了什么"一眼可见（排查丢消息全靠它）
        #   数据包：网络层收到几个包（证明连接活着）
        #   未识别：认不出的消息有几个 + 名字采样（如果有新类型消息，这里会露出来）
        self._统计 = {"数据包": 0, "弹幕": 0, "礼物": 0, "醒目留言": 0,
                     "点赞": 0, "聚合": 0, "未识别": 0}
        self._未识别样例: list[str] = []
        self._上次报账 = "（还没报过账）"    # 最近一次完整 60 秒的账（网页 /弹幕 直读）
        # 聚合缓冲：点赞按人累计；礼物按 (人,礼物) 合并连击
        self._赞: dict[str, dict] = {}          # uid -> {"name", "n"}
        self._赞起 = 0.0                        # 这一轮点赞的计时起点
        self._礼: dict[tuple, dict] = {}        # (uid, 礼物名) -> {"name","gift","num","price","ts"}

    # ── 对外只暴露一个接口：吐 RawMessage ──────────────
    async def __anext__(self) -> RawMessage:
        if self._task is None:                          # 第一次被取时才启动后台任务
            self._task = asyncio.create_task(self._跑(), name="bili-danmaku")
        return await self._q.get()

    # ── 连接 + 收包（断了就抛，由 _跑 负责重连）──────────
    async def _跑(self) -> None:
        logfile.写大标题(f"{time.strftime('%Y-%m-%d %H:%M:%S')} 启动｜房间 {self.room_id}")
        print(f"      [弹幕] 抓包日志 → {logfile.路径}", flush=True)
        while True:
            try:
                await self._连上并收()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"      [弹幕] 连接断了（{type(e).__name__}: {e}），2 秒后重连")
                logfile.写(f"连接断了（{type(e).__name__}: {e}），2 秒后重连")
                await asyncio.sleep(2)          # 别裸奔重试，会刷屏

    async def _拿弹幕地址(self) -> tuple[str, list[str]]:
        """HTTP 换 token + 服务器列表。"""
        头 = {"User-Agent": _BILI_UA,
              "Referer": f"https://live.bilibili.com/{self.room_id}"}
        async with httpx.AsyncClient(timeout=15) as c:
            # ★ 第 0 步：短号 → 真实房间号。
            #   直播间 URL 里的号可能是短号（比如房间 6 → 真实号 7734200）。
            #   token 和认证包都只认真实号。（blivedm 同样先做这一步）
            try:
                r0 = await c.get(
                    "https://api.live.bilibili.com/room/v1/Room/room_init",
                    params={"id": self.room_id}, headers=头,
                )
                j0 = r0.json()
                if j0.get("code") == 0:
                    真 = (j0.get("data") or {}).get("room_id")
                    if 真:
                        self.真实房间号 = int(真)
            except Exception:
                pass

            r = await c.get(
                "https://api.live.bilibili.com/room/v1/Danmu/getConf",
                params={"room_id": self.真实房间号, "platform": "pc", "player": "web"},
                headers=头,
            )
            j = r.json()
        if j.get("code") != 0:
            raise RuntimeError(f"拿弹幕配置失败 code={j.get('code')} msg={j.get('message')}")
        data = j["data"]
        hosts = [h["host"] for h in (data.get("host_server_list") or []) if h.get("host")]
        if not hosts and data.get("host"):
            hosts = [data["host"]]
        if not hosts:
            raise RuntimeError("服务端没给弹幕服务器列表")
        return data["token"], list(dict.fromkeys(hosts))     # 去重保序

    async def _拿buvid(self) -> str:
        """拿设备指纹 buvid3 —— 认证包里必须带它。

        为什么必须有（实测对照）：
            空 buvid 时服务器"能认证通过、能收榜单/进房广播，但**弹幕/礼物一条不推**"。
            blivedm（最成熟的 B站弹幕库）也是这么做的 ——
            连接前先去拿一份 buvid3 塞进认证包。
        """
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    "https://api.bilibili.com/x/frontend/finger/spi",
                    headers={"User-Agent": _BILI_UA, "Referer": "https://www.bilibili.com/"},
                )
                d = r.json()
                return str((d.get("data") or {}).get("b_3") or "")
        except Exception:
            return ""

    async def _连上并收(self) -> None:
        token, hosts = await self._拿弹幕地址()
        buvid = await self._拿buvid()

        # 依次试服务器，谁先连上算谁（避免单点故障）
        # ★ 随机打乱候选顺序：B站的弹幕服务器是个集群，
        #   实测有"连得上、心跳正常，但弹幕推不全"的节点。
        #   打乱之后，每次重连（含 10 分钟主动刷新）都换一批先试，
        #   不会长期卡在同一个半残节点上。
        候选 = list(hosts)
        random.shuffle(候选)
        连接 = None
        最后错: Exception | None = None
        for host in 候选[:5]:
            try:
                连接 = await websockets.connect(
                    f"wss://{host}:443/sub",
                    additional_headers={"User-Agent": _BILI_UA,
                                        "Origin": "https://live.bilibili.com"},
                    max_size=None,
                    # ★ 关掉库自带的 WS 心跳（ping/pong）——
                    #   B站服务器不回 pong，库等 20 秒就误判"连接死了"自己掐断，
                    #   实测约 40 秒断一次，每次重连有 3 秒空窗、期间弹幕全丢。
                    #   保活改由协议级心跳（op=2，每 30 秒）+ 沉默看门狗负责。
                    ping_interval=None,
                )
                break
            except Exception as e:
                最后错 = e
        if 连接 is None:
            raise RuntimeError(f"弹幕服务器全部连不上：{最后错!r}")

        async with 连接 as ws:
            # ① 认证：uid=0 是"游客"，收弹幕不需要登录
            #    ★★ 两个关键字段（对照 blivedm 实测）：
            #      buvid   = 真实设备指纹（不能空！空了服务器不给推弹幕，
            #                只给"榜单/进房"这类基础广播 —— 这是踩了很久的坑）
            #      protover= 3（brotli，官方推荐值；没装 brotli 才降级 2）
            认证 = {"uid": 0, "roomid": self.真实房间号, "protover": 3 if brotli else 2,
                    "buvid": buvid, "platform": "web", "type": 2, "key": token}
            await ws.send(_打包(7, json.dumps(认证).encode("utf-8")))

            # ② 等认证回应（op=8）
            首包 = await asyncio.wait_for(ws.recv(), timeout=10)
            for op, body in _拆包(首包):
                if op == 8:
                    try:
                        code = json.loads(body).get("code")
                    except Exception:
                        code = -1
                    if code != 0:
                        raise RuntimeError(f"弹幕认证失败 code={code}")
            编号说明 = f"（真实号 {self.真实房间号}）" if self.真实房间号 != self.room_id else ""
            print(f"      [弹幕] 已连上 B站房间 {self.room_id}{编号说明} ✓", flush=True)
            logfile.写(f"已连上 ✓（节点 {host}，房间号 {self.真实房间号}）")
            self._上次弹幕 = time.time()          # 报平安从"连上"开始计时

            # ③ 收包主循环
            #   ★★ 关键修复：用"常驻 recv 任务 + asyncio.wait(…, timeout=0.5)"，
            #      而不是 wait_for(ws.recv(), timeout=0.5)。
            #
            #      区别在哪（这是丢消息的真凶）：
            #        wait_for 超时 → 会【取消】正在等待的 recv 协程；
            #                       每秒取消两次，消息在"取消竞态"里被丢掉，
            #                       实测表现 = 几十条弹幕只进来一条。
            #        asyncio.wait 超时 → 只是"这轮先回去干别的"，
            #                       recv 任务原封不动，消息一个都不会丢。
            #
            #   收包任务：从头到尾只有一个，取到一条立刻续上下一个 —— 中间没有空窗。
            收包 = asyncio.create_task(ws.recv())
            心跳 = asyncio.create_task(asyncio.sleep(15))   # 首次早点发，别掐着 30 秒的点
            上次收到 = time.time()
            上次平安 = time.time()
            连接开始 = time.time()
            self._统计 = {"数据包": 0, "弹幕": 0, "礼物": 0, "醒目留言": 0,
                         "点赞": 0, "聚合": 0, "未识别": 0}
            self._未识别样例 = []

            while True:
                done, _ = await asyncio.wait(
                    {收包, 心跳}, timeout=0.5, return_when=asyncio.FIRST_COMPLETED,
                )
                现在 = time.time()

                if 收包 in done:
                    原始 = 收包.result()
                    收包 = asyncio.create_task(ws.recv())   # 立刻续上，绝不留空窗
                    上次收到 = 现在
                    self._统计["数据包"] += 1
                    if isinstance(原始, str):
                        原始 = 原始.encode("utf-8")
                    try:
                        for op, body in _拆包(原始):
                            if op == 5 and body:
                                await self._处理(body)
                            elif op == 3 and len(body) >= 4:
                                self.人气 = int.from_bytes(body[:4], "big")
                    except Exception as e:
                        # 一个包解析失败 ≠ 连接坏了 —— 打一声继续，绝不因此重连
                        print(f"      [弹幕] 一个数据包解析失败（已跳过）：{type(e).__name__}: {e}",
                              flush=True)

                if 心跳 in done:
                    await ws.send(_打包(2, b"[object Object]"))
                    心跳 = asyncio.create_task(asyncio.sleep(30))

                # 每 60 秒报一次账 —— 连接活没活、收到了什么、有没有不认识的消息，全摆出来：
                #   数据包 40 ｜ 弹幕 5 · 礼物 1 · 点赞 3 ｜ 不认识: NOTICE_MSG, GUARD_BUY
                if self.打日志 and 现在 - 上次平安 >= 60:
                    上次平安 = 现在
                    明细 = " · ".join(f"{k} {v}" for k, v in self._统计.items()
                                      if v and k not in ("数据包", "未识别")) or "无用户消息"
                    行 = f"数据包 {self._统计['数据包']} ｜ {明细}"
                    if self._未识别样例:
                        行 += f" ｜ 不认识: {', '.join(self._未识别样例[:4])}"
                    self._上次报账 = 行          # ★ 存下这轮完整 60 秒的账（网页 /弹幕 直读）
                    print(f"      [弹幕] 连接正常｜近 60 秒：{行}", flush=True)
                    logfile.写(f"[报账] {行}")
                    self._统计 = {k: 0 for k in self._统计}
                    self._未识别样例 = []

                # 沉默看门狗：正常每 30 秒（心跳回应）至少会收到一次数据。
                # 90 秒一条都没有 = 连接已经死了（半死连接的 recv 不会报错，只会永远沉默）
                if 现在 - 上次收到 > 90:
                    raise RuntimeError("90 秒没收到任何数据，判定连接已死")

                # 到点的聚合消息发出去
                for msg in self._该发的(现在):
                    await self._q.put(msg)

                # ★ 定期刷新连接：挂满 10 分钟主动重连一次。
                #   为什么必须这么做（实测）：
                #   B站的连接挂久了会"假活"—— 心跳/系统消息还在收，但**用户弹幕不推了**。
                #   同一时刻对比：新连接收到了弹幕、挂了 10 分钟的旧连接一条没收到。
                #   重连有 ~2 秒空窗，但换来的是"一直在正常接收"。
                if 现在 - 连接开始 >= 600:
                    print("      [弹幕] 挂满 10 分钟，主动刷新连接（防'假活'）", flush=True)
                    raise RuntimeError("定期刷新连接")

    # ── 单条命令 → RawMessage 或聚合缓冲 ─────────────────
    async def _处理(self, body: bytes) -> None:
        """⚠️ 全函数包 try —— 一条"格式怪异"的消息绝不能弄死整条连接。

        连接一断就是 2 秒空窗（重连期间），空窗里到达的弹幕全丢。
        宁可跳过这一条，不可断线。
        """
        try:
            await self._处理内(body)
        except Exception as e:
            print(f"      [弹幕] 一条消息处理失败（已跳过）：{type(e).__name__}: {e}",
                  flush=True)

    async def _处理内(self, body: bytes) -> None:
        try:
            d = json.loads(body)
        except Exception:
            return
        if not isinstance(d, dict):
            return
        cmd = str(d.get("cmd", "")).split(":")[0]     # 有些命令带 :4:0:2 后缀
        现在 = time.time()

        if cmd in ("DANMU_MSG", "SEND_GIFT", "SUPER_CHAT_MESSAGE", "LIKE_INFO_V3_CLICK"):
            self._上次弹幕 = 现在                     # 有"用户消息"了（报平安用）

        if cmd == "DANMU_MSG":                        # 弹幕
            info = d.get("info")
            if not isinstance(info, list) or len(info) < 3:
                self._统计["未识别"] += 1             # 结构怪异的弹幕：记一笔，不静默
                return
            try:
                文 = str(info[1])
                名 = str(info[2][1])
                uid = str(info[2][0])
            except (IndexError, TypeError):
                self._统计["未识别"] += 1
                return
            await self._q.put(self._造("danmaku", uid, 名, 文))
            self._统计["弹幕"] += 1
            logfile.写(f"[抓到] 弹幕 | {名}：{文}")
            # ★ 双写：日志给"人看/排查"，库给"机器查"。一条弹幕进两个地方，职责不同。
            #   传 uid（不是昵称）—— 同名不串台、改昵称不断史。
            if self.记忆 is not None:
                try:
                    self.记忆.记录(uid, 名, 文)
                except Exception:
                    pass                              # 记忆是旁路，坏了不影响收弹幕
            if self.打日志:
                print(f"      [抓到] 弹幕 | {名}：{文}", flush=True)

        elif cmd == "SEND_GIFT":                      # 礼物（进聚合缓冲，等连击结束）
            data = d.get("data") or {}
            uid = str(data.get("uid"))
            礼名 = str(data.get("giftName") or "礼物")
            数量 = int(data.get("num") or 1)
            名 = str(data.get("uname") or "观众")
            self._礼[(uid, 礼名)] = {
                "name": 名, "gift": 礼名, "num": 数量,
                "price": int(data.get("discount_price") or data.get("price") or 0),
                "ts": 现在,
            }
            self._统计["礼物"] += 1
            logfile.写(f"[抓到] 礼物 | {名}：{礼名} ×{数量}")
            if self.打日志:
                print(f"      [抓到] 礼物 | {名}：{礼名} ×{数量}")

        elif cmd == "SUPER_CHAT_MESSAGE":              # 醒目留言：即时上抛（花了钱的）
            data = d.get("data") or {}
            user = data.get("user_info") or {}
            名 = str(user.get("uname") or "观众")
            文 = str(data.get("message") or "")
            await self._q.put(self._造(
                "superchat", str(data.get("uid")), 名, 文,
                int(data.get("price") or 0)))
            self._统计["醒目留言"] += 1
            logfile.写(f"[抓到] 醒目留言 | {名}：{文}")
            if self.打日志:
                print(f"      [抓到] 醒目留言 | {名}：{文}")

        elif cmd == "LIKE_INFO_V3_CLICK":              # 点赞（进聚合缓冲）
            data = d.get("data") or {}
            uid = str(data.get("uid"))
            项 = self._赞.setdefault(uid, {"name": "观众", "n": 0})
            项["name"] = str(data.get("uname") or 项["name"])
            项["n"] += int(data.get("count") or 1)
            if self._赞起 <= 0:
                self._赞起 = 现在
            self._统计["点赞"] += 1

        elif cmd == "DM_INTERACTION":                  # ★ 互动聚合（B站新版协议）
            # 这一类事件把我们以前会漏掉的消息"打包"送过来：
            #   type 102 = 弹幕聚合（重复弹幕合并成一条，真实内容在 combo 里）
            #   type 104 = 礼物聚合（"N 人在投喂"）
            #   type 106 = 点赞聚合（"N 人点赞了"）
            #   type 103/105 = 关注聚合 / 分享聚合
            # ⚠️ data.data 是"JSON 字符串"，要再解一次
            data = d.get("data") or {}
            类型 = int(data.get("type") or 0)
            内文 = data.get("data")
            if isinstance(内文, str):
                try:
                    内文 = json.loads(内文)
                except Exception:
                    内文 = {}
            内文 = 内文 or {}
            self._统计["聚合"] += 1

            if 类型 == 102:                            # 弹幕聚合
                for 条 in (内文.get("combo") or []):
                    内容 = str(条.get("content") or "").strip()
                    if not 内容:
                        continue
                    次 = int(条.get("cnt") or 1)
                    展示 = 内容 if 次 <= 1 else f"{内容}（×{次}）"
                    await self._q.put(self._造("danmaku", "aggregate", "观众们", 展示))
                    logfile.写(f"[抓到] 弹幕聚合 | {展示}")
                    if self.打日志:
                        print(f"      [抓到] 弹幕聚合 | {展示}", flush=True)

            elif 类型 == 106:                          # 点赞聚合 → 进点赞缓冲
                次 = int(内文.get("cnt") or 0)
                if 次 > 0:
                    项 = self._赞.setdefault("aggregate", {"name": "观众们", "n": 0})
                    项["n"] += 次
                    if self._赞起 <= 0:
                        self._赞起 = 现在
                    if self.打日志:
                        print(f"      [抓到] 点赞聚合 | ×{次}", flush=True)

            elif 类型 == 104:                          # 礼物聚合
                次 = int(内文.get("cnt") or 0)
                尾巴 = str(内文.get("suffix_text") or "人送了礼物")
                if 次 > 0:
                    await self._q.put(self._造("gift", "aggregate", "观众们", f"{次}{尾巴}"))
                    logfile.写(f"[抓到] 礼物聚合 | {次}{尾巴}")
                    if self.打日志:
                        print(f"      [抓到] 礼物聚合 | {次}{尾巴}", flush=True)

            elif 类型 in (103, 105):                   # 关注聚合 / 分享聚合（轻提示）
                次 = int(内文.get("cnt") or 0)
                尾巴 = str(内文.get("suffix_text") or "")
                if 次 > 0:
                    await self._q.put(self._造("danmaku", "aggregate", "观众们", f"{次}{尾巴}"))
                    logfile.写(f"[抓到] 关注/分享聚合 | {次}{尾巴}")
                    if self.打日志:
                        print(f"      [抓到] 关注/分享聚合 | {次}{尾巴}", flush=True)

        elif cmd:
            # 不认识的消息：记一笔（名字去重采样，最多 6 个），60 秒报账时一起打出来。
            # 这样"有没有新类型消息被我们漏掉"直接看得见，不用猜。
            self._统计["未识别"] += 1
            logfile.写(f"[未识别] {cmd}")
            if cmd not in self._未识别样例 and len(self._未识别样例) < 6:
                self._未识别样例.append(cmd)

    # ── 聚合到点了 → 产出汇总消息 ────────────────────────
    def _该发的(self, 现在: float) -> list[RawMessage]:
        出: list[RawMessage] = []

        # 礼物：2.5 秒没再更新 = 连击结束 → 合并发一条
        for key, g in list(self._礼.items()):
            if 现在 - g["ts"] >= self._礼物等多久:
                出.append(self._造("gift", key[0], g["name"],
                                   f"{g['gift']} ×{g['num']}", g["price"] * g["num"]))
                self._礼.pop(key, None)

        # 点赞：攒够 6 秒 → 一条汇总
        if self._赞 and 现在 - self._赞起 >= self._点赞攒多久:
            榜单 = sorted(self._赞.items(), key=lambda kv: -kv[1]["n"])
            总数 = sum(v["n"] for _, v in 榜单)
            名字 = "、".join(v["name"] for _, v in 榜单[:2])
            if len(榜单) > 2:
                名字 += f" 等{len(榜单)}人"
            出.append(self._造("like", 榜单[0][0], 名字,
                               f"为主播点赞 ×{总数}", 总数))
            logfile.写(f"[抓到] 点赞 | {名字} ×{总数}")
            if self.打日志:
                print(f"      [抓到] 点赞 | {名字} ×{总数}")
            self._赞.clear()
            self._赞起 = 0.0

        return 出

    def _造(self, kind: str, uid: str, name: str, text: str, value: int = 0) -> RawMessage:
        return RawMessage(
            seq=next(self._seq), user_id=str(uid) or "?", user_name=name or "观众",
            text=text.strip(), kind=kind, value=value, ts=time.time(),
        )
