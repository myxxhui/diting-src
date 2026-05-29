"""从持仓 SoT 同步到 exit_engine holdings 表.

[Ref: 03_/04_维度四/.../step_02]
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.common.holdings_sot import HoldingEntry, load_holdings_sot
from apps.exit_engine.data.holdings_repo import HoldingsRepository
from apps.exit_engine.models.position import Position


class HoldingsSyncError(ValueError):
    """SoT 字段不满足启动期必填约束."""


def _validate_entry(entry: HoldingEntry) -> None:
    if not entry.symbol or len(entry.symbol.strip()) != 6:
        raise HoldingsSyncError(f"symbol 无效: {entry.symbol!r}")


def _resolve_qty_cost(entry: HoldingEntry) -> tuple[float, float, bool]:
    """返回 (quantity, cost_price, pnl_ready)."""
    qty = float(entry.quantity or 0.0)
    cost = float(entry.cost_price or 0.0)
    pnl_ready = qty > 0 and cost > 0
    return qty, cost, pnl_ready


def sync_positions_from_sot(
    session: Session,
    user_id: str = "default",
) -> dict[str, Any]:
    """从 ``MY_HOLDINGS_YAML`` 全量同步 active 持仓（可重入 upsert + soft delete）."""
    sot = load_holdings_sot()
    repo = HoldingsRepository(session)
    active_symbols: set[str] = set()
    synced = 0
    skipped: list[str] = []
    incomplete_pnl: list[str] = []

    for entry in sot.holdings:
        if not entry.active:
            continue
        if entry.role != "portfolio":
            continue
        try:
            _validate_entry(entry)
        except HoldingsSyncError as exc:
            skipped.append(str(exc))
            continue
        qty, cost, pnl_ready = _resolve_qty_cost(entry)
        if not pnl_ready:
            incomplete_pnl.append(entry.symbol)
        active_symbols.add(entry.symbol)
        pos_id = f"{user_id}:{entry.symbol}"
        repo.upsert(
            Position(
                id=pos_id,
                symbol=entry.symbol,
                name=entry.name or entry.symbol,
                quantity=qty,
                cost_price=cost,
                user_id=user_id,
            )
        )
        synced += 1

    stale_ids: list[str] = []
    for row in repo.list_active(user_id=user_id):
        if row.symbol not in active_symbols:
            stale_ids.append(row.id)
    repo.deactivate(stale_ids)

    return {
        "synced": synced,
        "active_symbols": sorted(active_symbols),
        "portfolio_symbols": sot.portfolio_symbols(),
        "watchlist_symbols": sot.watchlist_symbols(),
        "deactivated": len(stale_ids),
        "skipped": skipped,
        "incomplete_pnl": incomplete_pnl,
        "source": str(sot.source_path),
    }
