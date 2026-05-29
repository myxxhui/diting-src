"""月报补缺：上一自然月 step08 报告缺失时生成。

定时触发生效由 `report_jobs.copilot.monthly_report` 注册（与 settings 对齐）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from pathlib import Path
from typing import List

from sqlalchemy import select

from apps.copilot.services.ledger.models import MonthlyReport

logger = logging.getLogger(__name__)


def _previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


class LedgerScheduler:
    """保留占位：月报 cron 已迁至 `scheduler/jobs/report_jobs.py`。"""

    def __init__(
        self,
        generator,  # noqa: ANN001 — 兼容 main 传参
        *,
        user_ids: List[str],
        cron_day: int = 1,
        cron_hour: int = 9,
    ):
        self._gen = generator
        self._user_ids = user_ids or ["default"]
        self._cron_day = cron_day
        self._cron_hour = cron_hour

    def start(self) -> None:
        logger.info(
            "LedgerScheduler: 月报由 report_jobs id=copilot.monthly_report 调度 (day=%d hour=%d)",
            self._cron_day,
            self._cron_hour,
        )

    def stop(self) -> None:
        pass

    async def backfill_previous_month_if_missing(self, session_factory) -> None:
        from apps.copilot.config import settings
        from apps.copilot.services.reports.ledger_adapter import ReportLedgerAdapter
        from apps.copilot.services.reports.monthly import MonthlyReportGenerator
        from apps.copilot.services.reports.pdf import WeasyPDFRenderer

        year, month = _previous_month(date.today())
        last_day = calendar.monthrange(year, month)[1]
        target = date(year, month, min(15, last_day))
        renderer = WeasyPDFRenderer()
        out_root = Path(settings.ledger_reports_dir)

        for user_id in self._user_ids:
            async with session_factory() as session:
                exists = (
                    await session.execute(
                        select(MonthlyReport.id)
                        .where(MonthlyReport.user_id == user_id)
                        .where(MonthlyReport.year == year)
                        .where(MonthlyReport.month == month)
                    )
                ).first()
            if exists:
                continue
            logger.info("backfill step08 月报 user=%s %04d-%02d", user_id, year, month)
            async with session_factory() as session:
                ledger = ReportLedgerAdapter(session_factory)
                gen = MonthlyReportGenerator(session, ledger)
                ctx = await gen.aggregate(user_id, target)
                out = out_root / f"monthly_{user_id}_{ctx.period_label}.pdf"
                renderer.render(ctx, out)
                await gen.persist(ctx, str(out))
