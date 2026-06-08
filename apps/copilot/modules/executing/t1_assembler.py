"""T1 Scatter-Gather 装配车间 · 批量 portfolio_signals。

[Ref: 28_ §4.1 · §4.2]
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.collectors.daily_bars import LOOKBACK_TRADING_DAYS
from apps.copilot.modules.executing.collectors.intraday_draft import (
    compute_intraday_atr,
    load_draft_bar,
    load_draft_bar_dict,
    merge_pg_rows_with_draft,
)
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import SOURCE_PG
from apps.copilot.modules.executing.positions import profit_context
from apps.copilot.modules.executing.storage import (
    latest_raw_map,
    load_daily_bars,
    load_t1_snapshot,
    persist_indicator_snapshots,
)
from apps.copilot.modules.executing.t1_build import (
    _degraded_line,
    _position_context_batch,
    _probe_node_from_raw,
    _symbol_exchange,
)
from apps.copilot.modules.executing.money_unit import attach_money_unit, round_price
from apps.copilot.modules.executing.workspace_settings import get_workspace_settings
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
    AtrTrailingError,
    process_qmt_atr_trailing_from_rows,
)

logger = logging.getLogger(__name__)

T1_OPERATOR_TIMEOUT_SEC = float(os.environ.get("EXECUTING_T1_OPERATOR_TIMEOUT_SEC", "10"))

OperatorResult = tuple[str, dict[str, Any]]


async def _calc_qmt_atr_trailing_live(
    session: AsyncSession,
    symbol: str,
    *,
    entry_date: date | None,
    redis_client: Any,
) -> OperatorResult:
    """#15 实盘算子：PG 底库 + Redis 盘中草稿 → T1 五步法。"""
    sym = symbol.zfill(6)[-6:]
    pg_rows = await load_daily_bars(session, sym, limit=LOOKBACK_TRADING_DAYS)
    draft = load_draft_bar(redis_client, sym) if redis_client else None
    if draft is not None:
        merged = merge_pg_rows_with_draft(pg_rows, draft)
        payload = process_qmt_atr_trailing_from_rows(
            merged,
            entry_date,
            source=SOURCE_PG,
        )
        payload["intraday"] = True
        draft_meta = load_draft_bar_dict(redis_client, sym) if redis_client else None
        if draft_meta and draft_meta.get("collected_at"):
            payload["last_tick_time"] = draft_meta["collected_at"]
    elif pg_rows:
        payload = process_qmt_atr_trailing_from_rows(
            pg_rows,
            entry_date,
            source=SOURCE_PG,
        )
    else:
        snap = await load_t1_snapshot(session, sym, "qmt_atr_trailing")
        if snap:
            return "qmt_atr_trailing", snap
        raise AtrTrailingError(f"无 PG 底库且无 Redis 草稿 symbol={sym}")

    from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node

    node = build_qmt_atr_trailing_node(payload)
    return "qmt_atr_trailing", node


async def _calc_volume_price_div_live(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any,
    raw_by_key: dict[str, dict[str, Any]],
) -> OperatorResult:
    """#16：Redis 15m 优先 → PG T1 快照 / bars_payload 回放。"""
    from apps.copilot.modules.executing.collectors.bars_15m import load_bars_15m_redis
    from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node
    from apps.copilot.modules.executing.t1_operators.volume_price_div import (
        VolumePriceDivError,
        process_volume_price_div_from_redis,
    )

    sym = symbol.zfill(6)[-6:]
    cached = load_bars_15m_redis(redis_client, sym) if redis_client else None
    bars_payload: dict[str, Any] | None = cached
    if bars_payload is None:
        raw = raw_by_key.get("volume_price_div") or {}
        inner = raw.get("payload") or {}
        bars_payload = inner.get("bars_payload")

    if bars_payload:
        payload = process_volume_price_div_from_redis(bars_payload)
        node = build_volume_price_div_node(payload)
        return "volume_price_div", node

    snap = await load_t1_snapshot(session, sym, "volume_price_div")
    if snap:
        return "volume_price_div", snap

    raw = raw_by_key.get("volume_price_div") or {}
    preview = (raw.get("payload") or {}).get("t1_preview")
    if preview and preview.get("value") is not None:
        node = build_volume_price_div_node(
            {**preview, "source": raw.get("source") or preview.get("source") or ""}
        )
        return "volume_price_div", node

    raise VolumePriceDivError("Redis 15m 缓存缺失且 PG 无 bars_payload / T1 快照")


async def _calc_smart_money_flow(
    session: AsyncSession,
    symbol: str,
    *,
    raw_by_key: dict[str, dict[str, Any]],
) -> OperatorResult:
    """#17：T0 raw → T1；失败时读 PG T1 快照。"""
    sym = symbol.zfill(6)[-6:]
    raw = raw_by_key.get("smart_money_flow")
    node = _probe_node_from_raw("smart_money_flow", raw)
    if node is not None:
        return "smart_money_flow", node

    snap = await load_t1_snapshot(session, sym, "smart_money_flow")
    if snap:
        return "smart_money_flow", snap

    blocker = raw.get("blocker") if raw else "smart_money_flow 未采集"
    raise ValueError(blocker)


async def _gather_stock_indicators(
    session: AsyncSession,
    symbol: str,
    *,
    raw_by_key: dict[str, dict[str, Any]],
    entry_date: date | None,
    redis_client: Any,
    timeout_sec: float,
) -> tuple[dict[str, Any], list[str]]:
    """Scatter-Gather：并发算子 + 绝对超时。"""
    degraded: list[str] = []

    tasks: list[tuple[str, Awaitable[Any]]] = []

    async def _wrap_for_key(probe_key: str) -> OperatorResult:
        if probe_key == "qmt_atr_trailing":
            return await _calc_qmt_atr_trailing_live(
                session, symbol, entry_date=entry_date, redis_client=redis_client
            )
        if probe_key == "volume_price_div":
            return await _calc_volume_price_div_live(
                session, symbol, redis_client=redis_client, raw_by_key=raw_by_key
            )
        if probe_key == "smart_money_flow":
            return await _calc_smart_money_flow(session, symbol, raw_by_key=raw_by_key)
        raise ValueError(f"未实现的 live 算子: {probe_key}")

    for probe_key in PROBE_KEYS:
        tasks.append((probe_key, _wrap_for_key(probe_key)))

    async def _run_all() -> list[Any]:
        coros = [t[1] for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=True)

    try:
        results = await asyncio.wait_for(_run_all(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        degraded.append(f"{symbol}: T1 装配超时（>{timeout_sec}s）")
        results = []

    indicators: dict[str, Any] = {}
    task_keys = [t[0] for t in tasks]
    for i, result in enumerate(results):
        key = task_keys[i] if i < len(task_keys) else f"task_{i}"
        if isinstance(result, Exception):
            degraded.append(f"{key} ({type(result).__name__}: {result})")
            logger.warning("[%s] T1 算子失败 %s: %s", symbol, key, result)
            continue
        if result is None:
            continue
        ind_key, node = result
        indicators[ind_key] = node

    for probe_key in PROBE_KEYS:
        if probe_key not in indicators:
            degraded.append(_degraded_line(probe_key, raw_by_key.get(probe_key)))

    return indicators, degraded


async def assemble_stock_signal(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """单标的 portfolio_signals 条目。"""
    sym = symbol.zfill(6)[-6:]
    pc = await profit_context(session, sym, redis_client)
    raw_map = await latest_raw_map(session, sym)
    entry = None
    if pc.get("opened_at"):
        entry = date.fromisoformat(str(pc["opened_at"])[:10])

    indicators, degraded = await _gather_stock_indicators(
        session,
        sym,
        raw_by_key=raw_map,
        entry_date=entry,
        redis_client=redis_client,
        timeout_sec=timeout_sec or T1_OPERATOR_TIMEOUT_SEC,
    )
    await persist_indicator_snapshots(session, sym, indicators)

    signal: dict[str, Any] = {
        "stock_name": pc.get("name") or sym,
        "indicators": indicators,
    }
    pos = _position_context_batch(pc)
    if pos:
        signal["position_context"] = pos
    if degraded:
        signal["degraded_probes"] = degraded
    return signal


async def assemble_batch_portfolio(
    session: AsyncSession,
    symbols: list[str],
    *,
    redis_client: Any = None,
    execution_id: str | None = None,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """批量巡检 T1 ➔ T2 终极 JSON。"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_id = execution_id or f"batch_task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    portfolio: dict[str, Any] = {}
    any_degraded = False
    for sym in symbols:
        code = _symbol_exchange(sym)
        try:
            portfolio[code] = await assemble_stock_signal(
                session,
                sym,
                redis_client=redis_client,
                timeout_sec=timeout_sec,
            )
            if portfolio[code].get("degraded_probes"):
                any_degraded = True
        except Exception as exc:
            logger.exception("装配标的失败 symbol=%s", sym)
            any_degraded = True
            portfolio[code] = {
                "stock_name": sym,
                "indicators": {},
                "degraded_probes": [f"assemble_failed ({exc})"],
            }

    ws = await get_workspace_settings(session)
    batch_meta: dict[str, Any] = {
        "execution_id": batch_id,
        "timestamp": ts,
        "total_stocks_checked": len(symbols),
        "system_status": "Degraded" if any_degraded else "Nominal",
    }
    if ws.get("available_cash") is not None:
        batch_meta["account_available_cash"] = round_price(ws["available_cash"])

    return {
        "batch_meta": attach_money_unit(batch_meta),
        "portfolio_signals": portfolio,
    }
