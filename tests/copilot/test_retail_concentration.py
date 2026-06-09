"""retail_concentration T1 算子单测。"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from apps.copilot.modules.executing.indicator_nodes import build_retail_concentration_node
from apps.copilot.modules.executing.retail_concentration import (
    RETAIL_DANGER_PERCENTILE,
    compute_retail_concentration_metrics,
)


def _snap(end: date, holder: float, prev: float, avg: float) -> dict:
    chg = (holder - prev) / prev if prev else None
    return {
        "end_date": end.strftime("%Y%m%d"),
        "announce_date": end.strftime("%Y%m%d"),
        "holder_num": holder,
        "previous_holder_num": prev,
        "holder_num_change": chg,
        "avg_hold_vol": avg,
        "free_float_shares": avg * holder,
    }


def _payload(*, days_ago: int = 9, spike: bool = True) -> dict:
    today = date.today()
    end = today - timedelta(days=days_ago)
    snaps = []
    base = 30000.0
    for i in range(14):
        d = end - timedelta(days=90 * (13 - i))
        h = base + i * 100
        snaps.append(_snap(d, h, h - 50, 28000.0 - i * 200))
    latest_h = 42500.0 if spike else 36000.0
    prev_h = 35865.0 if spike else 36500.0
    snaps[-1] = _snap(end, latest_h, prev_h, 12500.0)
    return {"snapshots": snaps}


def test_compute_retail_concentration_low_percentile():
    m = compute_retail_concentration_metrics(_payload())
    assert m["value"] <= RETAIL_DANGER_PERCENTILE + 5
    assert m["raw_metrics"]["days_since_snapshot"] == 9
    assert m["raw_metrics"]["data_reliability"] == "HIGH"
    node = build_retail_concentration_node(m)
    assert node["indicator_name"] == "户均持股集中度与筹码分散检测"


def test_compute_retail_concentration_stale_warning():
    m = compute_retail_concentration_metrics(_payload(days_ago=45))
    assert m["raw_metrics"]["data_stale_warning"] is True
    assert m["raw_metrics"]["data_reliability"] == "STALE"


def test_insufficient_snapshots_raises():
    with pytest.raises(ValueError, match="快照不足"):
        compute_retail_concentration_metrics({"snapshots": _payload()["snapshots"][:5]})


def test_render_retail_concentration_card_and_formula_html():
    from apps.copilot.modules.executing.executing_render import (
        _highlight_formula,
        render_retail_concentration_card,
    )

    m = compute_retail_concentration_metrics(_payload())
    node = build_retail_concentration_node(m)
    html = render_retail_concentration_card(node)
    assert "retail_concentration" in html
    assert "border-left-color:#14b8a6" in html
    assert "data-probe-category" in html

    formula_html = _highlight_formula("(84.95 - 70.48) / 4.73 = 3.06")
    assert '<span class="text-slate-900 font-semibold">84.95</span>' in formula_html
    assert "&lt;span" not in formula_html
