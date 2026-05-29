"""D3 step_09 · market_phase 规则分类器单测."""
from __future__ import annotations

import pytest

from apps.state_watch.market_phase.rule_classifier_v1 import classify
from apps.state_watch.market_phase.schemas import MarketPhase, PhaseSignals


def _sig(**kwargs) -> PhaseSignals:
    base = dict(
        symbol="002837",
        name="英维克",
        pct_chg_1d=0.01,
        pct_chg_3d=0.02,
        pct_chg_5d=0.03,
        pct_chg_30d=0.10,
        pct_chg_60d=0.15,
        volume_ratio_5d=1.2,
        price_below_ma10=False,
        media_news_count_7d=5,
        phys_probe_alerts_active=0,
        has_q_report_released=False,
        has_pre_announce_released=False,
        has_major_contract=False,
        no_announcement_positive=True,
        insufficient_price=False,
        tags=[],
    )
    base.update(kwargs)
    return PhaseSignals(**base)


def test_concept_default_low_momentum():
    r = classify(_sig())
    assert r.market_phase == MarketPhase.CONCEPT
    assert r.confidence >= 0.45


def test_expectation_momentum_30d():
    r = classify(
        _sig(pct_chg_30d=0.35, volume_ratio_5d=1.8, no_announcement_positive=True)
    )
    assert r.market_phase == MarketPhase.EXPECTATION
    assert "expectation_momentum_30d" in r.reasoning_tags


def test_expectation_phys_probe():
    r = classify(
        _sig(
            phys_probe_alerts_active=2,
            volume_ratio_5d=2.0,
            no_announcement_positive=True,
        )
    )
    assert r.market_phase == MarketPhase.EXPECTATION


def test_realization_q_report():
    r = classify(_sig(has_q_report_released=True))
    assert r.market_phase == MarketPhase.REALIZATION


def test_realization_pre_announce():
    r = classify(_sig(has_pre_announce_released=True))
    assert r.market_phase == MarketPhase.REALIZATION


def test_realization_contract():
    r = classify(_sig(has_major_contract=True))
    assert r.market_phase == MarketPhase.REALIZATION


def test_exhaustion_vol_price_divergence():
    r = classify(
        _sig(
            pct_chg_60d=0.90,
            volume_ratio_5d=3.0,
            pct_chg_5d=-0.02,
        )
    )
    assert r.market_phase == MarketPhase.EXHAUSTION
    assert "exhaustion_vol_price_divergence" in r.reasoning_tags


def test_exhaustion_media_climax():
    r = classify(
        _sig(
            media_news_count_7d=40,
            pct_chg_3d=-0.03,
            price_below_ma10=True,
        )
    )
    assert r.market_phase == MarketPhase.EXHAUSTION


def test_exhaustion_priority_over_realization():
    r = classify(
        _sig(
            has_q_report_released=True,
            pct_chg_60d=0.90,
            volume_ratio_5d=3.0,
            pct_chg_5d=-0.01,
        )
    )
    assert r.market_phase == MarketPhase.EXHAUSTION


def test_insufficient_price_degraded():
    r = classify(_sig(insufficient_price=True, tags=["insufficient_input"]))
    assert r.market_phase == MarketPhase.CONCEPT
    assert r.confidence <= 0.5


@pytest.mark.parametrize(
    "phase,tag_fn",
    [
        (MarketPhase.CONCEPT, lambda: _sig()),
        (MarketPhase.EXPECTATION, lambda: _sig(pct_chg_30d=0.4, volume_ratio_5d=2.0)),
        (MarketPhase.REALIZATION, lambda: _sig(has_major_contract=True)),
        (MarketPhase.EXHAUSTION, lambda: _sig(pct_chg_60d=0.85, volume_ratio_5d=2.8, pct_chg_5d=-0.01)),
    ],
)
def test_four_phases_reachable(phase, tag_fn):
    assert classify(tag_fn()).market_phase == phase
