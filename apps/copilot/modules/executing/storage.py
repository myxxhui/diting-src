"""T0 raw / probe_state / audit 落库。

[Ref: 28_ §4 §5]
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import utc_now_naive
from apps.copilot.db.models import (
    ExecutingDailyAudit,
    ExecutingDailyBar,
    ExecutingT0ProbeState,
    ExecutingT0Raw,
    ExecutingT0SyncWatermark,
)
from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow
from apps.copilot.modules.executing.profile import PROBE_KEYS, load_profile


def _sanitize_json_value(obj: Any) -> Any:
    """PostgreSQL JSONB 不接受 NaN/Inf；递归转为 null。"""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_value(v) for v in obj]
    return obj


async def replace_daily_bars(
    session: AsyncSession,
    symbol: str,
    rows: list[DailyBarRow],
    *,
    source: str,
) -> int:
    """全量刷新标的日线底库（幂等 · 采集一次/日更均用）。"""
    sym = symbol.zfill(6)[-6:]
    if not rows:
        return 0
    adjust = rows[0].adjust
    existing = (
        await session.scalars(
            select(ExecutingDailyBar).where(
                ExecutingDailyBar.symbol == sym,
                ExecutingDailyBar.adjust == adjust,
            )
        )
    ).all()
    for old in existing:
        await session.delete(old)
    now = utc_now_naive()
    for r in rows:
        session.add(
            ExecutingDailyBar(
                symbol=sym,
                trade_date=r.trade_date,
                adjust=r.adjust,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                source=source,
                collected_at=now,
            )
        )
    await session.flush()
    return len(rows)


async def upsert_daily_bars(
    session: AsyncSession,
    symbol: str,
    rows: list[DailyBarRow],
    *,
    source: str,
) -> int:
    """增量写入日线底库（按 symbol+trade_date+adjust 覆盖/插入，不删历史）。"""
    sym = symbol.zfill(6)[-6:]
    if not rows:
        return 0
    now = utc_now_naive()
    n = 0
    for r in rows:
        adjust = r.adjust
        existing = await session.get(
            ExecutingDailyBar,
            {"symbol": sym, "trade_date": r.trade_date, "adjust": adjust},
        )
        if existing is None:
            session.add(
                ExecutingDailyBar(
                    symbol=sym,
                    trade_date=r.trade_date,
                    adjust=adjust,
                    open=r.open,
                    high=r.high,
                    low=r.low,
                    close=r.close,
                    volume=r.volume,
                    source=source,
                    collected_at=now,
                )
            )
        else:
            existing.open = r.open
            existing.high = r.high
            existing.low = r.low
            existing.close = r.close
            existing.volume = r.volume
            existing.source = source
            existing.collected_at = now
        n += 1
    await session.flush()
    return n


async def load_daily_bars(
    session: AsyncSession,
    symbol: str,
    *,
    adjust: str = "qfq",
    limit: int = 250,
) -> list[DailyBarRow]:
    sym = symbol.zfill(6)[-6:]
    db_rows = (
        await session.scalars(
            select(ExecutingDailyBar)
            .where(
                ExecutingDailyBar.symbol == sym,
                ExecutingDailyBar.adjust == adjust,
            )
            .order_by(ExecutingDailyBar.trade_date.desc())
            .limit(limit)
        )
    ).all()
    if not db_rows:
        return []
    ordered = sorted(db_rows, key=lambda r: r.trade_date)
    return [
        DailyBarRow(
            trade_date=r.trade_date,
            open=float(r.open),
            high=float(r.high),
            low=float(r.low),
            close=float(r.close),
            volume=float(r.volume),
            adjust=r.adjust,
        )
        for r in ordered
    ]


async def save_t0_batch(
    session: AsyncSession,
    symbol: str,
    items: list[dict[str, Any]],
    *,
    trade_date: date | None = None,
) -> int:
    td = trade_date or date.today()
    n = 0
    prof = load_profile(symbol)
    probes_cfg = prof.get("probes") or {}
    now = utc_now_naive()

    for it in items:
        key = it["probe_key"]
        session.add(
            ExecutingT0Raw(
                symbol=symbol,
                probe_key=key,
                trade_date=td,
                payload_json=_sanitize_json_value(
                    {
                        "ok": bool(it.get("ok")),
                        "payload": it.get("payload"),
                        "blocker": it.get("blocker"),
                    }
                ),
                source=it.get("source"),
            )
        )
        n += 1
        cfg = probes_cfg.get(key) or {}
        stale_days = int(cfg.get("stale_days", 1))
        ps = await session.get(ExecutingT0ProbeState, {"symbol": symbol, "probe_key": key})
        if ps is None:
            ps = ExecutingT0ProbeState(symbol=symbol, probe_key=key)
            session.add(ps)
        ps.collected_at = now
        ps.as_of = td
        ps.stale_after = now + timedelta(days=stale_days)
        if it.get("ok"):
            ps.status = "ok"
            ps.blocker = None
        else:
            ps.status = "missing"
            ps.blocker = (it.get("blocker") or "")[:500]
    await session.flush()
    return n


async def latest_raw_map(session: AsyncSession, symbol: str) -> dict[str, dict[str, Any]]:
    """每 probe 取最新一条 raw。"""
    out: dict[str, dict[str, Any]] = {}
    for key in PROBE_KEYS:
        row = (
            await session.scalars(
                select(ExecutingT0Raw)
                .where(
                    ExecutingT0Raw.symbol == symbol,
                    ExecutingT0Raw.probe_key == key,
                )
                .order_by(ExecutingT0Raw.collected_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            continue
        payload = row.payload_json or {}
        if not payload.get("ok"):
            out[key] = {
                "ok": False,
                "blocker": payload.get("blocker"),
                "source": row.source or "",
            }
        else:
            out[key] = {
                "ok": True,
                "payload": payload.get("payload") or {},
                "source": row.source or "",
            }
    return out


async def upsert_watermark(
    session: AsyncSession,
    job_id: str,
    symbol: str = "*",
    *,
    success: bool,
    trade_date: date | None = None,
    row_count: int = 0,
    error: str | None = None,
) -> None:
    row = await session.get(ExecutingT0SyncWatermark, {"job_id": job_id, "symbol": symbol})
    if row is None:
        row = ExecutingT0SyncWatermark(job_id=job_id, symbol=symbol)
        session.add(row)
    if success:
        row.last_success_at = utc_now_naive()
        row.last_trade_date = trade_date
        row.last_row_count = row_count
        row.last_error = None
    else:
        row.last_error = (error or "unknown")[:500]


async def save_daily_audit(
    session: AsyncSession,
    symbol: str,
    trade_date: date,
    telemetry: dict[str, Any],
    audit: dict[str, Any],
    *,
    run_id: str | None,
    t2_status: str,
) -> ExecutingDailyAudit:
    row = ExecutingDailyAudit(
        symbol=symbol,
        trade_date=trade_date,
        telemetry_json=_sanitize_json_value(telemetry),
        audit_json=_sanitize_json_value(audit),
        run_id=run_id,
        t2_status=t2_status,
    )
    session.add(row)
    await session.flush()
    return row
