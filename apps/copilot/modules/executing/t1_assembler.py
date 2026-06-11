"""T1 Scatter-Gather 装配车间 · 批量 portfolio_signals。

[Ref: 28_ §4.1 · §4.2 · probe_registry]
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.positions import profit_context
from apps.copilot.modules.executing.storage import (
    latest_raw_map,
    load_all_t1_snapshots,
    persist_indicator_snapshots,
)
from apps.copilot.modules.executing.t1_build import (
    _degraded_line,
    _position_context_batch,
    _symbol_exchange,
)
from apps.copilot.modules.executing.money_unit import attach_money_unit, round_price
from apps.copilot.modules.executing.workspace_settings import get_workspace_settings
from apps.copilot.modules.executing.profile import PROBE_KEYS, load_profile, profile_l3_keys
from apps.copilot.modules.executing.probe_registry import (
    OPTIONAL_SILENT_PROBE_KEYS,
    collect_t1_live_for_key,
)
from apps.copilot.modules.executing.l3_probe_registry import L3_PROBE_REGISTRY, collect_t1_live_l3_for_key
from apps.copilot.modules.executing.probes._base import T1LiveContext

logger = logging.getLogger(__name__)

T1_OPERATOR_TIMEOUT_SEC = float(os.environ.get("EXECUTING_T1_OPERATOR_TIMEOUT_SEC", "10"))


async def _gather_stock_indicators(
    session: AsyncSession,
    symbol: str,
    *,
    raw_by_key: dict[str, dict[str, Any]],
    entry_date: date | None,
    redis_client: Any,
    timeout_sec: float,
) -> tuple[dict[str, Any], list[str]]:
    """Scatter-Gather：registry 并发算子 + 绝对超时。"""
    degraded: list[str] = []
    sym = symbol.zfill(6)[-6:]
    prof = load_profile(sym)
    l3_keys = tuple(k for k in profile_l3_keys(prof) if k in L3_PROBE_REGISTRY)
    ctx = T1LiveContext(
        session=session,
        symbol=sym,
        raw_by_key=raw_by_key,
        entry_date=entry_date,
        redis_client=redis_client,
    )

    async def _wrap_l4(probe_key: str):
        return await collect_t1_live_for_key(probe_key, ctx)

    async def _wrap_l3(probe_key: str):
        return await collect_t1_live_l3_for_key(probe_key, ctx)

    tasks = [(probe_key, _wrap_l3(probe_key)) for probe_key in l3_keys]
    tasks += [(probe_key, _wrap_l4(probe_key)) for probe_key in PROBE_KEYS]

    async def _run_all() -> list[Any]:
        coros = [t[1] for t in tasks]
        return await asyncio.gather(*coros, return_exceptions=True)

    try:
        results = await asyncio.wait_for(_run_all(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        degraded.append(f"{sym}: T1 装配超时（>{timeout_sec}s）")
        results = []

    indicators: dict[str, Any] = {}
    task_keys = [t[0] for t in tasks]
    for i, result in enumerate(results):
        key = task_keys[i] if i < len(task_keys) else f"task_{i}"
        if isinstance(result, Exception):
            degraded.append(f"{key} ({type(result).__name__}: {result})")
            logger.warning("[%s] T1 算子失败 %s: %s", sym, key, result)
            continue
        if result is None:
            continue
        ind_key, node = result
        indicators[ind_key] = node

    for probe_key in (*l3_keys, *PROBE_KEYS):
        if probe_key not in indicators and probe_key not in OPTIONAL_SILENT_PROBE_KEYS:
            degraded.append(_degraded_line(probe_key, raw_by_key.get(probe_key)))

    return indicators, degraded

async def load_cached_stock_signal(
    session: AsyncSession,
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any]:
    """单标的 · 优先 PG 快照（执行区卡片秒开，不触发 Scatter-Gather live 算子）。"""
    sym = symbol.zfill(6)[-6:]
    pc = await profit_context(session, sym, redis_client)
    indicators = await load_all_t1_snapshots(session, sym)
    signal: dict[str, Any] = {
        "stock_name": pc.get("name") or sym,
        "indicators": indicators,
        "cache_only": True,
    }
    pos = _position_context_batch(pc)
    if pos:
        signal["position_context"] = pos
    if not indicators:
        signal["degraded_probes"] = [f"{sym}: PG 尚无 T1 快照 · 点「立即跑今日体检」或等待 Cron"]
    return signal


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
