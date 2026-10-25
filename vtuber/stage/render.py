"""舞台 —— 主线程那一格：开窗、每帧画。

它永远不等任何人。所有要"等"的事情都在子线程（pipeline.py）里。

每帧干这几件事：
    ① 读黑板 → 算「这一句播到第几秒」→ 查该摆什么嘴型（归音素）
    ①' 读黑板里的情绪               → 查该摆什么表情（归情绪）
    ② 平滑（不瞬移 —— 嘴要跟得快，脸要变得慢）
    ③ 送进模型 → Update → 画 → 上屏
"""
from __future__ import annotations

import os
import time

import live2d
import pygame

from voice import board, face, mouth

# 模型库就在本文件夹的 Resources/ 里
模型路径 = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Resources", "v3", "Haru", "Haru.model3.json",
)

宽, 高 = 800, 600
采样率 = 24000
平滑 = 0.35          # 嘴：每帧往目标挪 35%，不然嘴会一抽一抽
表情平滑 = 0.12      # 脸：慢一点（情绪要"慢慢显出来"，跟嘴的节奏不一样）

跑着 = True


def 启动():
    """开窗 + 声卡 + 加载模型。**必须在主线程调，而且要在起子线程之前调。**"""
    # 顺序不能换：先点亮 pygame → 起引擎 → 调声卡 → 开窗 → 引擎接管窗口 → 建模型
    pygame.init()
    live2d.init()

    # 声卡：必须先 quit 再 init
    #   （pygame.init() 会先把它开成 44100/立体声，之后那句 init 是不生效的）
    pygame.mixer.quit()
    pygame.mixer.init(frequency=采样率, size=-16, channels=2)
    print("      [声卡]", pygame.mixer.get_init())

    pygame.display.set_mode((宽, 高), pygame.DOUBLEBUF | pygame.OPENGL)
    # 给窗口起名 —— OBS 的"窗口采集"靠这个名字找到它（默认叫 "pygame window" 不好认）
    pygame.display.set_caption("AI 虚拟主播")
    live2d.glInit()

    model = live2d.Model()
    model.LoadModelJson(模型路径)
    model.Resize(宽, 高)
    board.黑板["当前模型"] = os.path.basename(os.path.dirname(模型路径))   # 登记给网页看
    print("      [舞台] 窗口开好了，Haru 读进内存了")
    return model


def 渲染循环(model, 秒数: float | None = None, 调试: bool = False) -> None:
    """主线程一直转这个圈。一秒 60 次。

    调试=True 时，每半秒打印一次「正在写的两个数」，用来验证嘴真的在动。
    """
    global 跑着
    当前开 = 0.0
    当前形 = 0.0
    当前表情 = face.情绪到参数("")        # 从「中性脸」出发，每帧往目标挪一点
    起始 = time.time()
    帧 = 0
    上次打印 = 0.0
    钟 = pygame.time.Clock()          # 用来限速，不然会空转到 1800+ 帧/秒

    while 跑着:
        # ⓪ 限速：一秒 60 帧。人眼看不出更高，但 CPU 会白烧
        钟.tick(60)

        # ① 收事件（不收系统会以为程序卡死）
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                跑着 = False

        # 到点自动关（测试用）
        if 秒数 and time.time() - 起始 > 秒数:
            break

        # ⚡ 查"要换模型"指令（网页下的单，主线程来执行）——
        #   子线程只写指令、不碰模型；模型的加载/绘制资源全归主线程。
        #   失败回退：新模型加载失败就继续用旧的，绝不把画面搞没
        要换 = board.黑板["要换模型"]
        if 要换:
            board.黑板["要换模型"] = None          # 先取走，防止重复执行
            try:
                新 = live2d.Model()
                新.LoadModelJson(要换)
                新.Resize(宽, 高)
                旧 = model
                model = 新                          # 下一帧起画的就是新模型
                board.黑板["当前模型"] = os.path.basename(os.path.dirname(要换))
                try:
                    旧.DestroyRenderer()            # 释放旧模型的渲染资源
                except Exception:
                    pass                             # 释放失败不致命，交给 GC
                print(f"      [舞台] 已切换模型 → {要换}")
            except Exception as e:
                print(f"      [舞台] 换模型失败（{type(e).__name__}: {e}），继续用旧的")

        # ② 读黑板，算「这一句播到第几秒」
        t = -1.0
        起点 = board.黑板["开始时刻"]
        if 起点 > 0:
            t = time.time() - 起点
            目标开, 目标形 = mouth.此刻嘴型(board.黑板["嘴型表"], t)
        else:
            目标开, 目标形 = 0.0, 0.0

        # ②' 读黑板里的情绪 → 查表情表（脸和嘴各管各的参数，不会打架）
        目标表情 = face.情绪到参数(board.黑板["情绪"])

        # ③ 平滑 → 送进模型 → 画
        当前开 += (目标开 - 当前开) * 平滑
        当前形 += (目标形 - 当前形) * 平滑
        for 名, 目标 in 目标表情.items():
            当前表情[名] += (目标 - 当前表情[名]) * 表情平滑

        model.Update()
        model.SetParamById("ParamMouthOpenY", 当前开)
        model.SetParamById("ParamMouthForm", 当前形)
        for 名, 值 in 当前表情.items():
            model.SetParamById(名, 值)
        live2d.clearBuffer()
        model.Draw()
        pygame.display.flip()

        帧 += 1
        if 调试 and time.time() - 上次打印 >= 0.5:
            上次打印 = time.time()
            情绪 = board.黑板["情绪"] or "中性"
            print(f"      [画面] 第{帧}帧  t={t:5.2f}s  情绪={情绪}  "
                  f"嘴=({当前开:.2f},{当前形:+.2f})  "
                  f"眼笑={model.GetParamValueById('ParamEyeLSmile'):.2f}  "
                  f"眉={model.GetParamValueById('ParamBrowLY'):+.2f}  "
                  f"脸红={model.GetParamValueById('ParamTere'):.2f}")


def 收场() -> None:
    global 跑着
    跑着 = True          # 让下次还能再跑
    try:
        live2d.dispose()
    except Exception:
        pass
    try:
        pygame.mixer.quit()
        pygame.quit()
    except Exception:
        pass
