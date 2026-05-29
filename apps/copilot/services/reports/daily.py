"""每日触发的日报生成器（时点由 APScheduler 配置）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import HealthRecord, Holding, User, UserDecision
from apps.copilot.services.alerts.models import AlertLog
from apps.copilot.services.reports.base import BaseReportGenerator, ReportContext


class LedgerPort(Protocol):
    async def snapshot_scs(self, user_id: str, day: date) -> float:
        ...


class DailyReportGenerator(BaseReportGenerator):
    kind = "daily"

    def __init__(self, session: AsyncSession, ledger: LedgerPort) -> None:
        self.session = session
        self.ledger = ledger

    async def aggregate(self, user_id: str, period_date: date) -> ReportContext:
        prev_date = period_date - timedelta(days=1)

        alert_summary = await self._count_alerts(user_id, period_date)
        color_delta = await self._color_delta(user_id, period_date, prev_date)
        scs_delta = await self._scs_delta(user_id, period_date, prev_date)
        exec_rate = await self._exec_rate(user_id, period_date)

        is_demo = not alert_summary["any_real"] and not color_delta["has_history"]
        payload: dict[str, Any] = {
            "alerts": alert_summary,
            "color_delta": color_delta,
            "scs_delta": scs_delta,
            "exec_rate": exec_rate,
        }
        return ReportContext(
            user_id=user_id,
            period_label=period_date.isoformat(),
            period_start=period_date,
            period_end=period_date,
            is_demo=is_demo,
            payload=payload,
        )

    async def _count_alerts(self, user_id: str, day: date) -> dict[str, Any]:
        stmt = (
            select(AlertLog.level, func.count())
            .where(AlertLog.user_id == user_id, func.date(AlertLog.created_at) == day)
            .group_by(AlertLog.level)
        )
        result = await self.session.execute(stmt)
        rows = {level: int(c) for level, c in result.all()}
        return {
            "red": rows.get("red", 0),
            "orange": rows.get("orange", 0),
            "total": sum(rows.values()),
            "any_real": sum(rows.values()) > 0,
        }

    async def _color_delta(self, user_id: str, today: date, prev: date) -> dict[str, Any]:
        async def snapshot(d: date) -> dict[str, int]:
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

        cur = await snapshot(today)
        prv = await snapshot(prev)
        return {
            "today": cur,
            "yesterday": prv,
            "delta": {k: cur[k] - prv[k] for k in cur},
            "has_history": any(prv.values()),
        }

    async def _scs_delta(self, user_id: str, today: date, prev: date) -> dict[str, float]:
        try:
            today_scs = await self.ledger.snapshot_scs(user_id, today)
            prev_scs = await self.ledger.snapshot_scs(user_id, prev)
        except Exception:  # noqa: BLE001
            today_scs = prev_scs = 0.0
        return {
            "today": float(today_scs),
            "yesterday": float(prev_scs),
            "delta": float(today_scs - prev_scs),
        }

    async def _exec_rate(self, user_id: str, day: date) -> dict[str, Any]:
        stmt = (
            select(UserDecision.action, func.count())
            .join(User, User.id == UserDecision.user_pk)
            .where(User.user_id == user_id, func.date(UserDecision.decided_at) == day)
            .group_by(UserDecision.action)
        )
        res = await self.session.execute(stmt)
        rows = {a: int(c) for a, c in res.all()}
        total = sum(rows.values())
        join = rows.get("join", 0)
        return {
            "join": join,
            "consider": rows.get("consider", 0),
            "not_interested": rows.get("not_interested", 0),
            "total": total,
            "rate": (join / total) if total else 0.0,
        }
