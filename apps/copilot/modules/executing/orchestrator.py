"""T0→T1→T2 编排。

[Ref: 28_ §5]
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ExecutingPipelineRun
from apps.copilot.modules.executing.positions import profit_context
from apps.copilot.modules.executing.storage import (
    latest_raw_map,
    save_daily_audit,
    save_t0_batch,
    upsert_watermark,
)
from apps.copilot.modules.executing.t0_collectors import collect_all_t0
from apps.copilot.modules.executing.t1_build import build_telemetry
from apps.copilot.modules.executing.t2_opus import run_t2_audit

logger = logging.getLogger(__name__)


async def run_t0_collect(session: AsyncSession, symbol: str) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    items = collect_all_t0(sym)
    n = await save_t0_batch(session, sym, items)
    await upsert_watermark(
        session,
        "collect-once",
        sym,
        success=True,
        trade_date=date.today(),
        row_count=n,
    )
    ok_keys = [i["probe_key"] for i in items if i.get("ok")]
    return {"symbol": sym, "collected": n, "ok_count": len(ok_keys), "total": len(items)}


async def run_daily_pipeline(
    session: AsyncSession,
    symbol: str,
    *,
    run_id: str | None = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    rid = run_id or str(uuid.uuid4())
    td = date.today()

    run_row = ExecutingPipelineRun(run_id=rid, symbol=sym, status="running", stage="T0")
    session.add(run_row)
    await session.flush()

    await run_t0_collect(session, sym)
    run_row.stage = "T1"
    await session.flush()

    raw_map = await latest_raw_map(session, sym)
    pc = await profit_context(session, sym, redis_client)
    telemetry = build_telemetry(sym, as_of=td, raw_by_key=raw_map, profit_context=pc)

    run_row.stage = "T2"
    await session.flush()
    audit, t2_status = run_t2_audit(telemetry)
    await save_daily_audit(session, sym, td, telemetry, audit, run_id=rid, t2_status=t2_status)
    await upsert_watermark(
        session,
        "daily-pipeline",
        sym,
        success=t2_status != "error",
        trade_date=td,
        row_count=len(telemetry.get("unavailable_data", [])),
    )

    run_row.status = "completed" if t2_status in ("ok", "pending") else "failed"
    run_row.stage = "DONE"
    run_row.progress_json = {
        "missing": telemetry.get("unavailable_data", []),
        "t2_status": t2_status,
    }
    await session.flush()
    return {
        "run_id": rid,
        "symbol": sym,
        "telemetry": telemetry,
        "audit": audit,
        "t2_status": t2_status,
    }


async def quote_intraday_job(session: AsyncSession, symbol: str, redis_client: Any) -> None:
    from apps.copilot.modules.executing.positions import fetch_mark_price
    import json

    price, stale = fetch_mark_price(symbol, redis_client)
    if price and redis_client is not None:
        redis_client.setex(
            f"executing:quote:{symbol.zfill(6)[-6:]}",
            600,
            json.dumps({"close": price, "is_stale": stale}),
        )
