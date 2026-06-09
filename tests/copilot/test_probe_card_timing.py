"""JL4 卡片顶栏时间语义单测。"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from apps.copilot.modules.executing.probe_card_timing import (
    ProbeCardTiming,
    build_card_timing,
    render_card_timing_bar,
)
from apps.copilot.db.models import ExecutingT0ProbeState, ExecutingT1ProbeSnapshot


def _probe_state(*, status: str = "ok", stale: bool = False) -> ExecutingT0ProbeState:
    now = datetime(2026, 6, 9, 7, 30, 0)
    ps = ExecutingT0ProbeState(symbol="601138", probe_key="turnover_acceleration", status=status)
    ps.collected_at = now
    ps.as_of = date(2026, 6, 9)
    ps.stale_after = now - timedelta(hours=1) if stale else now + timedelta(days=1)
    ps.blocker = "PG 行数不足" if status != "ok" else None
    return ps


def _t1_row() -> ExecutingT1ProbeSnapshot:
    row = ExecutingT1ProbeSnapshot(symbol="601138", probe_key="turnover_acceleration")
    row.trade_date = date(2026, 6, 8)
    row.collected_at = datetime(2026, 6, 9, 7, 31, 0)
    return row


def test_build_card_timing_prefers_watermark():
    node = {
        "value": 1.2,
        "raw_metrics": {"trade_date": "2026-06-08"},
    }
    sync = {
        "watermarks": [
            {
                "job_id": "l4-turnover-accel-eod",
                "symbol": "*",
                "last_success_at_cst": "2026-06-09 15:30:00",
                "last_error": None,
            }
        ]
    }
    timing = build_card_timing(
        "turnover_acceleration",
        symbol="601138",
        node=node,
        probe_state=_probe_state(),
        t1_row=_t1_row(),
        sync=sync,
    )
    assert timing.t0_collected_label == "2026-06-09 15:30:00"
    assert timing.t0_job_id == "l4-turnover-accel-eod"


def test_build_card_timing_ok():
    node = {
        "value": 1.2,
        "raw_metrics": {"trade_date": "2026-06-08"},
    }
    timing = build_card_timing(
        "turnover_acceleration",
        symbol="601138",
        node=node,
        probe_state=_probe_state(),
        t1_row=_t1_row(),
    )
    assert timing.health == "ok"
    assert timing.t1_effective_label == "2026-06-08"
    assert timing.t0_collected_label is not None
    assert "15:31" in (timing.t1_published_label or "")


def test_build_card_timing_failed_red_alert():
    timing = build_card_timing(
        "tech_beta_correlation",
        node={"value": 0.5, "raw_metrics": {}},
        probe_state=_probe_state(status="missing"),
    )
    assert timing.health == "failed"
    assert timing.alert


def test_render_card_timing_bar_layout():
    html_ok = render_card_timing_bar(
        ProbeCardTiming(
            t1_effective_label="2026-06-08",
            t1_published_label="2026-06-09 15:31:00",
            t0_collected_label="2026-06-09 15:30:12",
            health="ok",
        )
    )
    assert "T1有效 2026-06-08" in html_ok
    assert "T1测算 2026-06-09 15:31:00" in html_ok
    assert "T0增量 2026-06-09 15:30:12" in html_ok
    assert "text-rose-600" not in html_ok

    html_bad = render_card_timing_bar(
        ProbeCardTiming(
            t1_effective_label="2026-06-08",
            t1_published_label=None,
            t0_collected_label="2026-06-09 15:30:12",
            health="failed",
            alert="beta PG 行数=0 需>=120",
        )
    )
    assert "text-rose-600" in html_bad
    assert "beta PG" in html_bad


def test_render_turnover_card_with_timing():
    from apps.copilot.modules.executing.executing_render import render_turnover_acceleration_card

    timing = ProbeCardTiming(
        t1_effective_label="2026-06-08",
        t1_published_label="2026-06-09 15:31:00",
        t0_collected_label="2026-06-09 15:30:00",
        health="ok",
    )
    html = render_turnover_acceleration_card(
        {
            "value": 1.5,
            "fact_statement": "测试",
            "calculation_logic": "x/y",
            "source": "Tushare",
            "raw_metrics": {"trade_date": "2026-06-08"},
        },
        card_timing=timing,
    )
    assert "T1有效 2026-06-08" in html
    assert "T0增量" in html
    assert 'data-timing-health="ok"' in html
