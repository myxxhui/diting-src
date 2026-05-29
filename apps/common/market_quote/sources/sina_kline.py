"""新浪 K 线兜底（JSONP）。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §四 K2]
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

import httpx

from apps.common.market_quote.exchange import tencent_code, validate_symbol
from apps.common.market_quote.schemas import Kline

logger = logging.getLogger(__name__)

_TIMEOUT = 5.0
_URL = "https://finance.sina.com.cn/realstock/company/{code}/hisdata/klc_kl.js"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; diting-market-quote/1.0)"}


def fetch_kline(symbol: str, days: int) -> list[Kline]:
    if days <= 0:
        raise ValueError("days 须 > 0")
    sym = validate_symbol(symbol)
    code = tencent_code(sym)
    try:
        resp = httpx.get(_URL.format(code=code), headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sina_kline] HTTP 失败 symbol=%s: %s", sym, exc)
        return []

    match = re.search(r"\((\[.*\])\)", text, re.DOTALL)
    if not match:
        return []
    try:
        rows = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    out: list[Kline] = []
    for row in rows[-days:]:
        if not isinstance(row, dict):
            continue
        try:
            d = str(row.get("d", "")).replace("/", "-")
            out.append(
                Kline(
                    date=date.fromisoformat(d),
                    open=float(row["o"]),
                    high=float(row["h"]),
                    low=float(row["l"]),
                    close=float(row["c"]),
                    volume=int(float(row.get("v", 0))),
                    adjust="qfq",
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out
