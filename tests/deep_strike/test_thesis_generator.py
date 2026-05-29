"""D2 step_05 — ThesisCard schema + Generator + completeness 测试。

[Ref: 03_/02_维度二/step_05 §3.5.1~3]
"""
from __future__ import annotations

import pytest

from apps.deep_strike.engines.thesis.schema import EvidenceItem, ThesisCardSchema, ValuationAnchor
from apps.deep_strike.engines.thesis.completeness import batch_check, check_one


# ──────────────────────────────────────────────────────────────────────────────
# fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _valid_card(**overrides) -> ThesisCardSchema:
    defaults = dict(
        symbol="002837",
        name="英维克",
        playbook_id="profit_capture",
        confidence=0.72,
        thesis_summary="【002837·英维克】profit_capture 剧本命中（置信度 72%）。核心逻辑：数据中心温控设备订单同比增长68%。综合基本面证据链与行业对比，建议买入，需跟踪后续财报与行业政策动态。",
        evidence_chain=[
            EvidenceItem(evidence_type="financial", content="毛利率 36.2%，同比提升 1.1pp，行业领先。"),
            EvidenceItem(evidence_type="announcement", content="新签数据中心温控订单同比增长 68%，超市场预期。"),
            EvidenceItem(evidence_type="industry", content="液冷市场 CAGR 36%，公司市占率 29%，行业地位稳固。"),
        ],
        risks=[
            "监管政策收紧风险：行业政策存在不确定性，可能对公司主营业务产生负面影响。",
            "市场系统性风险：宏观经济下行或市场整体调整可能导致股价短期承压。",
            "业绩低于预期风险：实际财报数据或营收增速若低于市场预期，可能引发估值回调。",
        ],
        valuation_anchor=ValuationAnchor(method="PE", target_price=52.8, basis="当前 PE × 115%"),
        action="buy",
    )
    defaults.update(overrides)
    return ThesisCardSchema(**defaults)


# ──────────────────────────────────────────────────────────────────────────────
# Schema 校验
# ──────────────────────────────────────────────────────────────────────────────

class TestThesisCardSchema:
    def test_valid_card_pass(self):
        card = _valid_card()
        assert card.symbol == "002837"
        assert card.action == "buy"
        assert card.status == "proposed"

    def test_summary_min_50_chars(self):
        with pytest.raises(Exception):
            _valid_card(thesis_summary="短摘要")

    def test_evidence_chain_min_3(self):
        with pytest.raises(Exception):
            _valid_card(evidence_chain=[
                EvidenceItem(evidence_type="financial", content="内容A"),
                EvidenceItem(evidence_type="financial", content="内容B"),
            ])

    def test_risks_not_empty(self):
        with pytest.raises(Exception):
            _valid_card(risks=[])

    def test_risk_item_min_20_chars(self):
        with pytest.raises(Exception):
            _valid_card(risks=["太短"])

    def test_action_enum(self):
        with pytest.raises(Exception):
            _valid_card(action="sell")  # type: ignore

    def test_action_watch_allowed(self):
        card = _valid_card(action="watch")
        assert card.action == "watch"

    def test_timer_signal_optional(self):
        card = _valid_card()
        assert card.timer_signal is None


# ──────────────────────────────────────────────────────────────────────────────
# completeness
# ──────────────────────────────────────────────────────────────────────────────

class TestCompleteness:
    def test_valid_card_passes(self):
        card = _valid_card()
        errs = check_one(card)
        assert errs == []

    def test_short_summary_fails(self):
        card = _valid_card()
        card.thesis_summary = "很短"  # 绕过 Pydantic
        errs = check_one(card)
        assert any("thesis_summary" in e for e in errs)

    def test_insufficient_evidence_fails(self):
        card = _valid_card()
        card.evidence_chain = [
            EvidenceItem(evidence_type="financial", content="只有两条证据"),
            EvidenceItem(evidence_type="financial", content="第二条证据"),
        ]
        errs = check_one(card)
        assert any("evidence_chain" in e for e in errs)

    def test_batch_check_all_pass(self):
        cards = [_valid_card() for _ in range(3)]
        result = batch_check(cards)
        assert result["all_pass"] is True
        assert result["total"] == 3

    def test_batch_check_one_fail(self):
        good = _valid_card()
        bad = _valid_card()
        bad.evidence_chain = [EvidenceItem(evidence_type="financial", content="只有一条证据")]
        result = batch_check([good, bad])
        assert result["all_pass"] is False
        assert any(not r["pass"] for r in result["results"])


# ──────────────────────────────────────────────────────────────────────────────
# no-mock policy guard
# ──────────────────────────────────────────────────────────────────────────────

class TestNoMockGuard:
    def test_stub_mode_env_raises(self, monkeypatch):
        """THESIS_GENERATOR_MODE=stub 禁止在生产路径启动。"""
        import importlib
        import apps.deep_strike.engines.thesis.generator as gen_module

        monkeypatch.setenv("THESIS_GENERATOR_MODE", "stub")
        with pytest.raises(RuntimeError, match="stub"):
            importlib.reload(gen_module)

        # 清理 env，恢复
        monkeypatch.delenv("THESIS_GENERATOR_MODE", raising=False)
        importlib.reload(gen_module)
