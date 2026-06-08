"""#17 smart_money_flow · PG 底库 + Redis 热缓存。

[Ref: 28_ §3.2.1 · executing_moneyflow_daily]
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingMoneyflowDaily

logger = logging.getLogger(__name__)

MONEYFLOW_REDIS_KEY = "executing:moneyflow:{symbol}"
MONEYFLOW_REDIS_TTL_SEC = 86400 * 14  # 14 天 · 集群重启后可从 PG 再灌
MONEYFLOW_TARGET_TRADING_DAYS = 250
MONEYFLOW_MIN_TRADING_DAYS = 3


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_trade_date(raw: str) -> date:
    s = str(raw).strip().replace("-", "")
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return date.fromisoformat(str(raw)[:10])


def row_to_dict(row: ExecutingMoneyflowDaily) -> dict[str, Any]:
    return {
        "trade_date": row.trade_date.strftime("%Y%m%d"),
        "buy_elg_vol": float(row.buy_elg_vol),
        "sell_elg_vol": float(row.sell_elg_vol),
        "buy_lg_vol": float(row.buy_lg_vol),
        "sell_lg_vol": float(row.sell_lg_vol),
        "buy_md_vol": float(row.buy_md_vol),
        "sell_md_vol": float(row.sell_md_vol),
        "buy_sm_vol": float(row.buy_sm_vol),
        "sell_sm_vol": float(row.sell_sm_vol),
        "net_mf_vol": float(row.net_mf_vol),
    }


async def count_moneyflow_rows(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count())
        .select_from(ExecutingMoneyflowDaily)
        .where(ExecutingMoneyflowDaily.symbol == sym)
    )
    return int(n or 0)


async def load_moneyflow_rows(
    session: AsyncSession,
    symbol: str,
    *,
    limit: int = MONEYFLOW_TARGET_TRADING_DAYS,
) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    db_rows = (
        await session.scalars(
            select(ExecutingMoneyflowDaily)
            .where(ExecutingMoneyflowDaily.symbol == sym)
            .order_by(ExecutingMoneyflowDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [row_to_dict(r) for r in ordered]


async def upsert_moneyflow_rows(
    session: AsyncSession,
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> int:
    sym = _sym(symbol)
    if not rows:
        return 0
    now = utc_now_naive()
    n = 0
    for r in rows:
        td = _parse_trade_date(str(r.get("trade_date", "")))
        existing = await session.get(
            ExecutingMoneyflowDaily,
            {"symbol": sym, "trade_date": td},
        )
        if existing is None:
            session.add(
                ExecutingMoneyflowDaily(
                    symbol=sym,
                    trade_date=td,
                    buy_elg_vol=float(r.get("buy_elg_vol") or 0),
                    sell_elg_vol=float(r.get("sell_elg_vol") or 0),
                    buy_lg_vol=float(r.get("buy_lg_vol") or 0),
                    sell_lg_vol=float(r.get("sell_lg_vol") or 0),
                    buy_md_vol=float(r.get("buy_md_vol") or 0),
                    sell_md_vol=float(r.get("sell_md_vol") or 0),
                    buy_sm_vol=float(r.get("buy_sm_vol") or 0),
                    sell_sm_vol=float(r.get("sell_sm_vol") or 0),
                    net_mf_vol=float(r.get("net_mf_vol") or 0),
                    source=source,
                    collected_at=now,
                )
            )
        else:
            existing.buy_elg_vol = float(r.get("buy_elg_vol") or 0)
            existing.sell_elg_vol = float(r.get("sell_elg_vol") or 0)
            existing.buy_lg_vol = float(r.get("buy_lg_vol") or 0)
            existing.sell_lg_vol = float(r.get("sell_lg_vol") or 0)
            existing.buy_md_vol = float(r.get("buy_md_vol") or 0)
            existing.sell_md_vol = float(r.get("sell_md_vol") or 0)
            existing.buy_sm_vol = float(r.get("buy_sm_vol") or 0)
            existing.sell_sm_vol = float(r.get("sell_sm_vol") or 0)
            existing.net_mf_vol = float(r.get("net_mf_vol") or 0)
            existing.source = source
            existing.collected_at = now
        n += 1
    await session.flush()
    return n


def save_moneyflow_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if redis_client is None:
        return
    sym = _sym(symbol)
    body = dict(payload)
    body["cached_at"] = shanghai_now_iso()
    redis_client.setex(
        MONEYFLOW_REDIS_KEY.format(symbol=sym),
        MONEYFLOW_REDIS_TTL_SEC,
        json.dumps(body, ensure_ascii=False),
    )


def load_moneyflow_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    raw = redis_client.get(MONEYFLOW_REDIS_KEY.format(symbol=_sym(symbol)))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def build_payload_from_pg(
    session: AsyncSession,
    symbol: str,
    *,
    free_float_shares: float | None,
    ts_code: str,
    limit: int = MONEYFLOW_TARGET_TRADING_DAYS,
) -> dict[str, Any]:
    rows = await load_moneyflow_rows(session, symbol, limit=limit)
    last_date = rows[-1]["trade_date"] if rows else ""
    return {
        "moneyflow_rows": rows,
        "free_float_shares": free_float_shares,
        "last_update_date": last_date,
        "ts_code": ts_code,
        "rows_in_pg": len(rows),
        "history_store": "executing_moneyflow_daily",
    }


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    """T0 raw 存摘要 + 末 3 日样本；全量历史在 executing_moneyflow_daily。"""
    rows = list(payload.get("moneyflow_rows") or [])
    return {
        "ts_code": payload.get("ts_code"),
        "last_update_date": payload.get("last_update_date"),
        "free_float_shares": payload.get("free_float_shares"),
        "rows_in_pg": payload.get("rows_in_pg", len(rows)),
        "history_store": payload.get("history_store", "executing_moneyflow_daily"),
        "moneyflow_rows_count": len(rows),
        "moneyflow_rows_tail": rows[-3:] if rows else [],
    }
