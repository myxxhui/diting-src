"""#16 volume_price_div · 15min 量价背离硬算算子。

[Ref: 28_ §2.2 · 探针 #16]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.collectors.bars_15m import Bar15m, MIN_BARS_ACCEPT, SOURCE_EM_15M

INDICATOR_KEY = "volume_price_div"
HIGH_ZONE_PCT = 0.30  # 收盘价处于近期区间上 30% 视为「高位」


class VolumePriceDivError(Exception):
    pass


def _bars_from_payload(payload: dict[str, Any]) -> list[Bar15m]:
    raw = payload.get("bars") or []
    out: list[Bar15m] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            out.append(
                Bar15m(
                    datetime=str(row["datetime"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _format_bar_datetime(dt: str) -> str:
    s = str(dt).strip()
    if len(s) == 16 and s[10] == " ":  # 2026-06-08 15:00
        return f"{s}:00"
    return s


def _format_source_label(source: str, bars_count: int) -> str:
    base = (source or SOURCE_EM_15M).strip()
    return f"{base} ({bars_count} bars)"


def process_volume_price_div(
    bars: list[Bar15m],
    *,
    source: str = SOURCE_EM_15M,
) -> dict[str, Any]:
    """高位区阴线量 / 高位区阳线量 → 背离指数。"""
    if len(bars) < MIN_BARS_ACCEPT:
        raise VolumePriceDivError(
            f"15m K 线不足 {MIN_BARS_ACCEPT} 根（got {len(bars)}）"
        )

    closes = [b.close for b in bars]
    period_min = min(closes)
    period_max = max(closes)
    span = period_max - period_min
    if span <= 0:
        raise VolumePriceDivError("收盘价区间无效")

    high_zone_threshold = period_min + span * (1.0 - HIGH_ZONE_PCT)
    global_up_vol = 0.0
    global_down_vol = 0.0
    high_zone_up_vol = 0.0
    high_zone_down_vol = 0.0
    for b in bars:
        is_up = b.close >= b.open
        in_high = b.close >= high_zone_threshold
        if is_up:
            global_up_vol += b.volume
            if in_high:
                high_zone_up_vol += b.volume
        else:
            global_down_vol += b.volume
            if in_high:
                high_zone_down_vol += b.volume

    global_down_vol_safe = global_down_vol or 1e-9
    high_zone_up_safe = high_zone_up_vol or 1e-9
    global_vol_ratio = round(global_up_vol / global_down_vol_safe, 4)
    value = round(high_zone_down_vol / high_zone_up_safe, 2)

    fact = (
        f"近期高位区间内，15分钟级阴线成交总量为阳线成交总量的 {value} 倍。"
    )
    logic = "高位区阴线总成交量 / 高位区阳线总成交量"
    last_bar_datetime = _format_bar_datetime(bars[-1].datetime)

    return {
        "indicator_key": INDICATOR_KEY,
        "value": value,
        "source": _format_source_label(source, len(bars)),
        "calculation_logic": logic,
        "fact_statement": fact,
        "bars_count": len(bars),
        "period_min": round(period_min, 2),
        "period_max": round(period_max, 2),
        "high_zone_threshold_price": round(high_zone_threshold, 2),
        "global_up_vol": round(global_up_vol, 2),
        "global_down_vol": round(global_down_vol, 2),
        "high_zone_up_vol": round(high_zone_up_vol, 2),
        "high_zone_down_vol": round(high_zone_down_vol, 2),
        "global_vol_ratio": global_vol_ratio,
        "last_bar_datetime": last_bar_datetime,
    }


def process_volume_price_div_from_redis(
    redis_payload: dict[str, Any] | None,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    if not redis_payload:
        raise VolumePriceDivError("Redis 15m 缓存缺失")
    bars = _bars_from_payload(redis_payload)
    return process_volume_price_div(
        bars,
        source=source or str(redis_payload.get("source") or SOURCE_EM_15M),
    )
