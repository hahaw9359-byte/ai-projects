"""webapp.py —— FastAPI 接入层

收编的本质（一句话）：
    子线程里跑的不再是 asyncio.run(流水线())，而是 uvicorn；
    循环由 uvicorn 建，流水线六任务用 create_task 挂在它的循环上 ——
    全系统只剩一个循环，端点和队列同住，直接 await，不走桥。

三块内容：
    造app()      —— FastAPI 本体：lifespan（起/停流水线）+ 控制端点 + 控制台页面
    启动服务器()  —— 子线程入口（run_vtuber.py 调它，一行替换 asyncio.run）
    请求关闭()    —— 主线程收场时调：让 uvicorn 走优雅关闭（触发 lifespan 关闭段）

端点一览（浏览器开 http://127.0.0.1:8000 是控制台页面；接口文档：/docs）：
    GET  /           控制台页面（webui.html）
    GET  /状态       后台看板：黑板 / 队列 / 行为脑 / 小脑 / 大脑 / 任务健康
    POST /状态/暂停   停卖货吐字
    POST /状态/继续   恢复卖货
    GET  /才艺       可用才艺 + 当前才艺
    POST /才艺       切换才艺（说完当前句生效）
    POST /说         让主播念一句
    GET  /用量       token 预估（字数粗估）
    GET  /弹幕       弹幕源连接状态（在抓吗 / 断了吗 / 最近收到什么）
    GET  /模型       可用 Live2D 形象 + 当前形象
    POST /模型       切换形象（黑板下指令，主线程执行）
    GET  /文档       可用卖货文档 + 当前（放新文档：丢进「卖货文档/」文件夹）
    POST /文档       切换卖货文档（下一轮话术生效）

依赖：fastapi uvicorn（已装进项目 venv）
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

from pipeline import 装好流水线, 打统计, 合成工人, 播放工人
from cerebrum.llm import 账面快照
from core.knowledge import 记上次文档, 扫文档库, 商品知识库
from voice import board

项目目录 = os.path.dirname(os.path.abspath(__file__))

# ── Live2D 模型库（和 stage/render.py 用的是同一处）─────────
模型库目录 = os.path.join(项目目录, "stage", "Resources", "v3")

# ── 卖货文档库（和 pipeline 装好流水线用的是同一处）─────────
文档目录 = os.path.join(项目目录, "卖货文档")


def 扫模型库() -> dict[str, str]:
    """扫模型库：{文件夹名: model3.json 入口路径}。"""
    出: dict[str, str] = {}
    if not os.path.isdir(模型库目录):
        return 出
    for 文件夹 in sorted(os.listdir(模型库目录)):
        在这 = os.path.join(模型库目录, 文件夹)
        if not os.path.isdir(在这):
            continue
        for 文件 in sorted(os.listdir(在这)):
            if 文件.endswith(".model3.json"):
                出[文件夹] = os.path.join(在这, 文件)
                break
    return 出


def 造app(用假模型: bool = False) -> FastAPI:
    """造 FastAPI 应用：lifespan 在这儿、端点也在这儿。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ══════ 启动段：服务起来时跑一次 ══════
        组件 = 装好流水线(用假模型=用假模型)   # 原来 流水线() 的前半段
        app.state.组件 = 组件                 # 端点们靠它拿队列 / 行为脑
        app.state.开始时刻 = time.time()

        # 六个任务：只"建出来"，谁都不等 ——
        # 它们生在"执行 create_task 时正在跑的循环"上（= uvicorn 的循环）
        # ★ TTS 是两段流水线：合成工人一直往前跑，播放工人拿到成品就放 ——
        #   这样播放第 N 句时第 N+1 句已经合成好了，句间空档从 1.78 秒降到 ~0
        任务们 = [
            asyncio.create_task(组件.表演.loop(), name="行为脑"),
            asyncio.create_task(组件.小脑.run(), name="小脑"),
            asyncio.create_task(组件.大脑.loop(), name="大脑"),
            asyncio.create_task(组件.沉淀.loop(), name="沉淀"),
            asyncio.create_task(合成工人(组件.队列, 组件.音频队列), name="tts合成"),
            asyncio.create_task(播放工人(组件.音频队列), name="tts播放"),
        ]
        app.state.任务们 = 任务们              # /状态 里报"任务健康"

        # 共患难 —— 原来 TaskGroup 自动干的活，现在手写这几行：
        # 任一个任务"意外死"（不是正常取消）→ 请求整个服务收摊，不留半死系统
        def 收摊(t: asyncio.Task) -> None:
            if t.cancelled():
                return                          # 正常关闭时的取消：不管
            print(f"\n[监督] {t.get_name()} 意外死了：{t.exception()!r} → 请求收摊")
            server = getattr(app.state, "server", None)
            if server is not None:
                server.should_exit = True       # uvicorn 收到 → 走关闭流程

        for t in 任务们:
            t.add_done_callback(收摊)

        yield   # ← 函数停在这里。停着的整段 = 服务活着的时间

        # ══════ 关闭段：服务关闭时跑一次 ══════
        for t in 任务们:
            t.cancel()                          # 先喊停
        await asyncio.gather(*任务们, return_exceptions=True)   # 再等它们都停下
        打统计(组件)                             # 收场统计（原 流水线() 尾段）

    app = FastAPI(lifespan=lifespan)

    # ────────────── ① 控制台页面 ──────────────

    @app.get("/")
    async def 控制台():
        """操作台页面（页面里的按钮会自动调下面的 API）。"""
        return FileResponse(os.path.join(项目目录, "webui.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    async def 站点图标():
        """浏览器讨要的小图标：没有就静默答一下，免得日志里全是 404 噪音。"""
        return Response(status_code=204)

    # ────────────── ② 状态组（后台看板）──────────────

    @app.get("/状态")
    async def 状态():
        """一屏看全直播健康度。"""
        组件 = app.state.组件
        return {
            "运行时长(秒)": round(time.time() - app.state.开始时刻, 1),
            "在说": board.黑板["在说"],
            "情绪": board.黑板["情绪"],
            "队列": {"排着": 组件.队列.qsize(), "上限": 组件.队列.maxsize},
            "行为脑": {
                "模式": 组件.表演.mode,                      # idle / performing / suppressed
                "用户暂停": 组件.表演.用户暂停,               # 网页「暂停」按钮的状态
                "才艺": 组件.表演._pending or getattr(组件.表演.current, "id", None),
                "吐字段数": 组件.表演.emitted,
                "被抢次数": 组件.表演.interrupts,
            },
            "小脑": {**组件.小脑.stats, "丢弃明细": 组件.小脑.pipeline.简报()},
            "大脑": {"处理批数": 组件.大脑.handled},
            "任务健康": {t.get_name(): ("已停机" if t.done() else "在跑") for t in app.state.任务们},
        }

    @app.post("/状态/暂停")
    async def 暂停():
        """停卖货吐字 + 清掉排队的卖货（正在说的这一句会说完）。

        两个点（2026-10-16 实测修）：
          · 走"壳"的 interrupt → 顺便清掉排着的卖货，停得更干脆
          · 打"用户暂停"标 → 之后弹幕抢完画面也不自动恢复卖货
        """
        组件 = app.state.组件
        组件.表演.用户暂停 = True
        丢了 = await 组件.表演开关.interrupt()
        return {"行为脑": "已暂停", "清掉排队的卖货": 丢了, "说明": "正在说的这一句会说完"}

    @app.post("/状态/继续")
    async def 继续():
        """恢复卖货吐字。"""
        组件 = app.state.组件
        组件.表演.用户暂停 = False
        await 组件.表演.resume()
        return {"行为脑": "已恢复"}

    # ────────────── ③ 才艺组 ──────────────

    @app.get("/才艺")
    async def 看才艺():
        """可用才艺 + 当前才艺。"""
        表演 = app.state.组件.表演
        return {
            "可用": [{"id": s.id, "名字": s.name} for s in 表演._skills.values()],
            "当前": 表演._pending or getattr(表演.current, "id", None),
        }

    @app.post("/才艺")
    async def 切才艺(名字: str):
        """切换才艺 —— 当前这句说完后生效，不打断正在说的字。

        现在只有一种（sell），接口先给出去 —— 加新才艺只需 register，这里不用动。
        """
        try:
            app.state.组件.表演.switch_to(名字)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return {"切换中": 名字, "生效时机": "当前这句说完之后"}

    # ────────────── ④ 人工插入 ──────────────

    @app.post("/说")
    async def 说(文本: str, 情绪: str = ""):
        """让主播念一句。

        ★ await 队列.put 直接写 —— 端点与队列同循环；不收编，这行就得过桥。
        队列满（上限 2）时请求会等 —— 那就是"背压"。
        """
        await app.state.组件.队列.put(("回应", 文本, 情绪))
        return {"排上了": 文本}

    # ────────────── ⑤ 用量 ──────────────

    @app.get("/用量")
    async def 用量():
        """token 预估（先走字数粗估，不接计费口径）。"""
        分项 = 账面快照()
        合计 = {k: sum(v.get(k, 0) for v in 分项.values()) for k in ("调用", "输入字", "输出字")}
        合计["预估token"] = 合计["输入字"] + 合计["输出字"]
        return {"分项": 分项, "合计": 合计, "口径": "中文字数粗估（约 1 字 1 token），非计费口径"}

    # ────────────── ⑥ 弹幕连接 ──────────────

    @app.get("/弹幕")
    async def 弹幕状况():
        """弹幕源状况 —— 直接读"60 秒报账"的账，不做额外追踪。"""
        源 = app.state.组件.弹幕源
        if getattr(源, "_统计", None) is None:      # SilentSource：没接弹幕源
            return {"结论": "未接入弹幕源（安静模式）", "说明": "看 .env 有没有 BILI_ROOM_ID"}
        数据包 = 源._统计.get("数据包", 0)
        用户静默 = round(time.time() - 源._上次弹幕, 1) if 源._上次弹幕 else None
        return {
            "结论": "正常（在收包）" if 数据包 > 0 else "近 60 秒无数据包（刚启动 / 断线重连中）",
            "最近一次报账": 源._上次报账,            # 上一个完整 60 秒的定论
            "当前滚动": dict(源._统计),
            "最后用户消息_秒前": 用户静默,           # 区分"没人说话"vs"抓不到"
            "房间": 源.room_id,
            "人气": 源.人气,
        }

    # ────────────── ⑦ 模型组（Live2D 形象）──────────────

    @app.get("/模型")
    async def 看模型():
        """可用形象 + 当前形象。加新形象：把文件夹放进 stage/Resources/v3/ 即可。"""
        return {
            "可用": list(扫模型库()),
            "当前": board.黑板["当前模型"],
        }

    @app.post("/模型")
    async def 切模型(名字: str):
        """切换形象 —— 黑板下指令，主线程下一帧自己加载（画面会顿一下）。"""
        库 = 扫模型库()
        if 名字 not in 库:
            raise HTTPException(status_code=404, detail=f"没有这个模型：{名字}（可用：{list(库)}）")
        board.黑板["要换模型"] = 库[名字]
        return {"已下指令": 名字, "生效时机": "主线程下一帧（加载期间画面会顿一下）"}

    # ────────────── ⑧ 卖货文档（话术的资料库）──────────────

    @app.get("/文档")
    async def 看文档():
        """可用卖货文档 + 当前用的哪份。放新文档：丢进「卖货文档/」文件夹即可。"""
        kb = app.state.组件.卖货.知识库
        return {
            "可用": list(扫文档库(文档目录)),
            "当前": os.path.basename(kb.path) if kb else None,
        }

    @app.post("/文档")
    async def 切文档(名字: str):
        """切换卖货文档 —— 直接换 kb 引用，下一轮话术生效。

        为什么这次不用黑板：文档只在子线程循环里被用（卖货 / 大脑），
        而端点与它们同住一个循环 —— 直接改引用就行。
        （换模型要黑板，是因为渲染在主线程；换文档在循环内部，不需要。）
        """
        库 = 扫文档库(文档目录)
        if 名字 not in 库:
            raise HTTPException(status_code=404, detail=f"没有这份文档：{名字}（可用：{list(库)}）")
        新kb = 商品知识库(库[名字])                 # 载入 + 切块（几千字，毫秒级）
        组件 = app.state.组件
        组件.卖货.知识库 = 新kb                     # ★ 卖货话术：下一轮开始讲新文档
        组件.大脑.kb = 新kb                         # ★ 弹幕问产品：检索同一份
        记上次文档(文档目录, 名字)                   # 重启后仍是这份
        出 = {"已切换": 名字, "块数": len(新kb.块们), "生效时机": "下一轮话术开始使用"}
        if not 新kb.块们:
            出["提醒"] = "这份文档没切出内容 —— 检查有没有 ## / ### 小节和正文"
        return 出

    return app


# ── 模块级"当前服务器"引用（给 请求关闭() 用）──────────────
_服务器: uvicorn.Server | None = None


def 启动服务器(用假模型: bool = False, 端口: int = 8000) -> None:
    """子线程入口 —— run_vtuber.py 里一行替换 asyncio.run(流水线())。

    uvicorn 建循环 → 跑 app（lifespan 前段起流水线）→ 服务存活 →
    收到 should_exit（关窗 / 共患难）→ lifespan 后段收摊。
    """
    global _服务器
    app = 造app(用假模型=用假模型)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=端口, log_level="info"))
    _服务器 = server
    app.state.server = server            # 让 lifespan 里的"收摊"能找到它
    server.run()


def 请求关闭() -> None:
    """主线程收场时调：请 uvicorn 走优雅关闭（触发 lifespan 关闭段）。"""
    if _服务器 is not None:
        _服务器.should_exit = True
