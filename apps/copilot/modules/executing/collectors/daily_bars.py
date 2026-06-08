"""#15 qmt_atr_trailing · 腾讯 fqkline 250 交易日日线 → PG。

[Ref: 28_ §2.2.2 · 21_ §四 K1]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.common.market_quote.sources import tencent_kline

logger = logging.getLogger(__name__)

SOURCE_TENCENT = "tencent_fqkline"
ADJUST_QFQ = "qfq"
LOOKBACK_TRADING_DAYS = 250
MIN_BARS_ACCEPT = 200
ATR_WINDOW = 20


@dataclass(frozen=True)
class DailyBarRow:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjust: str = ADJUST_QFQ


def _klines_to_rows(klines: list[Any]) -> list[DailyBarRow]:
    rows: list[DailyBarRow] = []
    for k in klines:
        rows.append(
            DailyBarRow(
                trade_date=k.date,
                open=float(k.open),
                high=float(k.high),
                low=float(k.low),
                close=float(k.close),
                volume=float(k.volume),
                adjust=k.adjust or ADJUST_QFQ,
            )
        )
    rows.sort(key=lambda r: r.trade_date)
    return rows


def fetch_tencent_daily_bars(
    symbol: str,
    *,
    days: int = LOOKBACK_TRADING_DAYS,
    min_bars: int | None = None,
) -> tuple[list[DailyBarRow], str]:
    """仅从腾讯 fqkline 拉前复权日线；失败或不足 min_bars 返回空列表。"""
    sym = symbol.zfill(6)[-6:]
    need = MIN_BARS_ACCEPT if min_bars is None else min_bars
    klines = tencent_kline.fetch_kline(sym, days)
    if not klines:
        logger.warning("腾讯 fqkline 无数据 symbol=%s days=%d", sym, days)
        return [], SOURCE_TENCENT

    rows = _klines_to_rows(klines)
    if len(rows) < need:
        logger.warning(
            "腾讯 fqkline 根数不足 symbol=%s got=%d need>=%d",
            sym,
            len(rows),
            need,
        )
        return [], SOURCE_TENCENT
    return rows, SOURCE_TENCENT


def rows_to_ohlcv_lists(rows: list[DailyBarRow]) -> dict[str, list[float]]:
    return {
        "dates": [r.trade_date.isoformat() for r in rows],
        "open": [r.open for r in rows],
        "high": [r.high for r in rows],
        "low": [r.low for r in rows],
        "close": [r.close for r in rows],
        "volume": [r.volume for r in rows],
    }


