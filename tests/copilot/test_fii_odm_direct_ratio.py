"""fii_odm_direct_ratio JL3 单测。

[Ref: 28_ §2.2 fii_odm_direct_ratio]
"""
from __future__ import annotations

from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.indicator_node import (
    build_fii_odm_direct_ratio_node,
)
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t0_cninfo import (
    _qa_candidate_score,
)
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_contract import build_t1_contract
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_qa_analyzer import score_qa_document
from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_solver import solve_odm_direct_ratio
from apps.copilot.modules.executing.jl3_card_render import render_jl3_probe_card


SAMPLE_SEMANTIC_T0 = {
    "report_period": "2026-Q1",
    "report_title": "2026年第一季度报告",
    "total_cloud_revenue_cny": 167_595_118_174,
    "total_cloud_yoy_pct": 100.0,
    "is_breakdown_published": False,
    "qa_raw_transcript": "IR 实录占位",
    "semantic_evidence_layer": {
        "llm_tag": "unit_test",
        "evidence_quotes": [
            {
                "dimension": "cloud_revenue_growth",
                "source_doc": "quarterly_report",
                "quote_zh": "云计算业务方面，板块营业收入同比增长1倍。",
                "strength": "strong",
            },
            {
                "dimension": "csp_odm_deepening",
                "source_doc": "ir_activity_record",
                "quote_zh": "公司与多家主要客户在高端AI服务器ODM领域的制造优势与客户粘性持续巩固。",
                "strength": "strong",
            },
        ],
        "semantic_assessment": {
            "odm_csp_growth_signal": "strong_up",
            "meets_investment_thesis_odm_direct": True,
            "thesis_rationale_zh": "云业务翻倍且 ODM 粘性巩固",
        },
        "inferred_odm_share_of_cloud_pct": {"confidence": "none", "lo": None, "hi": None},
    },
}


def test_semantic_evidence_only_shows_signal_not_fake_pct():
    solved = solve_odm_direct_ratio(SAMPLE_SEMANTIC_T0)
    assert solved["solver"]["method"] == "semantic_evidence_only"
    assert solved["odm_ratio_pct"]["mid"] is None
    assert solved["semantic_signal"]["label"] == "CSP/ODM·强↑"
    node = build_fii_odm_direct_ratio_node(SAMPLE_SEMANTIC_T0, source="unit_test")
    assert node["value"] == "CSP/ODM·强↑"
    assert "1675" in node["value_detail"] or "1676" in node["value_detail"]


def test_t1_contract_has_semantic_layer():
    contract = build_t1_contract(SAMPLE_SEMANTIC_T0)
    assert contract["llm_tag"] == "unit_test"
    assert contract["semantic_evidence_layer"]
    assert "语义证据层" in contract["fact_statement"]


def test_indicator_node_and_card_render():
    node = build_fii_odm_direct_ratio_node(SAMPLE_SEMANTIC_T0, source="unit_test")
    assert node["indicator_name"]
    cs = node["raw_metrics"]["card_strategy"]
    assert cs.get("signal", {}).get("status") == "green"
    html = render_jl3_probe_card("fii_odm_direct_ratio", node)
    assert "云计算业务" in html or "云营收" in html or "语义" in html


def test_published_breakdown_short_circuit():
    t0 = {
        **SAMPLE_SEMANTIC_T0,
        "is_breakdown_published": True,
        "odm_direct_ratio_published_pct": 62.5,
    }
    solved = solve_odm_direct_ratio(t0)
    assert solved["odm_ratio_pct"]["mid"] == 62.5
    assert solved["solver"]["method"] == "published_breakdown"


REAL_IR_2026_Q1_EXCERPT = """
投资者关系活动记录表 编号：2026-003
Q1：AI业务是否具备对冲能力？
回复：2026年第一季度，云计算业务同比增长1倍。
Q4：竞争格局？
回复：公司与多家主要客户在高端AI服务器ODM领域的制造优势与客户粘性持续巩固。
"""


def test_qa_doc_scoring_prefers_ir_record_over_notice():
    notice_title = "关于召开2026年第一季度业绩说明会的公告"
    notice_text = "会议召开时间2026年5月20日"
    record_title = "投资者关系活动记录表"
    record_text = REAL_IR_2026_Q1_EXCERPT
    assert _qa_candidate_score(record_title, record_text) > _qa_candidate_score(
        notice_title, notice_text
    )
    assert score_qa_document(record_title, record_text) > score_qa_document(
        notice_title, notice_text
    )
