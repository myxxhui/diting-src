"""#15 盘中 T-0 草稿 K 线 · Redis 原位覆盖（不写 PG）。

[Ref: 28_ §2.2.2 · §3.4]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from apps.copilot.db.datetime_util import shanghai_now_iso
from apps.copilot.modules.executing.collectors.daily_bars import (
    ADJUST_QFQ,
    DailyBarRow,
    SOURCE_TENCENT,
    fetch_tencent_daily_bars,
)
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
    SOURCE_INTRADAY,
    compute_atr_trailing_payload,
)

logger = logging.getLogger(__name__)

DRAFT_BAR_KEY = "executing:draft_bar:{symbol}"
ATR_INTRADAY_KEY = "executing:atr_intraday:{symbol}"
QUOTE_KEY = "executing:quote:{symbol}"
# 交易时段 + 缓冲；盘中仅覆盖写，不追加历史
DRAFT_BAR_TTL_SEC = 36000
ATR_INTRADAY_TTL_SEC = 600


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def fetch_today_draft_bar(symbol: str) -> DailyBarRow | None:
    """腾讯 fqkline 最近几根；末行若为当日则作为未收盘日 K 草稿。"""
    from apps.copilot.db.datetime_util import shanghai_today

    sym = _sym(symbol)
    rows, _ = fetch_tencent_daily_bars(sym, days=3, min_bars=1)
    if not rows:
        return None
    last = rows[-1]
    today = shanghai_today()
    if last.trade_date != today:
        logger.debug("无当日 fqkline 草稿 symbol=%s last=%s today=%s", sym, last.trade_date, today)
        return None
    return last


def draft_bar_to_dict(row: DailyBarRow, *, source: str = SOURCE_TENCENT) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.isoformat(),
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "adjust": row.adjust,
        "source": source,
        "collected_at": shanghai_now_iso(),
        "mode": "intraday_overwrite",
    }


def dict_to_draft_bar(data: dict[str, Any]) -> DailyBarRow | None:
    try:
        return DailyBarRow(
            trade_date=date.fromisoformat(str(data["trade_date"])),
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data["volume"]),
            adjust=str(data.get("adjust") or ADJUST_QFQ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def merge_pg_rows_with_draft(
    pg_rows: list[DailyBarRow],
    draft: DailyBarRow | None,
) -> list[DailyBarRow]:
    """PG 历史 + Redis 当日草稿：同 trade_date 用草稿覆盖末行（模拟 250 行里 T-0 原位刷新）。"""
    if draft is None:
        return list(pg_rows)
    if not pg_rows:
        return [draft]
    out = list(pg_rows)
    if out[-1].trade_date == draft.trade_date:
        out[-1] = draft
    elif out[-1].trade_date < draft.trade_date:
        out.append(draft)
    return out


def overwrite_draft_bar(redis_client: Any, symbol: str, row: DailyBarRow) -> None:
    """Redis SET 覆盖写（非 append）。"""
    sym = _sym(symbol)
    payload = json.dumps(draft_bar_to_dict(row), ensure_ascii=False)
    redis_client.setex(DRAFT_BAR_KEY.format(symbol=sym), DRAFT_BAR_TTL_SEC, payload)


def load_draft_bar_dict(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    """Redis 草稿原文（含 collected_at · 供 T1 last_tick_time）。"""
    if redis_client is None:
        return None
    raw = redis_client.get(DRAFT_BAR_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def load_draft_bar(redis_client: Any, symbol: str) -> DailyBarRow | None:
    data = load_draft_bar_dict(redis_client, symbol)
    if not data:
        return None
    return dict_to_draft_bar(data)


def overwrite_atr_intraday(
    redis_client: Any,
    symbol: str,
    payload: dict[str, Any] | None,
) -> None:
    if redis_client is None or not payload:
        return
    sym = _sym(symbol)
    body = json.dumps({**payload, "mode": "intraday"}, ensure_ascii=False)
    redis_client.setex(ATR_INTRADAY_KEY.format(symbol=sym), ATR_INTRADAY_TTL_SEC, body)


def load_atr_intraday(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(ATR_INTRADAY_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def compute_intraday_atr(
    pg_rows: list[DailyBarRow],
    draft: DailyBarRow,
    *,
    entry_date: date | None = None,
    source: str = SOURCE_INTRADAY,
) -> dict[str, Any] | None:
    merged = merge_pg_rows_with_draft(pg_rows, draft)
    payload = compute_atr_trailing_payload(
        merged, entry_date=entry_date, source=source
    )
    if payload:
        payload["draft_source"] = SOURCE_TENCENT
        payload["current"] = round(draft.close, 4)
        payload["intraday"] = True
    return payload


def clear_intraday_draft(redis_client: Any, symbol: str) -> None:
    """盘后 PG 落库后清除草稿，避免次日误用昨日 Redis。"""
    if redis_client is None:
        return
    sym = _sym(symbol)
    redis_client.delete(
        DRAFT_BAR_KEY.format(symbol=sym),
        ATR_INTRADAY_KEY.format(symbol=sym),
    )
