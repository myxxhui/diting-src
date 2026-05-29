"""周报生成器（ISO 周；触发时点由调度配置）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import HealthRecord, Holding, ThesisCard, User, UserDecision
from apps.copilot.services.alerts.models import AlertLog
from apps.copilot.services.reports.base import BaseReportGenerator, ReportContext


class WeeklyLedgerPort(Protocol):
    async def compute_avoided_loss(self, user_id: str, start: date, end: date) -> float:
        ...


class WeeklyReportGenerator(BaseReportGenerator):
    kind = "weekly"

    def __init__(self, session: AsyncSession, ledger: WeeklyLedgerPort) -> None:
        self.session = session
        self.ledger = ledger

    @staticmethod
    def iso_week_range(any_day: date) -> tuple[date, date, int, int]:
        iso_year, iso_week, _ = any_day.isocalendar()
        monday = any_day - timedelta(days=any_day.weekday())
        sunday = monday + timedelta(days=6)
        return monday, sunday, iso_year, iso_week

    async def aggregate(self, user_id: str, period_date: date) -> ReportContext:
        monday, sunday, iso_year, iso_week = self.iso_week_range(period_date)

        alerts = await self._alerts(user_id, monday, sunday)
        thesis = await self._thesis(monday, sunday)
        decisions = await self._decisions(user_id, monday, sunday)
        avoided = await self._avoided_loss(user_id, monday, sunday)
        holdings = await self._holdings_delta(user_id, monday, sunday)

        is_demo = alerts["total"] == 0 and thesis["new"] == 0

        payload: dict[str, Any] = {
            "alerts": alerts,
            "thesis": thesis,
            "decisions": decisions,
            "avoided_loss": avoided,
            "holdings_delta": holdings,
            "iso_year": iso_year,
            "iso_week": iso_week,
        }
        return ReportContext(
            user_id=user_id,
            period_label=f"{iso_year}-W{iso_week:02d}",
            period_start=monday,
            period_end=sunday,
            is_demo=is_demo,
            payload=payload,
        )

    async def _alerts(self, user_id: str, start: date, end: date) -> dict[str, Any]:
        stmt = (
            select(AlertLog.level, AlertLog.alert_type, func.count())
            .where(
                AlertLog.user_id == user_id,
                func.date(AlertLog.created_at) >= start,
                func.date(AlertLog.created_at) <= end,
            )
            .group_by(AlertLog.level, AlertLog.alert_type)
        )
        res = await self.session.execute(stmt)
        by_type: dict[str, int] = {}
        red = orange = 0
        for level, alert_type, c in res.all():
            by_type[f"{level}:{alert_type}"] = int(c)
            if level == "red":
                red += int(c)
            elif level == "orange":
                orange += int(c)
        return {"red": red, "orange": orange, "total": red + orange, "by_type": by_type}

    async def _thesis(self, start: date, end: date) -> dict[str, Any]:
        stmt = select(func.count()).select_from(ThesisCard).where(
            func.date(ThesisCard.proposed_at) >= start,
            func.date(ThesisCard.proposed_at) <= end,
        )
        total = (await self.session.execute(stmt)).scalar_one()
        return {"new": int(total)}

    async def _decisions(self, user_id: str, start: date, end: date) -> dict[str, int]:
        stmt = (
            select(UserDecision.action, func.count())
            .join(User, User.id == UserDecision.user_pk)
            .where(
                User.user_id == user_id,
                func.date(UserDecision.decided_at) >= start,
                func.date(UserDecision.decided_at) <= end,
            )
            .group_by(UserDecision.action)
        )
        res = await self.session.execute(stmt)
        return {a: int(c) for a, c in res.all()}

    async def _avoided_loss(self, user_id: str, start: date, end: date) -> float:
        try:
            return float(await self.ledger.compute_avoided_loss(user_id, start, end))
        except Exception:  # noqa: BLE001
            return 0.0

    async def _holdings_delta(self, user_id: str, start: date, end: date) -> dict[str, Any]:
        async def color_count(d: date) -> dict[str, int]:
            stmt = (
                select(HealthRecord.push_level, func.count())
                .join(Holding, Holding.symbol == HealthRecord.symbol)
                .join(User, User.id == Holding.user_pk)
                .where(User.user_id == user_id, func.date(HealthRecord.occurred_at) == d)
                .group_by(HealthRecord.push_level)
            )
            res = await self.session.execute(stmt)
            rows = {int(level): int(c) for level, c in res.all()}
            return {
                "red": rows.get(3, 0),
                "orange": rows.get(2, 0),
                "yellow": rows.get(1, 0),
                "green": rows.get(0, 0),
            }

        first = await color_count(start)
        last = await color_count(end)
        return {"open": first, "close": last, "delta": {k: last[k] - first[k] for k in last}}
