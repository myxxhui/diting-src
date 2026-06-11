"""JL3 统一卡片模板单测。

[Ref: jl3_card_render.py · fii_twse_cloud 样板]
"""
from __future__ import annotations

from apps.copilot.modules.executing.jl3_card_render import (
    normalize_jl3_card_strategy,
    render_jl3_probe_card,
)
from apps.copilot.modules.executing.l3.fii_twse_cloud.indicator_node import build_fii_twse_cloud_node

SAMPLE_T0 = {
    "report_year": 2026,
    "report_month": 4,
    "total_revenue_ntd": 832_097_956_000,
    "prev_month_revenue_ntd": 803_737_716_000,
    "total_mom_pct": 3.53,
    "total_yoy_pct": 29.74,
    "pr_raw_text": "MoM  元件及其他 > 雲端網路 > 電腦終端 > 消費智能",
    "segment_baseline_weights_last_q": {"cloud": 22.0, "consumer": 47.0},
    "revenue_history": [
        {"year": 2026, "month": 3, "total_revenue_ntd": 803_000_000_000, "total_mom_pct": 34.9},
        {"year": 2026, "month": 4, "total_revenue_ntd": 832_097_956_000, "total_mom_pct": 3.53},
    ],
}


def test_normalize_legacy_fii_card_strategy():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    cs = node["raw_metrics"]["card_strategy"]
    norm = normalize_jl3_card_strategy(cs)
    assert norm.get("signal")
    assert norm["signal"]["status"] in ("green", "yellow", "red")
    assert norm.get("panel_title")


def test_render_jl3_probe_card_uses_template():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    html = render_jl3_probe_card("fii_twse_cloud", node)
    assert "云端网路 · 近" in html
    assert "合并总营收" in html
    assert "观察区" in html or "进攻" in html or "防守" in html
    assert "目标三发令规则" in html
    assert "进攻：连续两月" not in html
    assert "来源 ·" not in html
    assert "R_total=" not in html
    assert "T1 白盒 JSON" in html
    assert 'data-probe-key="fii_twse_cloud"' in html
