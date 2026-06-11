"""fii_gb200_milestone JL3 单测 · DeepSea 纯语义状态机 v1。

[Ref: 28_ §2.2 fii_gb200_milestone]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_gb200_milestone.indicator_node import (
    build_fii_gb200_milestone_node,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_contract import build_t1_contract
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t0_cninfo import _score_announcement
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_semantic import (
    build_shadow_validation,
    infer_gb200_milestone_semantic,
    needs_pro_review,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_solver import solve_gb200_milestone
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_solver_lifecycle import (
    check_temporal_paradox,
    detect_lifecycle_stage,
    detect_state_transition,
    map_product_segment,
)
from apps.copilot.modules.executing.probe_keys import L3_KEYS
from apps.copilot.services.deepsea.config_loader import get_l3_probe_config


SAMPLE_SHADOW = {
    "raw_materials_inventory": {
        "ok": True,
        "surge_signal": True,
        "qoq_pct": 42.1,
        "interpretation_zh": "原材料环比+42.1%",
        "source": "unit_test",
    },
}

SAMPLE_T0 = {
    "symbol": "601138",
    "doc_id": "doc_601138_cninfo_20260611_qa_transcript",
    "event_raw_text": (
        "郑弘孟：墨西哥厂区的GB200 NVL72产线已顺利通过北美核心客户的最终系统级验证。"
        "郑弘孟：关于大家关心的AI机柜交付节奏，目前该产线本季度已正式进入全面规模化批量交付阶段。"
        "财务总监：得益于测试环节的数字化，新品首批直通率表现优异，极大地避免了前期的物料损耗。"
    ),
    "announcement_title": "关于新一代AI智算机柜交付进展的自愿性信息披露",
    "official_announcement_text": (
        "本季度GB200 NVL72产线已顺利开启规模交付。"
        "公司最新一代高密度智算机柜及液冷整体解决方案已于本月顺利进入规模交付阶段。"
    ),
    "published_date": "2026-06-10",
    "investor_relations_qa": "",
    "prior_lifecycle_stage": "PVT",
    "prior_signal_snapshot": {"signal_status": "PVT"},
    "upstream_bottleneck_date": "2024-10-01",
    "shadow_proxies": SAMPLE_SHADOW,
}


def test_l3_registry_includes_gb200_milestone():
    assert L3_KEYS == ("fii_twse_cloud", "fii_odm_direct_ratio", "fii_gb200_milestone")
    assert "fii_gb200_milestone" in L3_KEYS


def test_probe_registry_deepsea_routing():
    cfg = get_l3_probe_config("601138", "fii_gb200_milestone")
    assert cfg["t1_pipeline"] == "deepsea_semantic"
    assert cfg["cache_group"] == "fii-cninfo-dynamic"
    assert cfg["update_trigger"] == "event_driven"
    assert cfg["stale_days"] == 90
    assert cfg["model_tier_escalation"] == "pro_on_low_confidence"
    assert "PVT" in cfg["state_machine_nodes"]
    assert "fii_ai_margin_tone" in (cfg.get("cohort_peers") or [])


def test_semantic_state_machine_pvt_to_mp():
    text = SAMPLE_T0["event_raw_text"]
    assert map_product_segment(text) == "GB200 NVL72/36 整机柜"
    stage_key, _, terms = detect_lifecycle_stage(text)
    assert stage_key == "MP"
    assert "规模交付" in terms or "批量交付" in terms or "量产" in terms
    assert detect_state_transition("PVT", "MP") == "PVT→MP"

    sem = infer_gb200_milestone_semantic(SAMPLE_T0)
    assert sem["signal_status"] == "MP"
    assert len(sem["evidence_quotes"]) >= 1
    assert sem["momentum_delta"] == "accelerating"
    assert sem["shadow_validation"]["passed"] is True
    assert sem["llm_tag"].startswith("rule_fallback") or str(sem["llm_tag"]).startswith("deepseek")
    assert sem.get("routing", {}).get("stale_days") == 90


def test_deepsea_contract_structure():
    contract = build_t1_contract(SAMPLE_T0)
    assert contract["contract_version"] == "fii_gb200_milestone_deepsea_v1"
    assert contract["signal_status"] == "MP"
    assert contract["cache_group"] == "fii-cninfo-dynamic"
    assert contract["value"] is None
    assert contract["calculation_logic"] is None
    assert isinstance(contract["evidence_quotes"], list)
    assert contract["momentum_delta"] == "accelerating"
    assert contract["shadow_validation"]["cross_refs"] == ["fii_raw_inventory", "fii_copper_shfe"]


def test_solve_mp_with_shadow():
    solved = solve_gb200_milestone(SAMPLE_T0)
    assert solved["solver"]["method"] == "deepsea_semantic_v1"
    assert solved["mp_starting_gun"] is True
    assert solved["confirmed_breakthrough"] is True
    assert solved["missing_data_flags"]["exact_revenue_cny"] == "RESTRICTED_NDA_DATA"


def test_temporal_paradox_blocks_mp():
    t0 = {**SAMPLE_T0, "published_date": "2024-06-01"}
    sem = infer_gb200_milestone_semantic(t0)
    assert sem["temporal_check"]["paradox"] is True
    assert sem["signal_status"] == "UNKNOWN"


def test_shadow_validation_raw_inventory():
    sv = build_shadow_validation(SAMPLE_T0, signal_status="MP")
    assert sv["passed"] is True
    assert "fii_raw_inventory" in sv["cross_refs"]


def test_indicator_node_deepsea_fields():
    node = build_fii_gb200_milestone_node(SAMPLE_T0, source="unit_test")
    assert "MP" in str(node["value"])
    assert "accelerating" in node["calculation_logic"] or "MP" in node["value_detail"]
    t1 = node.get("t1_json") or {}
    assert t1.get("contract_version") == "fii_gb200_milestone_deepsea_v1"
    assert t1.get("cache_group") == "fii-cninfo-dynamic"


def test_cninfo_buyback_title_deprioritized():
    buyback = _score_announcement("关于股份回购进展公告", "")
    milestone = _score_announcement("关于新一代AI智算机柜GB200交付进展的自愿性信息披露", "规模交付")
    assert milestone > buyback


def test_needs_pro_review_mp_low_confidence():
    assert needs_pro_review({"signal_status": "MP", "confidence": "medium", "evidence_quotes": ["a", "b"]})
    assert not needs_pro_review({"signal_status": "MP", "confidence": "high", "evidence_quotes": ["a", "b", "c"]})


def test_paradox_helper():
    from datetime import date

    ok = check_temporal_paradox(date(2026, 6, 10), "2024-10-01", "MP")
    assert ok["paradox"] is False
    bad = check_temporal_paradox(date(2024, 6, 1), "2024-10-01", "MP")
    assert bad["paradox"] is True
