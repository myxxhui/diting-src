"""T0 一次性 / 批量采集 Job（读 collect_symbols SoT）。

[Ref: 27_ §2.1.1 · §6 P0 collect-once]
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.radar.symbol_resolve import display_name_for_symbol
from apps.copilot.modules.radar.t0.symbol_list import load_generic_t0_collect_symbols

logger = logging.getLogger(__name__)


async def collect_once(
    session: AsyncSession,
    *,
    symbols: list[str] | None = None,
    job_id: str = "collect-once",
    redis_client: Any = None,
) -> list[dict[str, Any]]:
    """对 collect 表内 enabled 标的（或指定列表）执行 T0+T1 采集并落缓存/库。

    禁止全 A 股遍历；symbols 为空时读 ``load_generic_t0_collect_symbols()``。
    """
    from apps.copilot.modules.radar.service import collect_symbol_t0_only

    target = symbols if symbols is not None else await load_generic_t0_collect_symbols(
        session, enabled_only=True
    )
    if not target:
        logger.warning("collect-once: collect 表无 enabled 标的，跳过")
        return []

    results: list[dict[str, Any]] = []
    for sym in target:
        sym = str(sym).zfill(6)[-6:]
        name = display_name_for_symbol(sym, "", allow_network=False) or sym
        try:
            row = await collect_symbol_t0_only(
                session,
                query_text=sym,
                redis_client=redis_client,
                job_id=job_id,
            )
            bg_sink = row.pop("_bg_sink", None)
            await session.commit()
            if bg_sink is not None:
                await bg_sink.drain()
            results.append(row)
            logger.info(
                "collect-once ok symbol=%s t0_ok=%s version=%s",
                sym,
                row.get("t0_ok_parts"),
                row.get("version_id"),
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            logger.exception("collect-once failed symbol=%s", sym)
            results.append(
                {
                    "symbol": sym,
                    "name": name,
                    "status": "error",
                    "error": str(exc)[:200],
                }
            )
    return results
