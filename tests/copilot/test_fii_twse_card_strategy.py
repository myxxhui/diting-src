"""fii_twse_cloud 卡片战略层单测。

[Ref: 28_ §2.2 fii_twse_cloud]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import (
    build_card_strategy,
    compute_trend_signal,
)
from apps.copilot.modules.executing.l3.fii_twse_cloud.indicator_node import build_fii_twse_cloud_node
from apps.copilot.modules.executing.executing_render import render_fii_twse_cloud_card

SAMPLE_T0 = {
    "report_year": 2026,
    "report_month": 4,
    "total_revenue_ntd": 832_097_956_000,
    "prev_month_revenue_ntd": 803_737_716_000,
    "total_mom_pct": 3.53,
    "total_yoy_pct": 29.74,
    "pr_raw_text": (
        "MoM  元件及其他 > 雲端網路 > 電腦終端 > 消費智能\n"
        "说明如下:\n"
        "(2) 「云端网路产品类别」: 年对年强劲成长。"
    ),
    "segment_baseline_weights_last_q": {
        "cloud": 22.0,
        "consumer": 47.0,
        "computing": 8.0,
        "components": 23.0,
    },
    "seasonality_factor_consumer": {"consumer_mom_pct_range": [-18.0, 35.0]},
    "revenue_history": [
        {"year": 2025, "month": 11, "total_revenue_ntd": 700_000_000_000, "total_mom_pct": 2.0},
        {"year": 2025, "month": 12, "total_revenue_ntd": 720_000_000_000, "total_mom_pct": 2.8},
        {"year": 2026, "month": 1, "total_revenue_ntd": 730_000_000_000, "total_mom_pct": 1.4},
        {"year": 2026, "month": 2, "total_revenue_ntd": 595_000_000_000, "total_mom_pct": -18.5},
        {"year": 2026, "month": 3, "total_revenue_ntd": 803_000_000_000, "total_mom_pct": 34.9},
        {"year": 2026, "month": 4, "total_revenue_ntd": 832_097_956_000, "total_mom_pct": 3.53},
    ],
}


def test_card_strategy_has_three_goals():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    cs = node["raw_metrics"]["card_strategy"]
    assert "goal1_time_lag" in cs
    assert "goal1b_cloud_vs_total" in cs
    assert "goal2_noise_isolation" in cs
    assert "goal3_trend_trigger" in cs
    assert len(cs["goal1_time_lag"]["monthly_series"]) >= 4
    cmp_rows = cs["goal1b_cloud_vs_total"]["comparison_series"]
    assert len(cmp_rows) >= 4
    assert "total_mom_pct" in cmp_rows[-1]
    assert "cloud_mom_pct" in cmp_rows[-1]
    assert "sync_label" in cmp_rows[-1]


def test_render_cloud_vs_total_table():
    from apps.copilot.modules.executing.jl3_card_render import render_fii_cloud_vs_total_table

    html = render_fii_cloud_vs_total_table(
        [
            {
                "period": "2026-04",
                "total_billion_ntd": 832.1,
                "total_mom_pct": 3.5,
                "cloud_lo_billion_ntd": 170.2,
                "cloud_mom_pct": 5.1,
                "cloud_share_pct": 20.5,
                "sync_label": "云端更强",
            }
        ]
    )
    assert "云端MoM" in html or "月环比" in html
    assert "云端网路" in html


def test_honhai_ownership_on_card_face():
    from apps.copilot.modules.executing.jl3_card_render import render_fii_ownership_card_face
    from apps.copilot.modules.executing.l3.fii_twse_cloud.card_strategy import build_honhai_ownership_summary

    html = render_fii_ownership_card_face(build_honhai_ownership_summary())
    assert "鸿海系持股" in html
    assert "85.72" in html
    assert "详细了解股权与分红" in html
    assert "现金分红" in html


def test_card_strategy_includes_ownership():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    own = node["raw_metrics"]["card_strategy"].get("honhai_ownership") or {}
    assert own.get("concert_party_pct") == 85.72


def test_trend_signal_yellow_when_rank_second():
    sig = compute_trend_signal(
        cloud_lo_mom_series=[{"mom_pct": 5.0}, {"mom_pct": 8.0}],
        cloud_mom_rank=2,
        cloud_terms=["强劲成长"],
        consumer_terms=[],
    )
    assert sig["status"] == "yellow"


def test_render_strategy_panel():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    html = render_fii_twse_cloud_card(node)
    assert "云端网路 · 近" in html
    assert "合并总营收" in html
    assert "鸿海系持股" in html
    assert "详细了解股权与分红" in html
    assert "来源 ·" not in html
    assert "T1 白盒 JSON" in html
