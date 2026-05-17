"""维度三 health_change 事件处理器。

写入两张表:
- event_logs    : 原始事件审计
- health_records: 体检模块查询源

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
[Ref: 03_/00_维度零/.../03_数据采集与预处理.md#2.3-维度三事件-health_change]
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import EventLog, HealthRecord

STREAM_KEY = "events:monitor:health_change"


def _parse_dt(value: Any, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback or datetime.utcnow()


async def handle_health_change(
    session: AsyncSession, payload: dict[str, Any], msg_id: str
) -> None:
    """落库 health_change 事件。幂等键:event_id;重复事件直接跳过。"""
    event_id = str(payload.get("event_id") or msg_id)

    existing = await session.scalar(
        select(HealthRecord).where(HealthRecord.event_id == event_id)
    )
    if existing is not None:
        return

    occurred_at = _parse_dt(payload.get("timestamp"))
    node_state_raw = payload.get("node_state") or {}
    if isinstance(node_state_raw, dict):
        node_state = node_state_raw.get("state")
    else:
        node_state = str(node_state_raw) if node_state_raw else None

    session.add(
        EventLog(
            stream_key=STREAM_KEY,
            msg_id=msg_id,
            event_type=str(payload.get("event_type") or "health_change"),
            symbol=str(payload.get("symbol") or ""),
            payload=payload,
            trace_id=payload.get("trace_id"),
        )
    )
    session.add(
        HealthRecord(
            symbol=str(payload.get("symbol") or ""),
            name=str(payload.get("name") or ""),
            event_id=event_id,
            old_health=float(payload.get("old_health") or 0.0),
            new_health=float(payload.get("new_health") or 0.0),
            health_delta=float(payload.get("health_delta") or 0.0),
            push_level=int(payload.get("push_level") or 0),
            change_reason=payload.get("change_reason"),
            node_state=node_state if node_state is None else str(node_state),
            occurred_at=occurred_at,
        )
    )
    await session.commit()
