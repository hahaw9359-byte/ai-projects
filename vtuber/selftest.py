"""
小脑部件自测 —— 钉死三个最容易写错的点。

跑法：python selftest.py
"""
from __future__ import annotations

import asyncio

from core.types import DROP, PASS, SUSPECT, RawMessage
from cerebellum.audit import NullAuditor
from cerebellum.filters import default_pipeline
from cerebellum.window import BatchWindow


def mk(seq: int, uid: str = "u1", text: str = "hello", kind: str = "danmaku") -> RawMessage:
    return RawMessage(seq=seq, user_id=uid, user_name="测试用户", text=text, kind=kind)


# ── 1. 三态过滤 ──────────────────────────────────────
def test_filters() -> None:
    p = default_pipeline()

    assert p.run(mk(1, text="主播唱得真好")) == PASS
    assert p.run(mk(2, text="!!!!!!!!")) == DROP, "纯符号应被 SpamFilter 拦"
    assert p.run(mk(3, text="啊啊啊啊啊啊")) == DROP, "单字复读应被 SpamFilter 拦"
    assert p.run(mk(4, text="x" * 60)) == DROP, "超长应被 LengthFilter 拦"
    assert p.run(mk(5, text="加微信xxxx")) == SUSPECT, "敏感词应标 SUSPECT 而不是直接丢"

    # Dedup：同一用户 30 秒内重复内容 → 第二次丢
    assert p.run(mk(6, uid="u9", text="好听")) == PASS
    assert p.run(mk(7, uid="u9", text="好听")) == DROP

    # RateLimit：同一用户 10 秒内超过 20 条开始丢（第 21 条）
    for i in range(20):
        p.run(mk(100 + i, uid="u8", text=f"消息{i}"))
    assert p.run(mk(199, uid="u8", text="第21条")) == DROP

    print("  [1/3] 三态过滤 ............ OK")


# ── 2. 攒批窗口的两种触发 ────────────────────────────
async def test_window() -> None:
    out: asyncio.Queue = asyncio.Queue()
    w = BatchWindow(out, n=3, t=0.3)
    task = asyncio.create_task(w.run())
    try:
        # 触发方式 A：攒够 n 条
        for i in range(3):
            await w.feed(mk(i))
        batch = await asyncio.wait_for(out.get(), 1.0)
        assert len(batch) == 3, f"应攒够 3 条一起发，实际 {len(batch)}"

        # 触发方式 B：等满 t 秒
        await w.feed(mk(10))
        t0 = asyncio.get_running_loop().time()
        batch = await asyncio.wait_for(out.get(), 1.0)
        dt = asyncio.get_running_loop().time() - t0
        assert len(batch) == 1 and 0.25 < dt < 0.8, f"应在 ~0.3s 后发单条，实际 {dt:.2f}s"

        # 触发方式 C：礼物插队，立即成批
        await w.feed(mk(11, kind="gift"), urgent=True)
        batch = await asyncio.wait_for(out.get(), 0.1)
        assert len(batch) == 1 and batch[0].kind == "gift"
    finally:
        task.cancel()

    print("  [2/3] 攒批双触发 + 礼物插队 ... OK")


# ── 3. 审核：空实现全放行 ─────────────────────────────
async def test_audit() -> None:
    a = NullAuditor()
    msgs = [mk(1), mk(2), mk(3)]
    msgs[1].verdict = SUSPECT           # 只有中间那条疑似
    safe = await a.audit(msgs)
    assert safe == {1, 2, 3}, "空实现应全部放行"

    print("  [3/3] 审核空实现（疑似也放行）... OK")


async def _amain() -> None:
    await test_window()
    await test_audit()


if __name__ == "__main__":
    print("小脑部件自测：")
    test_filters()
    asyncio.run(_amain())
    print("\n全部通过。")
