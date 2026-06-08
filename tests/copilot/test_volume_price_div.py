"""#16 volume_price_div 15m 算子单测。"""
from __future__ import annotations

from apps.copilot.modules.executing.collectors.bars_15m import Bar15m
from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node
from apps.copilot.modules.executing.t1_operators.volume_price_div import (
    VolumePriceDivError,
    process_volume_price_div,
)


def _synthetic_bars(n: int = 170) -> list[Bar15m]:
    bars: list[Bar15m] = []
    for i in range(n):
        price = 80.0 + (i % 20) * 0.5
        is_down = i % 3 == 0
        o = price + (0.2 if is_down else -0.2)
        c = price - (0.3 if is_down else 0.1)
        bars.append(
            Bar15m(
                datetime=f"2026-06-01 10:{i%60:02d}:00",
                open=o,
                high=max(o, c) + 0.1,
                low=min(o, c) - 0.1,
                close=c,
                volume=1000.0 + i * 10 + (500 if is_down else 0),
            )
        )
    return bars


def test_process_volume_price_div_ok():
    payload = process_volume_price_div(_synthetic_bars(), source="tencent_mkline_m15_qfq")
    assert payload["indicator_key"] == "volume_price_div"
    assert payload["value"] is not None
    assert payload["bars_count"] >= 160
    assert "阈值" not in payload["fact_statement"]
    assert "健康" not in payload["fact_statement"]
    assert payload["calculation_logic"] == "高位区阴线总成交量 / 高位区阳线总成交量"
    assert "(170 bars)" in payload["source"]
    assert payload["period_max"] is not None
    assert payload["period_min"] is not None
    assert payload["high_zone_threshold_price"] is not None
    assert payload["high_zone_down_vol"] >= 0
    assert payload["high_zone_up_vol"] >= 0
    assert payload["global_up_vol"] >= 0
    assert payload["global_down_vol"] >= 0


def test_build_volume_price_div_node_raw_metrics():
    payload = process_volume_price_div(_synthetic_bars(), source="tencent_mkline_m15_qfq")
    node = build_volume_price_div_node(payload)
    assert node["indicator_name"] == "15分钟级高位量价背离"
    rm = node["raw_metrics"]
    assert "high_zone_down_vol" in rm
    assert "high_zone_up_vol" in rm
    assert "high_zone_threshold_price" in rm
    assert "period_max" in rm
    assert "period_min" in rm
    assert "global_vol_ratio" in rm
    assert "global_up_vol" in rm
    assert "global_down_vol" in rm
    assert "倍。" in node["fact_statement"]


def test_process_volume_price_div_insufficient():
    try:
        process_volume_price_div(_synthetic_bars(50))
        raise AssertionError("expected error")
    except VolumePriceDivError:
        pass
