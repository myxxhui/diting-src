"""去重修复验证：同 symbol 不得产生 window_overlap / capital_collision 假 flag。

[Ref: feasibility.py · step_15 §3.1]
"""
from __future__ import annotations

from datetime import date, timedelta

from apps.copilot.modules.roadmap.feasibility import evaluate_timeline_feasibility
from apps.copilot.modules.roadmap.calendar import trading_days_between


def _node(
    symbol: str,
    anchor: date,
    window_start: date,
    window_end: date,
    weight: float,
    seq: int = 1,
    node_id: int = 1,
) -> dict:
    return {
        "id": node_id,
        "symbol": symbol,
        "title": f"title_{symbol}_{node_id}",
        "anchor_date": anchor.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "target_weight_pct": weight,
        "sequence_no": seq,
        "build_lead_days": 15,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 测试 1：同一 symbol 两条节点、窗口重叠、各 50%
#         → 两者都不应出现 window_overlap 或 capital_collision
# ──────────────────────────────────────────────────────────────────────────────
def test_same_symbol_no_overlap_flag():
    """同 symbol（601138 × 2）产生窗口重叠时，不应打 window_overlap / capital_collision。"""
    today = date(2026, 7, 31)  # 远离 anchor，避免 build_window_tight 干扰
    anchor_a = date(2026, 9, 1)
    anchor_b = date(2026, 9, 10)
    # 窗口刻意重叠
    node_a = _node(
        symbol="601138",
        anchor=anchor_a,
        window_start=date(2026, 8, 20),
        window_end=date(2026, 9, 15),
        weight=50.0,
        seq=1,
        node_id=1,
    )
    node_b = _node(
        symbol="601138",
        anchor=anchor_b,
        window_start=date(2026, 9, 5),
        window_end=date(2026, 9, 25),
        weight=50.0,
        seq=2,
        node_id=2,
    )

    out = evaluate_timeline_feasibility([node_a, node_b], today=today)
    assert len(out) == 2, "返回节点数应与输入相同"

    for node_out in out:
        flags = node_out["feasibility_flags"]
        assert "window_overlap" not in flags, (
            f"同 symbol 不应出现 window_overlap，实际 flags={flags}"
        )
        assert "capital_collision" not in flags, (
            f"同 symbol 不应出现 capital_collision，实际 flags={flags}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 测试 2：不同 symbol 两条节点、窗口重叠、各 60%（合计 120% > 100）
#         → 两者都应出现 window_overlap 且 capital_collision
# ──────────────────────────────────────────────────────────────────────────────
def test_different_symbol_overlap_and_collision():
    """不同 symbol（601138 vs 300308）窗口重叠、合计 120%，应打 window_overlap + capital_collision。"""
    today = date(2026, 7, 31)
    anchor_a = date(2026, 9, 1)
    anchor_b = date(2026, 9, 10)
    node_a = _node(
        symbol="601138",
        anchor=anchor_a,
        window_start=date(2026, 8, 20),
        window_end=date(2026, 9, 15),
        weight=60.0,
        seq=1,
        node_id=1,
    )
    node_b = _node(
        symbol="300308",
        anchor=anchor_b,
        window_start=date(2026, 9, 5),
        window_end=date(2026, 9, 25),
        weight=60.0,
        seq=2,
        node_id=2,
    )

    out = evaluate_timeline_feasibility([node_a, node_b], today=today)
    assert len(out) == 2

    for node_out in out:
        flags = node_out["feasibility_flags"]
        assert "window_overlap" in flags, (
            f"不同 symbol 窗口重叠应出现 window_overlap，实际 flags={flags}"
        )
        assert "capital_collision" in flags, (
            f"合计 120% > 100 应出现 capital_collision，实际 flags={flags}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 测试 3：单节点距爆发点交易日不足 → 出现 build_window_tight（原逻辑未被破坏）
# ──────────────────────────────────────────────────────────────────────────────
def test_build_window_tight_preserved():
    """单节点 anchor 距 today 不足 build_lead_days 交易日，应出现 build_window_tight。"""
    today = date(2026, 5, 31)
    # anchor 只在 5 天后，交易日 ≪ build_lead_days=15
    anchor = today + timedelta(days=5)
    node = _node(
        symbol="000001",
        anchor=anchor,
        window_start=today,
        window_end=anchor + timedelta(days=10),
        weight=30.0,
        seq=1,
        node_id=1,
    )

    td = trading_days_between(today, anchor)
    out = evaluate_timeline_feasibility([node], build_lead_days=15, today=today)
    assert len(out) == 1

    flags = out[0]["feasibility_flags"]
    if td < 15:
        assert "build_window_tight" in flags, (
            f"距爆发点仅 {td} 交易日，应出现 build_window_tight，实际 flags={flags}"
        )
    # td >= 15 时（极端情况：假期堆叠）跳过该断言，避免日历边界误报
