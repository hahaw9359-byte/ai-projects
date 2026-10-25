"""
EmotionStreamParser —— 把流式的「情绪 + 文本」按【句子】切出来。

LLM 吐出来的原始形态（分片到达，每片可能只有两三个字）：

    "[开心]谢谢[认真]我看看……"

这个解析器负责切成：

    ("开心", "谢谢。")
    ("认真", "我看看……")

两个坑都在这儿解决：

  ① 「半截标记」：`[开` 可能落在前一片、`心]` 落在后一片
     → 未闭合的 `[` 先 hold 住，攒太久（超 TAG_MAX）才判定它不是标记

  ② 「碎片太多」：如果每来一片就往下游发，TTS 会被 2 个字的片段喂爆
     → 攒到句末标点才发。情绪变了也强制发（换情绪就得换发音）

对外只暴露两个方法：feed(片) 和 flush()（流结束时把残留吐干净）。
"""
from __future__ import annotations

TAG_MAX = 16                                  # buffer 里容忍多长还不闭合
TAG_LEN = 8                                   # 合法情绪名的最大长度
SENT_END = set("。！？!?；;\n")               # 句末标点（`…` 不算 —— 它是句中停顿，切了会出碎片）


class EmotionStreamParser:
    def __init__(self, allowed: set[str] | None = None, soft_limit: int = 80):
        self._buf = ""                        # 原始流（token 级）
        self._emo = ""                        # 最近一次解析出的情绪
        self._pend = ""                       # 攒着还没发的句子
        self._pend_emo = ""                   # ★ 这段句子属于哪个情绪（不能和 _emo 混用）
        self.allowed = allowed
        self.soft_limit = soft_limit

    # ── 对外接口 ─────────────────────────────────────
    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """喂一片，吐出若干 (情绪, 句子)。没到句末就什么都不吐。"""
        self._buf += chunk
        out: list[tuple[str, str]] = []
        for emo, text in self._parse():
            self._into_pend(emo, text, out)
        self._drain(out, final=False)
        return out

    def flush(self) -> list[tuple[str, str]]:
        """流结束：残留全部吐出去。"""
        out: list[tuple[str, str]] = []
        if self._buf:
            self._into_pend(self._emo, self._buf, out)
            self._buf = ""
        self._drain(out, final=True)
        return out

    # ── 内部 ①：词法分离（标记 vs 文本）──────────────
    def _parse(self) -> list[tuple[str, str]]:
        """返回 [(这段文本属于的情绪, 文本), ...]"""
        out: list[tuple[str, str]] = []
        emo = self._emo                       # 局部跟踪，避免和 _pend_emo 打架
        while self._buf:
            i = self._buf.find("[")

            if i == -1:                       # 没有 `[`，整段是文本
                out.append((emo, self._buf))
                self._buf = ""
                break

            if i > 0:                         # `[` 前面还有文本，先切出来
                out.append((emo, self._buf[:i]))
                self._buf = self._buf[i:]
                continue

            j = self._buf.find("]")           # buf 此刻以 "[" 开头
            if j == -1:                       # 还没闭合
                if len(self._buf) > TAG_MAX:  # 攒太久了 → 它不可能是标记
                    out.append((emo, "["))
                    self._buf = self._buf[1:]
                    continue
                break                         # hold 住，等下一片

            tag = self._buf[1:j]
            if self._is_tag(tag):             # 合法标记 → 只切情绪，不产出文本
                emo = tag
                self._buf = self._buf[j + 1:]
                continue

            out.append((emo, self._buf[:j + 1]))   # 不合法 → 当文本
            self._buf = self._buf[j + 1:]

        self._emo = emo                       # 同步回实例，下一次 feed 从这个情绪接着走
        return out

    def _is_tag(self, tag: str) -> bool:
        if not (1 <= len(tag) <= TAG_LEN):
            return False
        if "\n" in tag or "[" in tag or "]" in tag:
            return False
        if self.allowed is not None and tag not in self.allowed:
            return False
        return True

    # ── 内部 ②：攒句 + 到点吐 ────────────────────────
    def _into_pend(self, emo: str, text: str, out: list) -> None:
        if not text:
            return
        if self._pend and emo != self._pend_emo:
            # 情绪变了 → 旧句先吐（TTS 得换发音）
            out.append((self._pend_emo, self._pend))
            self._pend = ""
        self._pend_emo = emo
        self._pend += text

    def _drain(self, out: list, final: bool) -> None:
        if final:
            if self._pend:
                out.append((self._pend_emo, self._pend))
                self._pend = ""
            return

        while True:                           # ★ 反复切，一次 feed 里能出多句
            cut = -1
            for k, ch in enumerate(self._pend):
                if ch in SENT_END:
                    cut = k
            if cut >= 0:
                out.append((self._pend_emo, self._pend[:cut + 1]))
                self._pend = self._pend[cut + 1:]
                continue
            if len(self._pend) >= self.soft_limit:
                out.append((self._pend_emo, self._pend[:self.soft_limit]))
                self._pend = self._pend[self.soft_limit:]
                continue
            break

    # ── 调试用 ───────────────────────────────────────
    @property
    def emotion(self) -> str:
        return self._emo

    @property
    def pending(self) -> str:
        return self._pend


# ── 自测：python cerebrum/parser.py ──────────────────
if __name__ == "__main__":
    def collect(chunks: list[str], **kw):
        p = EmotionStreamParser(**kw)
        out = []
        for c in chunks:
            out += p.feed(c)
        out += p.flush()
        return out

    cases = [
        ("标记跨分片 + 按句输出",
         ["[开心", "]今天", "真好。"],
         [("开心", "今天真好。")]),

        ("情绪切换强制切句",
         ["[开心]好的", "[认真]我想想"],
         [("开心", "好的"), ("认真", "我想想")]),

        ("没标点 → flush 时吐出",
         ["[开心]没标点"],
         [("开心", "没标点")]),

        ("永不闭合 → 当普通文本",
         ["[开心", "没闭合"],
         [("", "[开心没闭合")]),

        ("白名单外的标签 → 当文本",
         ["[闲聊]嗯嗯"],
         [("", "[闲聊]嗯嗯")],
         {"allowed": {"开心"}}),

        ("超长伪标记 → 当文本",
         ["[" + "x" * 40],
         [("", "[" + "x" * 40)]),
    ]

    fails = 0
    for item in cases:
        name, chunks, want = item[0], item[1], item[2]
        kw = item[3] if len(item) > 3 else {}
        got = collect(chunks, **kw)
        ok = got == want
        fails += 0 if ok else 1
        print(f"[{'OK ' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"       期望 {want}")
            print(f"       实际 {got}")

    got = collect(["[开心]" + "字" * 100], soft_limit=20)
    ok = len(got) >= 3 and "".join(t for _, t in got) == "字" * 100
    fails += 0 if ok else 1
    print(f"[{'OK ' if ok else 'FAIL'}] 超长无标点 → 分段强吐（{len(got)} 段）")

    script = "[开心]欢迎来到直播间！[认真]今天这件商品，我给大家仔细讲讲。"
    chunks = [script[i:i + 2] for i in range(0, len(script), 2)]
    print(f"\n模拟 2 字/片 的真实流式输入（{len(chunks)} 片，共 {len(script)} 字）：")
    for emo, txt in collect(chunks):
        print(f"   ({emo!r}, {txt!r})")

    print("\n全部通过。" if fails == 0 else f"\n{fails} 项失败。")
