"""#24 etf_redemption_impact · PG ETF 持仓链接 + 份额日序列 + Redis 热缓存。

[Ref: 28_ §3.2.8 · executing_etf_stock_link / executing_etf_share_daily]
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import shanghai_now_iso, utc_now_naive
from apps.copilot.db.models import ExecutingEtfShareDaily, ExecutingEtfStockLink

logger = logging.getLogger(__name__)

ETF_REDIS_KEY = "executing:etf_redemption:{symbol}"
ETF_BACKFILL_KEY = "executing:etf_redemption:backfill:{symbol}"
ETF_DISC_CURSOR_KEY = "executing:etf_redemption:disc_cursor:{symbol}"
ETF_UNIVERSE_REDIS_KEY = "executing:etf_universe"
ETF_REDIS_TTL_SEC = 86400 * 14
ETF_LOOKBACK_CALENDAR_DAYS = 90


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _parse_date(raw: str | date | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    s = str(raw).strip().replace("-", "")[:8]
    if len(s) == 8:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    return None


async def load_etf_links(session: AsyncSession, symbol: str) -> list[dict[str, Any]]:
    sym = _sym(symbol)
    rows = (
        await session.scalars(
            select(ExecutingEtfStockLink)
            .where(ExecutingEtfStockLink.symbol == sym)
            .order_by(ExecutingEtfStockLink.stock_weight.desc())
        )
    ).all()
    return [
        {
            "etf_ts_code": r.etf_ts_code,
            "stock_weight": float(r.stock_weight),
            "report_end_date": r.report_end_date.strftime("%Y%m%d") if r.report_end_date else "",
            "link_source": r.link_source or "",
        }
        for r in rows
    ]


async def upsert_etf_links(
    session: AsyncSession,
    symbol: str,
    links: list[dict[str, Any]],
    *,
    source: str,
) -> int:
    sym = _sym(symbol)
    if not links:
        return 0
    now = utc_now_naive()
    n = 0
    for lk in links:
        etf = str(lk.get("etf_ts_code") or "").strip()
        if not etf:
            continue
        w = float(lk.get("stock_weight") or 0)
        if w <= 0:
            continue
        rep = _parse_date(lk.get("report_end_date"))
        existing = await session.scalar(
            select(ExecutingEtfStockLink).where(
                ExecutingEtfStockLink.symbol == sym,
                ExecutingEtfStockLink.etf_ts_code == etf,
            )
        )
        if existing:
            existing.stock_weight = w
            existing.report_end_date = rep
            existing.link_source = str(lk.get("link_source") or source)[:64]
            existing.collected_at = now
        else:
            session.add(
                ExecutingEtfStockLink(
                    symbol=sym,
                    etf_ts_code=etf,
                    stock_weight=w,
                    report_end_date=rep,
                    link_source=str(lk.get("link_source") or source)[:64],
                    source=source,
                    collected_at=now,
                )
            )
        n += 1
    await session.flush()
    return n


async def upsert_etf_share_rows(
    session: AsyncSession,
    etf_ts_code: str,
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> int:
    if not rows:
        return 0
    now = utc_now_naive()
    n = 0
    for r in rows:
        td = _parse_date(r.get("trade_date"))
        if td is None:
            continue
        existing = await session.scalar(
            select(ExecutingEtfShareDaily).where(
                ExecutingEtfShareDaily.etf_ts_code == etf_ts_code,
                ExecutingEtfShareDaily.trade_date == td,
            )
        )
        fd = float(r.get("fd_share") or 0)
        nav = r.get("unit_nav")
        nav_f = float(nav) if nav is not None else None
        chg = r.get("fd_share_change")
        chg_f = float(chg) if chg is not None else None
        if existing:
            existing.fd_share = fd
            existing.unit_nav = nav_f
            existing.fd_share_change = chg_f
            existing.source = source
            existing.collected_at = now
        else:
            session.add(
                ExecutingEtfShareDaily(
                    etf_ts_code=etf_ts_code,
                    trade_date=td,
                    fd_share=fd,
                    fd_share_change=chg_f,
                    unit_nav=nav_f,
                    source=source,
                    collected_at=now,
                )
            )
        n += 1
    await session.flush()
    return n


async def load_etf_share_series(
    session: AsyncSession,
    etf_ts_code: str,
    *,
    limit: int = 120,
) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(ExecutingEtfShareDaily)
            .where(ExecutingEtfShareDaily.etf_ts_code == etf_ts_code)
            .order_by(ExecutingEtfShareDaily.trade_date.desc())
            .limit(limit)
        )
    ).all()
    ordered = sorted(rows, key=lambda r: r.trade_date)
    return [
        {
            "trade_date": r.trade_date.strftime("%Y%m%d"),
            "fd_share": float(r.fd_share),
            "fd_share_change": float(r.fd_share_change) if r.fd_share_change is not None else None,
            "unit_nav": float(r.unit_nav) if r.unit_nav is not None else None,
        }
        for r in ordered
    ]


async def count_etf_links(session: AsyncSession, symbol: str) -> int:
    sym = _sym(symbol)
    n = await session.scalar(
        select(func.count()).select_from(ExecutingEtfStockLink).where(
            ExecutingEtfStockLink.symbol == sym
        )
    )
    return int(n or 0)


async def build_payload_from_pg(
    session: AsyncSession,
    symbol: str,
    *,
    stock_amount_by_date: dict[str, float] | None = None,
) -> dict[str, Any]:
    sym = _sym(symbol)
    links = await load_etf_links(session, sym)
    share_by_etf: dict[str, list[dict[str, Any]]] = {}
    for lk in links:
        etf = lk["etf_ts_code"]
        share_by_etf[etf] = await load_etf_share_series(session, etf)
    return {
        "symbol": sym,
        "etf_links": links,
        "etf_share_series": share_by_etf,
        "stock_amount_by_date": stock_amount_by_date or {},
        "history_store": "executing_etf_stock_link+executing_etf_share_daily",
        "links_count": len(links),
    }


def save_etf_redis(redis_client: Any, symbol: str, payload: dict[str, Any]) -> None:
    if not redis_client:
        return
    key = ETF_REDIS_KEY.format(symbol=_sym(symbol))
    body = {**payload, "cached_at": shanghai_now_iso()}
    try:
        redis_client.setex(key, ETF_REDIS_TTL_SEC, json.dumps(body, ensure_ascii=False, default=str))
    except Exception:
        logger.exception("etf_redemption redis save failed symbol=%s", symbol)


def load_etf_redis(redis_client: Any, symbol: str) -> dict[str, Any] | None:
    if not redis_client:
        return None
    key = ETF_REDIS_KEY.format(symbol=_sym(symbol))
    try:
        raw = redis_client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def is_etf_backfill_done(redis_client: Any, symbol: str) -> bool:
    if not redis_client:
        return False
    try:
        return bool(redis_client.get(ETF_BACKFILL_KEY.format(symbol=_sym(symbol))))
    except Exception:
        return False


def mark_etf_backfill_done(redis_client: Any, symbol: str) -> None:
    if not redis_client:
        return
    try:
        redis_client.set(ETF_BACKFILL_KEY.format(symbol=_sym(symbol)), "1")
    except Exception:
        pass


def get_disc_cursor(redis_client: Any, symbol: str) -> int:
    if not redis_client:
        return 0
    try:
        v = redis_client.get(ETF_DISC_CURSOR_KEY.format(symbol=_sym(symbol)))
        return int(v or 0)
    except Exception:
        return 0


def set_disc_cursor(redis_client: Any, symbol: str, cursor: int) -> None:
    if not redis_client:
        return
    try:
        redis_client.set(ETF_DISC_CURSOR_KEY.format(symbol=_sym(symbol)), str(cursor))
    except Exception:
        pass


def save_etf_universe(redis_client: Any, codes: list[str]) -> None:
    if not redis_client:
        return
    try:
        redis_client.setex(
            ETF_UNIVERSE_REDIS_KEY,
            86400 * 7,
            json.dumps(codes, ensure_ascii=False),
        )
    except Exception:
        pass


def load_etf_universe(redis_client: Any) -> list[str] | None:
    if not redis_client:
        return None
    try:
        raw = redis_client.get(ETF_UNIVERSE_REDIS_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        return list(data) if isinstance(data, list) else None
    except Exception:
        return None


def trim_t0_payload_for_raw_store(payload: dict[str, Any]) -> dict[str, Any]:
    links = list(payload.get("etf_links") or [])
    series = payload.get("etf_share_series") or {}
    tail: dict[str, Any] = {}
    for etf, rows in series.items():
        tail[etf] = rows[-2:] if rows else []
    return {
        "links_count": payload.get("links_count", len(links)),
        "etf_links_top3": links[:3],
        "etf_share_tail": tail,
        "history_store": payload.get("history_store"),
    }
