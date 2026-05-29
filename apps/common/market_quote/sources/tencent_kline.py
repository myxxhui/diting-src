"""腾讯 fqkline 日线 K 线。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §四 K1]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from apps.common.market_quote.exchange import tencent_code, validate_symbol
from apps.common.market_quote.schemas import Kline

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; diting-market-quote/1.0)",
    "Referer": "https://gu.qq.com/",
}


def _parse_rows(rows: list[list[Any]]) -> list[Kline]:
    out: list[Kline] = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            out.append(
                Kline(
                    date=date.fromisoformat(str(row[0])),
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=int(float(row[5])),
                    adjust="qfq",
                )
            )
        except (ValueError, TypeError):
            continue
    return out


def fetch_kline(symbol: str, days: int) -> list[Kline]:
    if days <= 0:
        raise ValueError("days 须 > 0")
    sym = validate_symbol(symbol)
    code = tencent_code(sym)
    param = f"{code},day,,,{days},qfq"
    try:
        resp = httpx.get(_URL.format(param=param), headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tencent_kline] HTTP 失败 symbol=%s: %s", sym, exc)
        return []

    data = payload.get("data") or {}
    block = data.get(code) or {}
    rows = block.get("qfqday") or block.get("day") or []
    return _parse_rows(rows)
