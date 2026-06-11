"""DeepSea Dispatcher 批推单测。

[Ref: 29_ §5.4 · 28_ §2.11.5 fii-cninfo-dynamic]
"""
from __future__ import annotations

import asyncio

import pytest

from apps.copilot.modules.executing.l3.fii_gb200_milestone.card_strategy import (
    build_card_strategy,
    render_gb200_milestone_body,
)
from apps.copilot.modules.executing.l3.fii_gb200_milestone.indicator_node import (
    build_fii_gb200_milestone_node,
)
from apps.copilot.services.deepsea.context_cache import clear_context_cache_for_tests, warm_context_cache
from apps.copilot.services.deepsea.dispatcher import dispatch_cohort_inference


SAMPLE_T0 = {
    "symbol": "601138",
    "doc_id": "doc_601138_cninfo_20260611_qa_transcript",
    "event_raw_text": (
        "郑弘孟：墨西哥厂区的GB200 NVL72产线已顺利通过北美核心客户的最终系统级验证。"
        "郑弘孟：关于大家关心的AI机柜交付节奏，目前该产线本季度已正式进入全面规模化批量交付阶段。"
        "财务总监：得益于测试环节的数字化，新品首批直通率表现优异，极大地避免了前期的物料损耗。"
    ),
    "official_announcement_text": "本季度GB200 NVL72产线已顺利开启规模交付。",
    "published_date": "2026-06-10",
    "prior_lifecycle_stage": "PVT",
    "prior_signal_snapshot": {"signal_status": "PVT"},
    "shadow_proxies": {"raw_materials_inventory": {"qoq_pct": 42.1}},
}


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_context_cache_for_tests()
    yield
    clear_context_cache_for_tests()


def test_warm_context_cache_hit():
    ref1 = warm_context_cache(
        cache_group="fii-cninfo-dynamic",
        doc_id="doc_test",
        text="全文缓存测试" * 10,
    )
    ref2 = warm_context_cache(
        cache_group="fii-cninfo-dynamic",
        doc_id="doc_test",
        text="全文缓存测试" * 10,
    )
    assert ref1.cache_key == ref2.cache_key
    assert ref1.char_count == ref2.char_count


def test_dispatch_cohort_gb200_ok():
    batch = asyncio.run(
        dispatch_cohort_inference(
            symbol="601138",
            cache_group="fii-cninfo-dynamic",
            t0_payload=SAMPLE_T0,
            force_probes=["fii_gb200_milestone", "fii_liquid_attach"],
        )
    )
    gb200 = next(b for b in batch if b.get("probe_key") == "fii_gb200_milestone")
    assert gb200["status"] == "ok"
    assert gb200["contract"]["signal_status"] == "MP"
    assert len(gb200["contract"]["evidence_quotes"]) >= 1
    assert gb200["cache_group"] == "fii-cninfo-dynamic"

    pending = next(b for b in batch if b.get("probe_key") == "fii_liquid_attach")
    assert pending["status"] == "pending"


def test_card_strategy_evidence_quotes():
    node = build_fii_gb200_milestone_node(SAMPLE_T0, source="unit_test")
    contract = node["t1_json"]
    cs = build_card_strategy(SAMPLE_T0, contract)
    assert cs["signal_status"] == "MP"
    assert cs["momentum_delta"] == "accelerating"
    assert len(cs["evidence_quotes"]) >= 1
    assert cs["shadow_validation"].get("passed") is True

    html = render_gb200_milestone_body(node)
    assert "证据原句" in html
    assert "侧翼验真" in html
    assert "批量交付" in html or "规模交付" in html


def test_dispatch_doc_inference_entry():
    from apps.copilot.services.deepsea.dispatcher import dispatch_doc_inference

    batch = asyncio.run(
        dispatch_doc_inference(
            "doc_601138_cninfo_20260611_qa_transcript",
            symbol="601138",
            t0_payload=SAMPLE_T0,
            cache_group="fii-cninfo-dynamic",
            force_probes=["fii_gb200_milestone"],
        )
    )
    assert batch[0]["status"] == "ok"
