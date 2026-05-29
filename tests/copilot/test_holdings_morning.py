"""W1+W2 合并早报."""
from __future__ import annotations

from datetime import date

from apps.copilot.services.reports.holdings_morning import (
    health_score_to_push_level,
    _color_distribution,
    _phase_distribution,
    HoldingMorningRow,
)
from apps.copilot.services.reports.base import ReportContext
from apps.copilot.services.reports.renderer import ReportRenderer


def test_push_level_mapping():
    assert health_score_to_push_level(85) == 0
    assert health_score_to_push_level(72) == 1
    assert health_score_to_push_level(55) == 2
    assert health_score_to_push_level(30) == 3


def test_render_holdings_morning_template():
    rows = [
        HoldingMorningRow(
            symbol="601138",
            name="工业富联",
            role="portfolio",
            health_score=72.0,
            push_level=1,
            color="关注",
            market_phase="expectation",
            phase_label_zh="炒预期",
            phase_confidence=0.85,
            reasoning_tags=["expectation_momentum_30d"],
            shares=2000,
            cost_price=59.3,
            last_close=70.0,
            pct_change_1d=0.005,
        )
    ]
    ctx = ReportContext(
        user_id="default",
        period_label=date.today().isoformat(),
        period_start=date.today(),
        period_end=date.today(),
        is_demo=False,
        payload={
            "rows": [],
            "portfolio": [__import__("dataclasses").asdict(rows[0])],
            "watchlist": [],
            "phase_distribution": _phase_distribution(rows),
            "color_distribution": _color_distribution(rows),
            "phase_labels_zh": {},
            "focus": ["工业富联 health 偏低"],
            "generated_at": "2026-05-28T00:00:00+00:00",
            "active_count": 1,
        },
    )
    r = ReportRenderer()
    html = r.render("holdings_morning", "html", ctx)
    md = r.render("holdings_morning", "md", ctx)
    assert "工业富联" in html
    assert "炒预期" in html
    assert "健康度" in html
    assert "601138" in md
