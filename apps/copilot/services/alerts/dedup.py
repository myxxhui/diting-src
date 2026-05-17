"""告警去重。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.services.alerts.models import Alert, AlertLog


class AlertDeduper:
    """基于 alert_logs 表的去重器（持久化 + 跨进程一致）。"""

    def __init__(self, session_factory, window_seconds: int = 3600):
        self._session_factory = session_factory
        self._window = window_seconds

    async def is_duplicate(self, alert: Alert) -> bool:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=self._window)
        async with self._session_factory() as session:  # type: AsyncSession
            stmt = (
                select(AlertLog.id)
                .where(AlertLog.dedup_key == alert.dedup_key)
                .where(AlertLog.created_at >= threshold)
                .limit(1)
            )
            row = (await session.execute(stmt)).first()
            return row is not None
