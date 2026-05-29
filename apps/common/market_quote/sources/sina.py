"""新浪 hq.sinajs.cn 实时行情。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §四 P2]
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import httpx

from apps.common.market_quote.exchange import tencent_code, validate_symbol
from apps.common.market_quote.schemas import RealtimeQuote
from apps.common.market_quote.time_utils import compute_is_stale

logger = logging.getLogger(__name__)

_TIMEOUT = 3.0
_URL = "http://hq.sinajs.cn/list={codes}"
_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (compatible; diting-market-quote/1.0)",
}
_BATCH_SIZE = 50


def parse_sina_line(line: str) -> Optional[RealtimeQuote]:
    line = line.strip()
    if "=" not in line:
        return None
    prefix, payload = line.split("=", 1)
    payload = payload.strip().strip('"').strip(";")
    if not payload:
        return None
    parts = payload.split(",")
    if len(parts) < 9:
        return None

    # var hq_str_sh601138 → symbol from prefix
    key = prefix.split("_")[-1] if "_" in prefix else ""
    symbol = key[2:] if len(key) >= 8 else ""
    if not symbol:
        return None

    try:
        prev_close = float(parts[2])
        close = float(parts[3])
        volume = int(float(parts[8]))
    except (ValueError, IndexError):
        return None
    if close <= 0:
        return None

    if len(parts) >= 32:
        ts_str = f"{parts[30]} {parts[31]}"
        try:
            timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()

    change_pct = (close - prev_close) / prev_close if prev_close > 0 else 0.0
    return RealtimeQuote(
        symbol=symbol.zfill(6),
        close=close,
        prev_close=prev_close,
        change_pct=change_pct,
        volume=volume,
        timestamp=timestamp,
        source="sina",
        is_stale=compute_is_stale(timestamp),
    )


def fetch_realtime(symbols: list[str]) -> dict[str, RealtimeQuote]:
    if not symbols:
        return {}
    out: dict[str, RealtimeQuote] = {}
    normalized = [validate_symbol(s) for s in symbols]

    for i in range(0, len(normalized), _BATCH_SIZE):
        batch = normalized[i : i + _BATCH_SIZE]
        codes = ",".join(tencent_code(s) for s in batch)
        try:
            resp = httpx.get(_URL.format(codes=codes), headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[sina] HTTP 失败 batch=%d: %s", i // _BATCH_SIZE, exc)
            continue
        for line in resp.text.strip().split("\n"):
            quote = parse_sina_line(line)
            if quote is not None:
                out[quote.symbol] = quote
    return out
