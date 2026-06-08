"""执行区全局设置（账户可用资金）。

[Ref: 28_ §5.3]
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ExecutingWorkspaceSettings

_SETTINGS_ID = "default"


async def get_workspace_settings(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(ExecutingWorkspaceSettings, _SETTINGS_ID)
    if row is None:
        return {"available_cash": None, "updated_at": None}
    return {
        "available_cash": float(row.available_cash) if row.available_cash is not None else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def save_workspace_settings(
    session: AsyncSession,
    *,
    available_cash: float | None,
) -> ExecutingWorkspaceSettings:
    row = await session.get(ExecutingWorkspaceSettings, _SETTINGS_ID)
    if row is None:
        row = ExecutingWorkspaceSettings(id=_SETTINGS_ID)
        session.add(row)
    row.available_cash = available_cash
    await session.flush()
    return row
