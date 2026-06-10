"""fii_twse_cloud JL3 单测。

[Ref: 28_ §2.2 fii_twse_cloud]
"""
from __future__ import annotations

import pytest

from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_contract import build_t1_contract
from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_solver import (
    extract_segment_narratives,
    parse_mom_ranking,
    solve_cloud_revenue_range,
)
from apps.copilot.modules.executing.l3.fii_twse_cloud.indicator_node import build_fii_twse_cloud_node
from apps.copilot.modules.executing.l3_probe_registry import L3_PROBE_REGISTRY, L3_KEYS
from apps.copilot.modules.executing.probe_keys import L3_KEYS as PK_L3


SAMPLE_T0 = {
    "report_year": 2026,
    "report_month": 4,
    "total_revenue_ntd": 832_097_956_000,
    "prev_month_revenue_ntd": 803_737_716_000,
    "total_mom_pct": 3.53,
    "total_yoy_pct": 29.74,
    "pr_raw_text": (
        "云端网路产品方面，预期云端网路产品在季对季、年对年都将有强劲成长的表现；"
        "消费智能产品方面，今年整体需求优于去年，因此预期将会达到显著成长。"
        "云端网路产品 MoM 增速为四大板块第一。"
    ),
    "segment_baseline_weights_last_q": {
        "cloud": 22.0,
        "consumer": 47.0,
        "computing": 8.0,
        "components": 23.0,
    },
    "seasonality_factor_consumer": {
        "consumer_mom_pct_range": [-18.0, 35.0],
        "by_calendar_month": {"4": [0.0, 20.0]},
    },
}


def test_l3_keys_and_registry_aligned():
    assert PK_L3 == ("fii_twse_cloud",)
    assert set(L3_PROBE_REGISTRY) == set(L3_KEYS)


def test_solver_produces_cloud_bounds():
    solved = solve_cloud_revenue_range(SAMPLE_T0)
    bounds = solved["cloud_revenue_ntd"]
    assert bounds["lo"] > 0
    assert bounds["hi"] >= bounds["lo"]
    assert solved["pr_evidence"]["cloud_mom_rank"] == 1
    assert "强劲" in str(solved["pr_evidence"].get("segment_fuzzy_terms", {}).get("cloud", []))


def test_parse_mom_ranking_from_table():
    text = "MoM  元件及其他 > 雲端網路 > 電腦終端 > 消費智能"
    ranking = parse_mom_ranking(text)
    assert ranking == ["components", "cloud", "computing", "consumer"]


def test_segment_narratives_extracted():
    snippets = extract_segment_narratives(
        SAMPLE_T0["pr_raw_text"],
        year=2026,
        month=4,
    )
    assert "cloud" in snippets
    assert "云端" in snippets["cloud"]
    assert "MoM" not in snippets["cloud"] or ">" not in snippets["cloud"]


def test_t1_contract_structure():
    contract = build_t1_contract(SAMPLE_T0)
    assert contract["indicator_id"] == "fii_twse_cloud"
    assert contract["period"] == "2026-04"
    assert "cloud_revenue_ntd" in contract
    assert "macro" in contract
    assert "pr_evidence" in contract
    assert "anti_substitution_matrix" not in contract
    assert "missing_data_flags" not in contract
    assert "云端" in contract["fact_statement"]


def test_indicator_node_has_t1_json():
    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    assert node["t1_json"]["indicator_id"] == "fii_twse_cloud"
    assert node.get("value_detail") or node.get("value")
    assert "card_strategy" in node["raw_metrics"]


def test_render_fii_twse_cloud_card():
    from apps.copilot.modules.executing.executing_render import render_fii_twse_cloud_card

    node = build_fii_twse_cloud_node(SAMPLE_T0, source="test")
    html = render_fii_twse_cloud_card(node)
    assert "fii_twse_cloud" in html
    assert "T1 白盒 JSON" in html
    assert "母公司云端营收" in html
