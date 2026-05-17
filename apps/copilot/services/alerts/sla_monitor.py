"""红色告警 SLA。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.services.alerts.models import Alert, AlertLevel, AlertLog


class SLAMonitor:
    """记录每条告警的派发延迟，红色告警判定是否在 SLA 内送达。"""

    def __init__(self, session_factory, red_sla_seconds: int = 300):
        self._session_factory = session_factory
        self._red_sla = red_sla_seconds

    async def record(
        self,
        alert: Alert,
        dispatch_ts: datetime,
        any_channel_ok_ts: datetime | None,
        channels_result: dict[str, dict],
    ) -> tuple[bool | None, int | None]:
        latency_ms: int | None = None
        sla_met: bool | None = None

        if any_channel_ok_ts is not None:
            latency_ms = int((any_channel_ok_ts - dispatch_ts).total_seconds() * 1000)

        if alert.level == AlertLevel.RED:
            if latency_ms is None:
                sla_met = False
            else:
                sla_met = latency_ms <= self._red_sla * 1000

        async with self._session_factory() as session:  # type: AsyncSession
            stmt = (
                update(AlertLog)
                .where(AlertLog.alert_id == alert.alert_id)
                .values(
                    sla_met=sla_met,
                    latency_ms=latency_ms,
                    channels_sent=channels_result,
                )
            )
            await session.execute(stmt)
            await session.commit()

        return sla_met, latency_ms

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
