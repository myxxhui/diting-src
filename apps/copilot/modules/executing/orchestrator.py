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
from apps.copilot.modules.executing.collectors.daily_bars import (
    MIN_BARS_ACCEPT,
    LOOKBACK_TRADING_DAYS,
    SOURCE_TENCENT,
    fetch_tencent_daily_bars,
)
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
    SOURCE_INTRADAY,
    SOURCE_PG,
    compute_atr_trailing_payload,
)
from apps.copilot.modules.executing.positions import get_position_opened_at
from apps.copilot.modules.executing.collectors.intraday_draft import (
    clear_intraday_draft,
    compute_intraday_atr,
    fetch_today_draft_bar,
    load_draft_bar,
    overwrite_atr_intraday,
    overwrite_draft_bar,
)
from apps.copilot.modules.executing.storage import (
    load_daily_bars,
    replace_daily_bars,
    save_daily_audit,
    save_t0_batch,
    upsert_daily_bars,
    upsert_watermark,
)
from apps.copilot.modules.executing.t0_collectors import collect_all_t0
from apps.copilot.modules.executing.t1_assembler import assemble_batch_portfolio
from apps.copilot.modules.executing.t1_build import telemetry_probe_stats
from apps.copilot.modules.executing.t2_opus import run_t2_audit
from apps.copilot.modules.executing.universe import load_executing_collect_symbols

logger = logging.getLogger(__name__)


async def run_daily_bars_sync_all(session: AsyncSession) -> dict[str, Any]:
    """按 executing_collect_symbols 全量采集腾讯 250 日日线 → PG。"""
    from apps.copilot.modules.executing.universe import load_executing_collect_symbols

    symbols = await load_executing_collect_symbols(session)
    if not symbols:
        await upsert_watermark(
            session,
            "executing-bars250-bootstrap",
            "*",
            success=False,
            error="executing_collect_empty",
        )
        return {"status": "skip", "reason": "executing_collect_empty", "symbols": []}

    results: list[dict[str, Any]] = []
    for sym in symbols:
        results.append(await run_daily_bars_sync(session, sym))
    failed = [r for r in results if r.get("status") == "error"]
    await upsert_watermark(
        session,
        "executing-bars250-bootstrap",
        "*",
        success=not failed,
        trade_date=date.today(),
        row_count=sum(r.get("bars_count", 0) for r in results),
        error=failed[0].get("error") if failed else None,
    )
    return {
        "status": "error" if failed else "ok",
        "symbols_total": len(symbols),
        "ok_count": sum(1 for r in results if r.get("status") == "ok"),
        "failed_count": len(failed),
        "results": results,
    }


async def run_daily_bars_incremental_sync(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    """工作日 16:00：拉腾讯 250 日 · 增量 UPSERT PG（不删历史）· 清除 Redis 草稿。"""
    sym = symbol.zfill(6)[-6:]
    rows, source = fetch_tencent_daily_bars(sym, days=LOOKBACK_TRADING_DAYS)
    if len(rows) < MIN_BARS_ACCEPT:
        err = (
            f"腾讯 fqkline 不足 {MIN_BARS_ACCEPT} 根（got {len(rows)}）"
            f"·symbol={sym}"
        )
        await upsert_watermark(
            session, "l4-atr-bars-sync", sym, success=False, error=err
        )
        return {"symbol": sym, "status": "error", "error": err, "bars_count": len(rows)}

    n = await upsert_daily_bars(session, sym, rows, source=source)
    if redis_client is not None:
        clear_intraday_draft(redis_client, sym)

    entry = await get_position_opened_at(session, sym)
    atr_payload = compute_atr_trailing_payload(
        rows, entry_date=entry, source=f"{SOURCE_PG} · eod_incremental"
    )
    td = rows[-1].trade_date
    if atr_payload:
        await save_t0_batch(
            session,
            sym,
            [
                {
                    "probe_key": "qmt_atr_trailing",
                    "ok": True,
                    "payload": atr_payload,
                    "source": atr_payload.get("source", SOURCE_PG),
                }
            ],
            trade_date=td,
        )
        from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node
        from apps.copilot.modules.executing.storage import upsert_t1_snapshot

        try:
            atr_node = build_qmt_atr_trailing_node(
                {**atr_payload, "source": atr_payload.get("source", SOURCE_PG)}
            )
            await upsert_t1_snapshot(
                session,
                sym,
                "qmt_atr_trailing",
                atr_node,
                trade_date=td,
                source=atr_payload.get("source", SOURCE_PG),
            )
        except ValueError:
            pass
    await upsert_watermark(
        session,
        "l4-atr-bars-sync",
        sym,
        success=True,
        trade_date=td,
        row_count=n,
    )
    return {
        "symbol": sym,
        "status": "ok",
        "bars_count": n,
        "mode": "incremental_upsert",
        "source": SOURCE_TENCENT,
        "as_of": td.isoformat(),
        "atr_multiple": (atr_payload or {}).get("atr_multiple"),
    }


async def run_daily_bars_sync(session: AsyncSession, symbol: str) -> dict[str, Any]:
    """采集腾讯 fqkline 250 交易日日线并全量写入 PG（#15 底库 · bootstrap）。"""
    sym = symbol.zfill(6)[-6:]
    rows, source = fetch_tencent_daily_bars(sym, days=LOOKBACK_TRADING_DAYS)
    if len(rows) < MIN_BARS_ACCEPT:
        err = (
            f"腾讯 fqkline 不足 {MIN_BARS_ACCEPT} 根（got {len(rows)}）"
            f"·symbol={sym}"
        )
        await upsert_watermark(
            session, "l4-atr-bars-sync", sym, success=False, error=err
        )
        return {"symbol": sym, "status": "error", "error": err, "bars_count": len(rows)}

    n = await replace_daily_bars(session, sym, rows, source=source)
    entry = await get_position_opened_at(session, sym)
    atr_payload = compute_atr_trailing_payload(rows, entry_date=entry, source=SOURCE_PG)
    td = rows[-1].trade_date
    if atr_payload:
        await save_t0_batch(
            session,
            sym,
            [
                {
                    "probe_key": "qmt_atr_trailing",
                    "ok": True,
                    "payload": atr_payload,
                    "source": atr_payload.get("source", SOURCE_PG),
                }
            ],
            trade_date=td,
        )
        from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node
        from apps.copilot.modules.executing.storage import upsert_t1_snapshot

        try:
            atr_node = build_qmt_atr_trailing_node(
                {**atr_payload, "source": atr_payload.get("source", SOURCE_PG)}
            )
            await upsert_t1_snapshot(
                session,
                sym,
                "qmt_atr_trailing",
                atr_node,
                trade_date=td,
                source=atr_payload.get("source", SOURCE_PG),
            )
        except ValueError:
            pass
    await upsert_watermark(
        session,
        "l4-atr-bars-sync",
        sym,
        success=True,
        trade_date=td,
        row_count=n,
    )
    return {
        "symbol": sym,
        "status": "ok",
        "bars_count": n,
        "source": SOURCE_TENCENT,
        "as_of": td.isoformat(),
        "atr_multiple": (atr_payload or {}).get("atr_multiple"),
    }


async def run_t0_collect(session: AsyncSession, symbol: str) -> dict[str, Any]:
    sym = symbol.zfill(6)[-6:]
    daily_rows = await load_daily_bars(session, sym, limit=LOOKBACK_TRADING_DAYS)
    entry = await get_position_opened_at(session, sym)
    items = collect_all_t0(sym, daily_bar_rows=daily_rows or None, entry_date=entry)
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


async def run_batch_daily_pipeline(
    session: AsyncSession,
    symbols: list[str] | None = None,
    *,
    run_id: str | None = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """批量巡检：T0 逐标的 → T1 Scatter-Gather 整包 → T2 Opus 一次决断。"""
    syms = symbols or await load_executing_collect_symbols(session)
    if not syms:
        return {"status": "skip", "reason": "executing_collect_empty"}

    rid = run_id or str(uuid.uuid4())
    td = date.today()
    batch_id = f"batch_task_{td.strftime('%Y%m%d')}_{rid[:8]}"

    run_row = ExecutingPipelineRun(run_id=rid, symbol="*", status="running", stage="T0")
    session.add(run_row)
    await session.flush()

    for sym in syms:
        await run_t0_collect(session, sym)
    run_row.stage = "T1"
    await session.flush()

    telemetry = await assemble_batch_portfolio(
        session,
        syms,
        redis_client=redis_client,
        execution_id=batch_id,
    )
    probe_stats = telemetry_probe_stats(telemetry)

    run_row.stage = "T2"
    await session.flush()
    audit, t2_status = run_t2_audit(telemetry)
    await save_daily_audit(session, "*", td, telemetry, audit, run_id=rid, t2_status=t2_status)
    await upsert_watermark(
        session,
        "daily-pipeline",
        "*",
        success=t2_status != "error",
        trade_date=td,
        row_count=probe_stats["filled"],
    )

    run_row.status = "completed" if t2_status in ("ok", "pending") else "failed"
    run_row.stage = "DONE"
    run_row.progress_json = {
        "missing": probe_stats["missing"],
        "t2_status": t2_status,
        "data_integrity": probe_stats.get("data_integrity"),
        "total_stocks_checked": probe_stats.get("total_stocks_checked"),
        "system_status": probe_stats.get("system_status"),
    }
    await session.flush()
    return {
        "run_id": rid,
        "symbols": syms,
        "telemetry": telemetry,
        "audit": audit,
        "t2_status": t2_status,
    }


async def run_daily_pipeline(
    session: AsyncSession,
    symbol: str,
    *,
    run_id: str | None = None,
    redis_client: Any = None,
) -> dict[str, Any]:
    """单标的触发：内部走批量 JSON（portfolio_signals 仅 1 键）+ Scatter-Gather。"""
    sym = symbol.zfill(6)[-6:]
    rid = run_id or str(uuid.uuid4())
    td = date.today()
    batch_id = f"batch_task_{td.strftime('%Y%m%d')}_{rid[:8]}"

    run_row = ExecutingPipelineRun(run_id=rid, symbol=sym, status="running", stage="T0")
    session.add(run_row)
    await session.flush()

    await run_t0_collect(session, sym)
    run_row.stage = "T1"
    await session.flush()

    telemetry = await assemble_batch_portfolio(
        session,
        [sym],
        redis_client=redis_client,
        execution_id=batch_id,
    )
    probe_stats = telemetry_probe_stats(telemetry)

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
        row_count=probe_stats["filled"],
    )

    run_row.status = "completed" if t2_status in ("ok", "pending") else "failed"
    run_row.stage = "DONE"
    run_row.progress_json = {
        "missing": probe_stats["missing"],
        "t2_status": t2_status,
        "data_integrity": probe_stats.get("data_integrity"),
    }
    await session.flush()
    return {
        "run_id": rid,
        "symbol": sym,
        "telemetry": telemetry,
        "audit": audit,
        "t2_status": t2_status,
    }


async def quote_intraday_job(session: AsyncSession, symbol: str, redis_client: Any) -> dict[str, Any]:
    """盘中 */5：腾讯当日 fqkline 草稿 → Redis 覆盖写 · PG 历史 + 草稿算 ATR。"""
    import json

    from apps.copilot.db.datetime_util import shanghai_now_iso
    from apps.copilot.modules.executing.collectors.intraday_draft import QUOTE_KEY

    sym = symbol.zfill(6)[-6:]
    executed_at = shanghai_now_iso()
    draft = fetch_today_draft_bar(sym)
    if draft is None:
        logger.info(
            "[热数据] symbol=%s 北京时间=%s status=skip reason=no_today_draft",
            sym,
            executed_at,
        )
        return {
            "symbol": sym,
            "status": "skip",
            "reason": "no_today_draft",
            "executed_at": executed_at,
        }

    if redis_client is not None:
        overwrite_draft_bar(redis_client, sym, draft)
        redis_client.setex(
            QUOTE_KEY.format(symbol=sym),
            600,
            json.dumps(
                {
                    "close": draft.close,
                    "high": draft.high,
                    "low": draft.low,
                    "open": draft.open,
                    "trade_date": draft.trade_date.isoformat(),
                    "is_stale": False,
                    "mode": "intraday_overwrite",
                },
                ensure_ascii=False,
            ),
        )

    pg_rows = await load_daily_bars(session, sym, limit=LOOKBACK_TRADING_DAYS)
    entry = await get_position_opened_at(session, sym)
    atr_payload = compute_intraday_atr(
        pg_rows, draft, entry_date=entry, source=SOURCE_INTRADAY
    )
    if atr_payload and redis_client is not None:
        overwrite_atr_intraday(redis_client, sym, atr_payload)

    atr_mult = (atr_payload or {}).get("atr_multiple")
    logger.info(
        "[热数据] symbol=%s 北京时间=%s trade_date=%s high=%.4f low=%.4f close=%.4f "
        "atr_multiple=%s pg_bars=%d → Redis 覆盖写完成",
        sym,
        executed_at,
        draft.trade_date.isoformat(),
        draft.high,
        draft.low,
        draft.close,
        atr_mult,
        len(pg_rows),
    )
    return {
        "symbol": sym,
        "status": "ok",
        "executed_at": executed_at,
        "draft": {
            "trade_date": draft.trade_date.isoformat(),
            "high": draft.high,
            "low": draft.low,
            "close": draft.close,
        },
        "atr_multiple": atr_mult,
        "pg_bars": len(pg_rows),
    }


async def vol_div_15m_job(
    session: AsyncSession,
    symbol: str,
    redis_client: Any,
) -> dict[str, Any]:
    """#16 盘中 */15：东财 15min K 线 → Redis + T0 落库。"""
    from apps.copilot.db.datetime_util import shanghai_now_iso
    from apps.copilot.modules.executing.collectors.bars_15m import (
        bars_to_payload,
        fetch_bars_15m_em,
        save_bars_15m_redis,
    )
    from apps.copilot.modules.executing.t1_operators.volume_price_div import (
        process_volume_price_div,
    )

    sym = symbol.zfill(6)[-6:]
    executed_at = shanghai_now_iso()
    bars, source = fetch_bars_15m_em(sym)
    if not bars:
        logger.warning(
            "[15m] symbol=%s 北京时间=%s status=error reason=fetch_failed",
            sym,
            executed_at,
        )
        return {
            "symbol": sym,
            "status": "error",
            "reason": "fetch_failed_or_insufficient_bars",
            "executed_at": executed_at,
        }

    payload = bars_to_payload(sym, bars, source=source)
    t1_payload: dict[str, Any] | None = None
    try:
        t1_payload = process_volume_price_div(bars, source=source)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[15m] T1 预计算失败 symbol=%s: %s", sym, exc)

    if redis_client is not None:
        save_bars_15m_redis(redis_client, sym, payload)

    from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node
    from apps.copilot.modules.executing.storage import upsert_t1_snapshot

    await save_t0_batch(
        session,
        sym,
        [
            {
                "probe_key": "volume_price_div",
                "ok": True,
                "payload": {
                    "bars_payload": payload,
                    "bars_meta": {
                        "bars_count": len(bars),
                        "first_datetime": bars[0].datetime,
                        "last_datetime": bars[-1].datetime,
                        "source": source,
                    },
                    "t1_preview": t1_payload,
                },
                "source": source,
            }
        ],
        trade_date=date.today(),
    )
    if t1_payload:
        node = build_volume_price_div_node(t1_payload)
        await upsert_t1_snapshot(
            session, sym, "volume_price_div", node, trade_date=date.today(), source=source
        )

    logger.info(
        "[15m] symbol=%s 北京时间=%s bars=%d last=%s → Redis OK",
        sym,
        executed_at,
        len(bars),
        bars[-1].datetime,
    )
    return {
        "symbol": sym,
        "status": "ok",
        "executed_at": executed_at,
        "bars_count": len(bars),
        "last_datetime": bars[-1].datetime,
        "source": source,
        "divergence_index": (t1_payload or {}).get("value"),
    }


async def run_smart_money_sync_symbol(
    session: AsyncSession,
    symbol: str,
    redis_client: Any,
    *,
    mode: str = "incremental",
) -> dict[str, Any]:
    """#17 单标的：Tushare → PG 250 底库 + Redis + T0 摘要 + T1 快照。"""
    from apps.copilot.modules.executing.indicator_nodes import build_smart_money_flow_node
    from apps.copilot.modules.executing.moneyflow_storage import MONEYFLOW_TARGET_TRADING_DAYS
    from apps.copilot.modules.executing.smart_money_flow import (
        SOURCE_TUSHARE,
        compute_smart_money_metrics,
        sync_smart_money_symbol,
        tushare_token,
    )
    from apps.copilot.modules.executing.storage import save_t0_batch, upsert_t1_snapshot

    sym = symbol.zfill(6)[-6:]
    if not tushare_token():
        return {"symbol": sym, "status": "error", "error": "TUSHARE_TOKEN 未配置"}

    try:
        result = await sync_smart_money_symbol(
            session, sym, redis_client=redis_client, mode=mode
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[smart-money] sync 失败 symbol=%s: %s", sym, exc)
        return {"symbol": sym, "status": "error", "error": str(exc)[:200]}

    payload = result.get("payload") or {}
    rows_n = len(payload.get("moneyflow_rows") or [])
    ok = rows_n >= 3 and bool(payload.get("free_float_shares"))
    t0_item = {
        "probe_key": "smart_money_flow",
        "ok": ok,
        "payload": result.get("t0_summary") or {},
        "source": SOURCE_TUSHARE,
    }
    if not ok:
        t0_item["blocker"] = (
            f"moneyflow PG 行数={result.get('pg_count')} free_float="
            f"{payload.get('free_float_shares')}"
        )[:200]
    await save_t0_batch(session, sym, [t0_item], trade_date=date.today())

    t1_value = None
    if ok:
        metrics = compute_smart_money_metrics(payload)
        node = build_smart_money_flow_node(metrics, source=SOURCE_TUSHARE)
        await upsert_t1_snapshot(
            session, sym, "smart_money_flow", node, trade_date=date.today(), source=SOURCE_TUSHARE
        )
        t1_value = node.get("value")

    return {
        **result,
        "symbol": sym,
        "status": "ok" if ok else "error",
        "t1_value": t1_value,
        "target_trading_days": MONEYFLOW_TARGET_TRADING_DAYS,
    }


async def run_smart_money_backfill_check(
    session: AsyncSession,
    symbols: list[str],
    redis_client: Any,
) -> dict[str, Any]:
    """14:00 · 检查执行区全标的是否满 250 交易日，不足则 full 回填。"""
    from apps.copilot.modules.executing.moneyflow_storage import (
        MONEYFLOW_TARGET_TRADING_DAYS,
        count_moneyflow_rows,
    )

    results: list[dict[str, Any]] = []
    for sym in symbols:
        n = await count_moneyflow_rows(session, sym.zfill(6)[-6:])
        if n < MONEYFLOW_TARGET_TRADING_DAYS:
            results.append(
                await run_smart_money_sync_symbol(
                    session, sym, redis_client, mode="full"
                )
            )
        else:
            results.append(
                {"symbol": sym.zfill(6)[-6:], "status": "skip", "pg_count": n, "reason": "already_full"}
            )
    ok = [r for r in results if r.get("status") == "ok"]
    await upsert_watermark(
        session,
        "l4-smart-money-backfill",
        "*",
        success=bool(ok) or all(r.get("status") == "skip" for r in results),
        trade_date=date.today(),
        row_count=sum(r.get("pg_count", 0) or r.get("upserted", 0) for r in results),
    )
    return {"job_id": "l4-smart-money-backfill", "status": "ok", "results": results}


async def run_smart_money_eod(
    session: AsyncSession,
    symbols: list[str],
    redis_client: Any,
) -> dict[str, Any]:
    """17:00 · 全执行区标的增量日更 + T1 快照。"""
    results = []
    for sym in symbols:
        results.append(
            await run_smart_money_sync_symbol(
                session, sym, redis_client, mode="incremental"
            )
        )
    ok = [r for r in results if r.get("status") == "ok"]
    await upsert_watermark(
        session,
        "l4-smart-money-eod",
        "*",
        success=bool(ok),
        trade_date=date.today(),
        row_count=len(ok),
        error=None if ok else "smart_money_eod_failed",
    )
    return {"job_id": "l4-smart-money-eod", "status": "ok" if ok else "error", "results": results}


async def run_level2_super_order_sync_symbol(
    session: AsyncSession,
    symbol: str,
    redis_client: Any,
    *,
    mode: str = "incremental",
) -> dict[str, Any]:
    """#18 单标的：Tushare elg_amount → PG + T0 摘要 + T1 分位快照。"""
    from apps.copilot.modules.executing.indicator_nodes import build_level2_super_order_node
    from apps.copilot.modules.executing.level2_super_order import (
        SOURCE_ELG,
        SUPER_ORDER_MIN_TRADING_DAYS,
        compute_level2_super_order_metrics,
        sync_level2_super_order_symbol,
    )
    from apps.copilot.modules.executing.smart_money_flow import tushare_token
    from apps.copilot.modules.executing.storage import save_t0_batch, upsert_t1_snapshot

    sym = symbol.zfill(6)[-6:]
    if not tushare_token():
        return {"symbol": sym, "status": "error", "error": "TUSHARE_TOKEN 未配置"}

    try:
        result = await sync_level2_super_order_symbol(
            session, sym, redis_client=redis_client, mode=mode
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[level2-super-order] sync 失败 symbol=%s: %s", sym, exc)
        return {"symbol": sym, "status": "error", "error": str(exc)[:200]}

    payload = result.get("payload")
    pg_count = int(result.get("pg_count") or 0)
    ok = payload is not None and pg_count >= SUPER_ORDER_MIN_TRADING_DAYS
    t0_item = {
        "probe_key": "level2_super_order",
        "ok": ok,
        "payload": result.get("t0_summary") or {},
        "source": SOURCE_ELG,
    }
    if not ok:
        t0_item["blocker"] = (
            f"elg PG 行数={pg_count} 或 elg_amount 未回填"
        )[:200]
    await save_t0_batch(session, sym, [t0_item], trade_date=date.today())

    t1_value = None
    if ok and payload:
        metrics = compute_level2_super_order_metrics(payload)
        node = build_level2_super_order_node(metrics, source=SOURCE_ELG)
        await upsert_t1_snapshot(
            session, sym, "level2_super_order", node, trade_date=date.today(), source=SOURCE_ELG
        )
        t1_value = node.get("value")

    return {
        **result,
        "symbol": sym,
        "status": "ok" if ok else "error",
        "t1_value": t1_value,
        "target_trading_days": SUPER_ORDER_MIN_TRADING_DAYS,
    }


async def run_level2_super_order_backfill_check(
    session: AsyncSession,
    symbols: list[str],
    redis_client: Any,
) -> dict[str, Any]:
    """14:00 · 检查全标的 PG 是否满 120 交易日且 elg 金额已回填。"""
    from apps.copilot.modules.executing.level2_super_order import (
        SUPER_ORDER_MIN_TRADING_DAYS,
        load_level2_super_order_payload,
    )
    from apps.copilot.modules.executing.moneyflow_storage import count_moneyflow_rows

    results: list[dict[str, Any]] = []
    for sym in symbols:
        code = sym.zfill(6)[-6:]
        n = await count_moneyflow_rows(session, code)
        payload = await load_level2_super_order_payload(session, code)
        if n < SUPER_ORDER_MIN_TRADING_DAYS or payload is None:
            results.append(
                await run_level2_super_order_sync_symbol(
                    session, sym, redis_client, mode="full"
                )
            )
        else:
            results.append(
                {"symbol": code, "status": "skip", "pg_count": n, "reason": "already_full"}
            )
    ok = [r for r in results if r.get("status") == "ok"]
    await upsert_watermark(
        session,
        "l2-super-order-backfill",
        "*",
        success=bool(ok) or all(r.get("status") == "skip" for r in results),
        trade_date=date.today(),
        row_count=sum(r.get("pg_count", 0) or r.get("upserted", 0) for r in results),
    )
    return {"job_id": "l2-super-order-backfill", "status": "ok", "results": results}


async def run_level2_super_order_eod(
    session: AsyncSession,
    symbols: list[str],
    redis_client: Any,
) -> dict[str, Any]:
    """17:00 · 全执行区标的 elg 增量日更 + T1 分位快照。"""
    results = []
    for sym in symbols:
        results.append(
            await run_level2_super_order_sync_symbol(
                session, sym, redis_client, mode="incremental"
            )
        )
    ok = [r for r in results if r.get("status") == "ok"]
    await upsert_watermark(
        session,
        "l2-super-order-eod",
        "*",
        success=bool(ok),
        trade_date=date.today(),
        row_count=len(ok),
        error=None if ok else "level2_super_order_eod_failed",
    )
    return {"job_id": "l2-super-order-eod", "status": "ok" if ok else "error", "results": results}


async def run_margin_skew_sync_symbol(
    session: AsyncSession,
    symbol: str,
    redis_client: Any,
    *,
    mode: str = "incremental",
) -> dict[str, Any]:
    """#19 单标的：Tushare margin_detail → PG + T0 摘要 + T1 分位快照。"""
    from apps.copilot.modules.executing.indicator_nodes import build_margin_short_skew_node
    from apps.copilot.modules.executing.margin_short_skew import (
        SOURCE_MARGIN,
        compute_margin_short_skew_metrics,
        sync_margin_skew_symbol,
    )
    from apps.copilot.modules.executing.margin_storage import MARGIN_MIN_TRADING_DAYS
    from apps.copilot.modules.executing.smart_money_flow import tushare_token
    from apps.copilot.modules.executing.storage import save_t0_batch, upsert_t1_snapshot

    sym = symbol.zfill(6)[-6:]
    if not tushare_token():
        return {"symbol": sym, "status": "error", "error": "TUSHARE_TOKEN 未配置"}

    try:
        result = await sync_margin_skew_symbol(
            session, sym, redis_client=redis_client, mode=mode
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[margin-skew] sync 失败 symbol=%s: %s", sym, exc)
        return {"symbol": sym, "status": "error", "error": str(exc)[:200]}

    payload = result.get("payload")
    pg_count = int(result.get("pg_count") or 0)
    valid_rows = [
        r for r in (payload or {}).get("margin_rows") or []
        if r.get("margin_to_float_ratio") is not None
    ]
    ok = len(valid_rows) >= MARGIN_MIN_TRADING_DAYS
    t0_item = {
        "probe_key": "margin_short_skew",
        "ok": ok,
        "payload": result.get("t0_summary") or {},
        "source": SOURCE_MARGIN,
    }
    if not ok:
        t0_item["blocker"] = (
            f"两融 PG 行数={pg_count} 或 margin_to_float_ratio 有效行={len(valid_rows)}"
        )[:200]
    await save_t0_batch(session, sym, [t0_item], trade_date=date.today())

    t1_value = None
    if ok and payload:
        metrics = compute_margin_short_skew_metrics(payload)
        node = build_margin_short_skew_node(metrics, source=SOURCE_MARGIN)
        await upsert_t1_snapshot(
            session, sym, "margin_short_skew", node, trade_date=date.today(), source=SOURCE_MARGIN
        )
        t1_value = node.get("value")

    return {
        **result,
        "symbol": sym,
        "status": "ok" if ok else "error",
        "t1_value": t1_value,
        "target_trading_days": MARGIN_MIN_TRADING_DAYS,
    }


async def run_margin_skew_morning(
    session: AsyncSession,
    symbols: list[str],
    redis_client: Any,
) -> dict[str, Any]:
    """08:30 周二至周六 · T+1 两融增量/250日回填 + T1 快照。"""
    from apps.copilot.modules.executing.margin_storage import MARGIN_TARGET_TRADING_DAYS, count_margin_rows

    results: list[dict[str, Any]] = []
    for sym in symbols:
        code = sym.zfill(6)[-6:]
        n = await count_margin_rows(session, code)
        mode = "full" if n < MARGIN_TARGET_TRADING_DAYS else "incremental"
        results.append(
            await run_margin_skew_sync_symbol(session, sym, redis_client, mode=mode)
        )
    ok = [r for r in results if r.get("status") == "ok"]
    await upsert_watermark(
        session,
        "l4-margin-skew-morning",
        "*",
        success=bool(ok),
        trade_date=date.today(),
        row_count=len(ok),
        error=None if ok else "margin_skew_morning_failed",
    )
    return {"job_id": "l4-margin-skew-morning", "status": "ok" if ok else "error", "results": results}
