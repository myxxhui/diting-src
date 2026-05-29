"""P3·价格探针(30min 调度).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from apps.state_watch.probes.base_probe import BaseProbe, ProbeError, ProbeResult
from apps.state_watch.probes.datasource.quote_adapter import Bar, fetch_bars_60d


def _rsi_14(closes: list[float]) -> float:
    if len(closes) < 15:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(-14, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    if losses == 0:
        return 100.0
    rs = (gains / 14) / (losses / 14)
    return 100 - (100 / (1 + rs))


def _max_close(bars: list[Bar]) -> float:
    return max(b.close for b in bars) if bars else 0.0


def _ma(values: list[float], window: int) -> float:
    if len(values) < window:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-window:]) / window


def compute_price_metrics(bars: list[Bar]) -> dict[str, Any]:
    if len(bars) < 2:
        raise ProbeError("not enough bars")
    closes = [b.close for b in bars]
    volumes = [b.volume for b in bars]
    last_close = closes[-1]
    prev_close = closes[-2]
    pct_1d = (last_close - prev_close) / prev_close if prev_close else 0.0
    max60 = _max_close(bars)
    drawdown = (last_close / max60) - 1 if max60 else 0.0
    vol_ratio = (volumes[-1] / _ma(volumes, 20)) if _ma(volumes, 20) > 0 else 1.0
    ma20 = _ma(closes, 20)
    ma_dev = (last_close / ma20) - 1 if ma20 else 0.0
    rsi = _rsi_14(closes)
    return {
        "last_close": round(last_close, 4),
        "pct_change_1d": round(pct_1d, 6),
        "drawdown_60d": round(drawdown, 6),
        "turnover_pct": round(bars[-1].turnover_pct, 4),
        "vol_ratio_20d": round(vol_ratio, 4),
        "ma20": round(ma20, 4),
        "ma_deviation_20d": round(ma_dev, 6),
        "rsi_14": round(rsi, 4),
    }


class PriceProbe(BaseProbe):
    probe_type = "price"
    timeout_seconds = 20.0
    interval_hours = 0.5

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        bars = await asyncio.to_thread(fetch_bars_60d, symbol)
        return compute_price_metrics(bars)


async def _cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    probe = PriceProbe()
    result: ProbeResult = await probe.fetch(args.symbol)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_cli())
