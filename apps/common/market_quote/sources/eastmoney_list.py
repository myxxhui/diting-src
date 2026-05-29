"""东方财富 push2 实时 list。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §四 P3]
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from apps.common.market_quote.exchange import eastmoney_secid, validate_symbol
from apps.common.market_quote.schemas import RealtimeQuote
from apps.common.market_quote.time_utils import compute_is_stale

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
_URL = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get"
    "?secids={secids}&fields=f12,f14,f2,f3,f4,f6"
)
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; diting-market-quote/1.0)"}
_BATCH_SIZE = 100


def parse_eastmoney_item(item: dict[str, Any]) -> RealtimeQuote | None:
    try:
        symbol = str(item["f12"]).zfill(6)
        f2 = item.get("f2")
        if f2 is None or f2 == "-":
            return None
        close = float(f2) / 100.0
        f3 = item.get("f3")
        change_pct = float(f3) / 100.0 if f3 not in (None, "-") else 0.0
    except (KeyError, TypeError, ValueError):
        return None
    if close <= 0:
        return None
    prev_close = close / (1 + change_pct) if change_pct != -1 else close
    timestamp = datetime.now()
    return RealtimeQuote(
        symbol=symbol,
        close=close,
        prev_close=prev_close,
        change_pct=change_pct,
        volume=0,
        timestamp=timestamp,
        source="eastmoney_list",
        is_stale=compute_is_stale(timestamp),
    )


def fetch_realtime(symbols: list[str]) -> dict[str, RealtimeQuote]:
    if not symbols:
        return {}
    out: dict[str, RealtimeQuote] = {}
    normalized = [validate_symbol(s) for s in symbols]

    for i in range(0, len(normalized), _BATCH_SIZE):
        batch = normalized[i : i + _BATCH_SIZE]
        secids = ",".join(eastmoney_secid(s) for s in batch)
        try:
            resp = httpx.get(_URL.format(secids=secids), headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[eastmoney_list] HTTP 失败 batch=%d: %s", i // _BATCH_SIZE, exc)
            continue
        diff = (data.get("data") or {}).get("diff") or []
        for item in diff:
            quote = parse_eastmoney_item(item)
            if quote is not None:
                out[quote.symbol] = quote
    return out
