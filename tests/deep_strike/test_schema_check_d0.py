"""D0 schema_check 单测。"""
from __future__ import annotations

import asyncio

from apps.copilot.modules.recommendation.schema import ThesisProposedPayload
from apps.deep_strike.engines.thesis.d0_payload import card_to_d0_payload, d0_field_diff
from apps.deep_strike.engines.thesis.schema import EvidenceItem, ThesisCardSchema, ValuationAnchor


def _card() -> ThesisCardSchema:
    return ThesisCardSchema(
        symbol="300308",
        name="中际旭创",
        playbook_id="profit_capture",
        confidence=0.8,
        thesis_summary="【300308·中际旭创】profit_capture 剧本命中。核心逻辑：光模块景气回升，龙头份额提升，需跟踪财报。",
        evidence_chain=[
            EvidenceItem(evidence_type="financial", content="毛利率连续三季改善，经营现金流显著好转。"),
            EvidenceItem(evidence_type="announcement", content="公司公告海外大客户订单落地，交付节奏明确。"),
            EvidenceItem(evidence_type="industry", content="光模块行业景气度回升，龙头份额提升。"),
        ],
        risks=["监管政策收紧风险：行业政策存在不确定性，可能影响估值。"],
        valuation_anchor=ValuationAnchor(method="watch_only", basis="仅观察，暂不设目标价。"),
        action="watch",
    )


def test_d0_field_diff_zero():
    payload = card_to_d0_payload(_card())
    assert d0_field_diff(payload) == []


def test_d0_payload_validates():
    payload = card_to_d0_payload(_card())
    parsed = ThesisProposedPayload.model_validate(payload)
    assert parsed.symbol == "300308"
    assert len(parsed.evidence_chain) >= 3
