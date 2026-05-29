"""每月月报聚合（step_08）：SCS/EV 按日趋势、8 象限、TOP 复盘、行为与告警概要。

与 `services/ledger/monthly_report.py` 并存：本模块为 ReportContext + WeasyPrint 管线；
定时任务见 `report_jobs.copilot.monthly_report`。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import ThesisCard, User, UserDecision
from apps.copilot.services.alerts.models import AlertLog
from apps.copilot.services.ledger.models import AttributionRecord, MonthlyReport as MonthlyReportRow
from apps.copilot.services.reports.base import BaseReportGenerator, ReportContext


class MonthlyLedgerPort(Protocol):
    async def snapshot_scs(self, user_id: str, day: date) -> float: ...

    async def compute_avoided_loss(self, user_id: str, start: date, end: date) -> float: ...

    async def compute_earned(self, user_id: str, start: date, end: date) -> float: ...


@dataclass
class TopThesis:
    thesis_id: str
    symbol: str
    name: str
    octant: str
    pnl: float
    note: str


class MonthlyReportGenerator(BaseReportGenerator):
    kind = "monthly"

    def __init__(self, session: AsyncSession, ledger: MonthlyLedgerPort) -> None:
        self.session = session
        self.ledger = ledger

    @staticmethod
    def month_range(year: int, month: int) -> tuple[date, date]:
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return start, end

    async def aggregate(self, user_id: str, period_date: date) -> ReportContext:
        year, month = period_date.year, period_date.month
        start, end = self.month_range(year, month)

        scs_trend = await self._scs_trend(user_id, start, end)
        ev_trend = await self._ev_trend(user_id, start, end)
        octants = await self._octant_distribution(user_id, start, end)
        top_success, top_failure = await self._top_thesis(user_id, start, end)
        behavior = await self._user_behavior(user_id, start, end)
        alerts_overview = await self._alerts_overview(user_id, start, end)

        payload: dict[str, Any] = {
            "year": year,
            "month": month,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "scs_trend": scs_trend,
            "ev_trend": ev_trend,
            "octants": octants,
            "top_success": [t.__dict__ for t in top_success],
            "top_failure": [t.__dict__ for t in top_failure],
            "behavior": behavior,
            "alerts_overview": alerts_overview,
            "scs_summary": {
                "first": scs_trend[0]["scs"] if scs_trend else 0.0,
                "last": scs_trend[-1]["scs"] if scs_trend else 0.0,
                "max": max((p["scs"] for p in scs_trend), default=0.0),
                "min": min((p["scs"] for p in scs_trend), default=0.0),
            },
            "ev_summary": {
                "avoided_loss": sum(p["avoided_loss"] for p in ev_trend),
                "earned": sum(p["earned"] for p in ev_trend),
            },
        }

        return ReportContext(
            user_id=user_id,
            period_label=f"{year}-{month:02d}",
            period_start=start,
            period_end=end,
            is_demo=not octants["any_real"],
            payload=payload,
        )

    async def _scs_trend(self, user_id: str, start: date, end: date) -> list[dict[str, Any]]:
        days = (end - start).days + 1
        out: list[dict[str, Any]] = []
        for i in range(days):
            d = start + timedelta(days=i)
            try:
                scs = await self.ledger.snapshot_scs(user_id, d)
            except Exception:
                scs = 0.0
            out.append({"date": d.isoformat(), "scs": float(scs)})
        return out

    async def _ev_trend(self, user_id: str, start: date, end: date) -> list[dict[str, Any]]:
        days = (end - start).days + 1
        out: list[dict[str, Any]] = []
        for i in range(days):
            d = start + timedelta(days=i)
            try:
                avoided = float(await self.ledger.compute_avoided_loss(user_id, d, d))
                earned = float(await self.ledger.compute_earned(user_id, d, d))
            except Exception:
                avoided = earned = 0.0
            out.append({"date": d.isoformat(), "avoided_loss": avoided, "earned": earned})
        return out

    async def _octant_distribution(self, user_id: str, start: date, end: date) -> dict[str, Any]:
        day_start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        day_end = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        stmt = (
            select(AttributionRecord.octant, func.count(), func.sum(AttributionRecord.result_pnl))
            .where(
                and_(
                    AttributionRecord.user_id == user_id,
                    AttributionRecord.created_at >= day_start,
                    AttributionRecord.created_at <= day_end,
                )
            )
            .group_by(AttributionRecord.octant)
        )
        res = await self.session.execute(stmt)
        counts: dict[str, dict[str, Any]] = {x: {"count": 0, "pnl": 0.0} for x in "ABCDEFGH"}
        total = 0
        for octant, c, s in res.all():
            counts[octant] = {"count": int(c), "pnl": float(s or 0.0)}
            total += int(c)
        return {"counts": counts, "total": total, "any_real": total > 0}

    async def _top_thesis(
        self, user_id: str, start: date, end: date
    ) -> tuple[list[TopThesis], list[TopThesis]]:
        day_start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        day_end = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
        stmt = (
            select(AttributionRecord, ThesisCard)
            .outerjoin(ThesisCard, AttributionRecord.symbol == ThesisCard.symbol)
            .where(
                and_(
                    AttributionRecord.user_id == user_id,
                    AttributionRecord.created_at >= day_start,
                    AttributionRecord.created_at <= day_end,
                )
            )
        )
        res = await self.session.execute(stmt)
        rows = res.all()
        success = sorted([r for r in rows if r[0].result_pnl > 0], key=lambda r: -r[0].result_pnl)[:3]
        failure = sorted([r for r in rows if r[0].result_pnl < 0], key=lambda r: r[0].result_pnl)[:3]

        def to_top(rs: list) -> list[TopThesis]:
            out: list[TopThesis] = []
            for attr, thesis in rs:
                out.append(
                    TopThesis(
                        thesis_id=(thesis.thesis_id if thesis else f"attr-{attr.id}"),
                        symbol=attr.symbol,
                        name=(thesis.name if thesis else attr.symbol),
                        octant=attr.octant,
                        pnl=float(attr.result_pnl),
                        note=(attr.attribution_text or ""),
                    )
                )
            return out

        return to_top(success), to_top(failure)

    async def _user_behavior(self, user_id: str, start: date, end: date) -> dict[str, Any]:
        join_q = (
            select(func.count())
            .select_from(UserDecision)
            .join(User, User.id == UserDecision.user_pk)
            .where(
                User.user_id == user_id,
                UserDecision.action == "join",
                func.date(UserDecision.decided_at) >= start,
                func.date(UserDecision.decided_at) <= end,
            )
        )
        total_q = (
            select(func.count())
            .select_from(UserDecision)
            .join(User, User.id == UserDecision.user_pk)
            .where(
                User.user_id == user_id,
                func.date(UserDecision.decided_at) >= start,
                func.date(UserDecision.decided_at) <= end,
            )
        )
        joined = (await self.session.execute(join_q)).scalar_one()
        total = (await self.session.execute(total_q)).scalar_one()
        return {
            "exec_rate": (int(joined) / int(total)) if total else 0.0,
            "join": int(joined),
            "total": int(total),
        }

    async def _alerts_overview(self, user_id: str, start: date, end: date) -> dict[str, Any]:
        stmt = (
            select(AlertLog.level, func.count())
            .where(
                AlertLog.user_id == user_id,
                func.date(AlertLog.created_at) >= start,
                func.date(AlertLog.created_at) <= end,
            )
            .group_by(AlertLog.level)
        )
        res = await self.session.execute(stmt)
        rows = {str(l): int(c) for l, c in res.all()}
        return {"red": rows.get("red", 0), "orange": rows.get("orange", 0)}

    async def persist(self, ctx: ReportContext, pdf_path: str) -> MonthlyReportRow:
        oct = ctx.payload["octants"]["counts"]
        dist = {k: v["count"] for k, v in oct.items()}
        row = MonthlyReportRow(
            user_id=ctx.user_id,
            year=ctx.payload["year"],
            month=ctx.payload["month"],
            scs=ctx.payload["scs_summary"]["last"],
            ev=ctx.payload["ev_summary"]["avoided_loss"] + ctx.payload["ev_summary"]["earned"],
            octant_distribution=dist,
            summary=ctx.payload,
            pdf_path=pdf_path,
            generated_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row
