"""Pod 启动时从 PG 回填 Executing 探针 Redis 热缓存（Redis 空盘可自愈）。

[Ref: 28_ §4.2 · executing_t1_probe_snapshots + 各 probe PG 底库]
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.universe import load_executing_collect_symbols

logger = logging.getLogger(__name__)

LoaderFn = Callable[..., Awaitable[Any]]

# T0 管道：load_*_payload 在 Redis miss 时读 PG 并写回 Redis
_WARMUP_LOADERS: tuple[str, ...] = (
    "apps.copilot.modules.executing.smart_money_flow:load_smart_money_payload",
    "apps.copilot.modules.executing.level2_super_order:load_level2_super_order_payload",
    "apps.copilot.modules.executing.margin_short_skew:load_margin_skew_payload",
    "apps.copilot.modules.executing.turnover_acceleration:load_turnover_acceleration_payload",
    "apps.copilot.modules.executing.tech_beta_correlation:load_tech_beta_correlation_payload",
    "apps.copilot.modules.executing.block_trade_discount:load_block_trade_payload",
    "apps.copilot.modules.executing.retail_concentration:load_retail_concentration_payload",
    "apps.copilot.modules.executing.insider_sell_actual:load_insider_sell_payload",
    "apps.copilot.modules.executing.etf_redemption_impact:load_etf_redemption_payload",
)


def _import_loader(dotted: str) -> LoaderFn:
    mod_name, fn_name = dotted.rsplit(":", 1)
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, fn_name)


async def _call_loader(
    loader: LoaderFn,
    session: AsyncSession,
    symbol: str,
    redis_client: Any,
) -> Any:
    kwargs: dict[str, Any] = {"session": session, "symbol": symbol}
    if "redis_client" in inspect.signature(loader).parameters:
        kwargs["redis_client"] = redis_client
    return await loader(**kwargs)


async def warm_executing_redis_from_pg(
    session: AsyncSession,
    redis_client: Any,
    *,
    symbols: list[str] | None = None,
) -> dict[str, int]:
    """启动/重启后预热 Redis · 失败不阻塞 Pod。"""
    if not redis_client:
        return {"symbols": 0, "warmed": 0, "skipped": "no_redis"}

    syms = symbols or await load_executing_collect_symbols(session)
    if not syms:
        return {"symbols": 0, "warmed": 0, "skipped": "no_symbols"}

    loaders = [_import_loader(d) for d in _WARMUP_LOADERS]
    warmed = 0
    for sym in syms:
        code = sym.zfill(6)[-6:]
        for loader in loaders:
            try:
                payload = await _call_loader(loader, session, code, redis_client)
                if payload:
                    warmed += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("redis warm skip %s %s: %s", code, loader.__name__, exc)

    logger.info(
        "Executing Redis 预热完成 symbols=%d loader_hits=%d",
        len(syms),
        warmed,
    )
    return {"symbols": len(syms), "warmed": warmed}


async def warm_executing_all_redis_from_pg(
    session: AsyncSession,
    redis_client: Any,
    *,
    symbols: list[str] | None = None,
    analyst_session_limit: int = 50,
    radar_chat_session_limit: int = 50,
) -> dict[str, Any]:
    """探针热缓存 + T2 / 雷达对话会话 + UI 设置一并预热。"""
    from apps.copilot.modules.copilot_ui_settings import warm_ui_settings_from_pg
    from apps.copilot.modules.executing.t2_analyst import warm_t2_analyst_sessions_from_pg
    from apps.copilot.modules.radar.chat import warm_radar_chat_sessions_from_pg

    probe_stats = await warm_executing_redis_from_pg(
        session, redis_client, symbols=symbols
    )
    chat_stats = await warm_t2_analyst_sessions_from_pg(
        session, redis_client, limit=analyst_session_limit
    )
    radar_stats = await warm_radar_chat_sessions_from_pg(
        session, redis_client, limit=radar_chat_session_limit
    )
    ui_stats = await warm_ui_settings_from_pg(session)
    return {
        "probe": probe_stats,
        "t2_analyst_chat": chat_stats,
        "radar_chat": radar_stats,
        "ui_settings": ui_stats,
    }


async def count_t1_snapshots(session: AsyncSession, symbol: str) -> int:
    """诊断：PG 中该标的 T1 快照行数。"""
    from sqlalchemy import func, select

    from apps.copilot.db.models import ExecutingT1ProbeSnapshot

    sym = symbol.zfill(6)[-6:]
    n = await session.scalar(
        select(func.count())
        .select_from(ExecutingT1ProbeSnapshot)
        .where(ExecutingT1ProbeSnapshot.symbol == sym)
    )
    return int(n or 0)
