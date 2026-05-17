"""月报调度器：每月 1 日 09:00 生成上月报；启动时补缺。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from apps.copilot.services.ledger.monthly_report import MonthlyReportGenerator

logger = logging.getLogger(__name__)


def _previous_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


class LedgerScheduler:
    def __init__(
        self,
        generator: MonthlyReportGenerator,
        *,
        user_ids: List[str],
        cron_day: int = 1,
        cron_hour: int = 9,
    ):
        self._gen = generator
        self._user_ids = user_ids or ["default"]
        self._cron_day = cron_day
        self._cron_hour = cron_hour
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        trigger = CronTrigger(day=self._cron_day, hour=self._cron_hour, minute=0)
        self._scheduler.add_job(
            self._monthly_job,
            trigger,
            id="monthly_report",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info(
            "ledger scheduler started: cron day=%d hour=%d users=%s",
            self._cron_day,
            self._cron_hour,
            self._user_ids,
        )

    def stop(self) -> None:
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:
            pass

    async def _monthly_job(self) -> None:
        year, month = _previous_month(date.today())
        for user_id in self._user_ids:
            try:
                await self._gen.generate(user_id=user_id, year=year, month=month)
                logger.info("月报生成完成: user=%s %04d-%02d", user_id, year, month)
            except Exception as e:
                logger.exception("月报生成失败 user=%s %04d-%02d: %s", user_id, year, month, e)

    async def backfill_previous_month_if_missing(self, session_factory) -> None:
        from sqlalchemy import select

        from apps.copilot.services.ledger.models import MonthlyReport

        year, month = _previous_month(date.today())
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
            if not exists:
                logger.info("backfill 月报 user=%s %04d-%02d", user_id, year, month)
                await self._gen.generate(user_id=user_id, year=year, month=month)
