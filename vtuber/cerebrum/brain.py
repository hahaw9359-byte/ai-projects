"""
大脑 —— 消费者 + 抢占者。

它的全部工作就是这一个循环：

    等小脑投递 → 读行为脑快照 → 抢画面 → 流式生成 → 按句吐出 → 释放画面

三个关键点：
  1. 没输入时它挂起在 in_q.get() 上，不占 CPU —— 它不轮询
  2. 抢画面 / 释放，就是调行为脑的 interrupt() / resume()
  3. ★ finally 里必须释放 —— LLM 报错、TTS 崩、网络断，
     都不能让行为脑被"永久压制"，否则直播就黑屏了
"""
from __future__ import annotations

import asyncio
import logging

from cerebrum.parser import EmotionStreamParser

log = logging.getLogger("brain")

EMOTIONS = ["开心", "惊讶", "认真", "害羞", "无奈", "兴奋", "温柔"]

_PROMPT = """你是直播间的主播，正在直播中。

【你当前在做的事】{state}
【刚才观众说了】{messages}
【你对这个人的记忆】{memories}
【小脑判断：观众想问的产品】{产品线索}
【商品资料（观众问到产品时，只依据这里回答）】
{商品资料}

要求：
- 像真主播一样口语化地回应，一两句话就够，别长篇大论
- 每句话前面用 [情绪] 标注，可用情绪：{emotions}
- 观众送礼物或点赞时，先真诚感谢；具体礼物要说出来（比如"谢谢老铁的火箭"）
- 商品问题依据【商品资料】回答：有信息就答，没有就说"这个我帮你确认一下"
- 不要编造型号、价格、规格 —— 不知道的绝不瞎说
- 直接输出台词，不要任何解释或格式说明
"""


class Brain:
    def __init__(self, in_q, shared, memory, llm, perform=None,
                 on_text=None, emotions: list[str] | None = None,
                 kb=None):
        self.in_q = in_q                    # 小脑投递过来的队列
        self.shared = shared
        self.memory = memory
        self.llm = llm
        self.perform = perform              # 行为脑（用来抢/放画面）
        self.on_text = on_text or self._default_sink
        self.emotions = emotions or EMOTIONS
        self.kb = kb                        # 商品知识库（观众问产品时检索）

        self.handled = 0                    # 处理了几批

    # ── 主循环 ───────────────────────────────────────
    async def loop(self) -> None:
        while True:
            payload = await self.in_q.get()        # ★ 没输入时挂起在这儿
            try:
                await self.handle(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # 兜底：任何没被 handle 接住的异常，都不能让这条循环死掉
                # （它一死，TaskGroup 会把整个子线程带走 = 所有弹幕从此没人回）
                print(f"      [大脑] 处理出错（{type(e).__name__}: {e}）—— 继续处理下一批")

    async def handle(self, payload) -> None:
        snap = self.shared.snapshot()
        log.info("抢画面 → 回应 %s（%d 条）", payload.primary_name, len(payload.messages))
        if self.perform:
            await self.perform.interrupt()         # 抢画面
        try:
            parser = EmotionStreamParser(allowed=set(self.emotions))
            prompt = self._build_prompt(payload, snap)
            async for chunk in self.llm.stream(prompt):
                for emo, sent in parser.feed(chunk):
                    await self.on_text(emo, sent)
            for emo, sent in parser.flush():       # 流结束，吐出残留
                await self.on_text(emo, sent)
            self.handled += 1
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # ★ LLM 网络抖动 / API 报错，只跳过这一批，绝不向上抛 ——
            #   原来没这层保护：模型一次调用失败 = 整条大脑循环死掉 = 后面所有弹幕没人理
            print(f"      [大脑] 这一批生成失败（{type(e).__name__}: {e}）—— 跳过，继续听弹幕")
        finally:
            if self.perform:
                await self.perform.resume()        # ★ 必须释放，报错也要放
            log.info("释放画面")

    # ── 组装 prompt ──────────────────────────────────
    def _build_prompt(self, payload, snap: dict) -> str:
        _类 = {"danmaku": "说", "gift": "送出礼物", "superchat": "醒目留言", "like": "点赞"}
        msgs = "\n".join(f"{m.user_name}（{_类.get(m.kind, m.kind)}）：{m.text}" for m in payload.messages)
        memories = "、".join(payload.memories) if payload.memories else "（第一次见，没有记录）"

        # ★ 商品资料：检索 query 的优先级 = 小脑开智的线索 > 整批观众的话
        #   ⚠️ 为什么不用 payload.text：那个只含 primary_user 说的话。
        #      同批里"有人送礼 + 另一人问产品"时，primary 被礼物占走，
        #      query 就只剩礼物文本 → 真正的买家问题被丢掉。
        #      检索要"信息最大化"，和"回应谁"是两件事，不能共用一份文本。
        商品资料 = "（这次没检索到相关商品，按常规回应即可）"
        if self.kb:
            查询 = payload.产品线索 or " / ".join(m.text for m in payload.messages)
            hits = self.kb.检索(查询, top_k=2)
            if hits:
                商品资料 = "\n\n".join(h.全文() for h in hits)

        if snap.get("mode") == "performing" and snap.get("skill_id"):
            state = f"正在……（才艺：{snap['skill_id']}），刚被打断"
        else:
            state = "空闲"
        return _PROMPT.format(
            state=state, messages=msgs, memories=memories,
            emotions="/".join(self.emotions),
            商品资料=商品资料,
            产品线索=payload.产品线索 or "（没有明显产品问题）",
        )

    # ── 默认下游：先打印（接 TTS 时替换掉）────────────
    @staticmethod
    async def _default_sink(emotion: str, text: str) -> None:
        tag = emotion or "--"
        print(f"      [大脑|{tag}] {text}")
