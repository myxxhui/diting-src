"""腾讯 qt.gtimg.cn 实时行情。

[Ref: 03_/_共享规约/21_行情数据源降级与断路器规约.md §四 P1]
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
_URL = "http://qt.gtimg.cn/q={codes}"


def parse_tencent_line(line: str) -> Optional[RealtimeQuote]:
    """解析单行 v_sh601138=\"1~工业富联~601138~67.16~...\""""
    line = line.strip()
    if not line or "=" not in line:
        return None
    payload = line.split("=", 1)[1].strip().strip('"').strip(";")
    parts = payload.split("~")
    if len(parts) < 7:
        return None
    try:
        symbol = parts[2].zfill(6)
        close = float(parts[3])
        prev_close = float(parts[4])
        volume = int(float(parts[6]) * 100)  # 手 → 股
    except (ValueError, IndexError):
        return None
    if close <= 0:
        return None

    ts_str = parts[30] if len(parts) > 30 else ""
    try:
        timestamp = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S") if ts_str else datetime.now()
    except ValueError:
        timestamp = datetime.now()

    change_pct = (close - prev_close) / prev_close if prev_close > 0 else 0.0
    return RealtimeQuote(
        symbol=symbol,
        close=close,
        prev_close=prev_close,
        change_pct=change_pct,
        volume=volume,
        timestamp=timestamp,
        source="tencent",
        is_stale=compute_is_stale(timestamp),
    )


def fetch_realtime(symbols: list[str]) -> dict[str, RealtimeQuote]:
    if not symbols:
        return {}
    codes = ",".join(tencent_code(validate_symbol(s)) for s in symbols)
    try:
        resp = httpx.get(_URL.format(codes=codes), timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[tencent] HTTP 失败: %s", exc)
        return {}

    out: dict[str, RealtimeQuote] = {}
    for line in resp.text.strip().split("\n"):
        quote = parse_tencent_line(line)
        if quote is not None:
            out[quote.symbol] = quote
    return out
