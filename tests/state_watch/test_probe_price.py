"""P3·价格探针测试.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import pytest

from apps.state_watch.probes.datasource.quote_adapter import Bar
from apps.state_watch.probes.price import PriceProbe, compute_price_metrics


def _make_bars(closes: list[float], volumes: list[float] | None = None) -> list[Bar]:
    n = len(closes)
    volumes = volumes or [1000.0] * n
    bars = []
    for i, c in enumerate(closes):
        bars.append(
            Bar(
                date=f"D{i:02d}",
                open=c,
                high=c * 1.01,
                low=c * 0.99,
                close=c,
                volume=volumes[i],
                turnover_pct=1.5,
            )
        )
    return bars


class TestPureFunctions:
    def test_pct_change_calc(self):
        bars = _make_bars([100, 110])
        m = compute_price_metrics(bars)
        assert m["pct_change_1d"] == pytest.approx(0.1, abs=1e-6)

    def test_drawdown_neg(self):
        bars = _make_bars([120, 110, 100, 90])
        m = compute_price_metrics(bars)
        assert m["drawdown_60d"] < 0
        assert m["drawdown_60d"] == pytest.approx((90 / 120) - 1, abs=1e-6)

    def test_rsi_all_up_returns_100(self):
        closes = [100 + i for i in range(20)]
        bars = _make_bars(closes)
        m = compute_price_metrics(bars)
        assert m["rsi_14"] == 100.0

    def test_rsi_all_down_low(self):
        closes = [120 - i for i in range(20)]
        bars = _make_bars(closes)
        m = compute_price_metrics(bars)
        assert m["rsi_14"] < 30

    def test_vol_ratio_high_when_spike(self):
        closes = [100] * 30
        volumes = [1000.0] * 29 + [10000.0]
        bars = _make_bars(closes, volumes)
        m = compute_price_metrics(bars)
        assert m["vol_ratio_20d"] > 5

    def test_ma_deviation_neg_when_below(self):
        closes = [100] * 19 + [85]
        bars = _make_bars(closes)
        m = compute_price_metrics(bars)
        assert m["ma_deviation_20d"] < 0


class TestPriceProbeIntegration:
    """集成测试走 MarketQuote（腾讯 K 线优先，见规约 21）。"""

    async def test_fetch_returns_keys(self):
        probe = PriceProbe()
        result = await probe.fetch("601138")
        assert result.success is True, result.error
        expected = {
            "last_close",
            "pct_change_1d",
            "drawdown_60d",
            "turnover_pct",
            "vol_ratio_20d",
            "ma20",
            "ma_deviation_20d",
            "rsi_14",
        }
        assert expected.issubset(result.data.keys())

    async def test_fetch_elapsed_recorded(self):
        probe = PriceProbe()
        result = await probe.fetch("601138")
        assert result.success is True, result.error
        assert result.elapsed_ms >= 0
