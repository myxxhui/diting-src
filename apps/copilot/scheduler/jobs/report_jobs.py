"""APScheduler 任务注册。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from apps.copilot.config import settings
from apps.copilot.db.models import DailyReport, WeeklyReport
from apps.copilot.services.alerts.dispatcher import AlertDispatcher
from apps.copilot.services.reports.daily import DailyReportGenerator
from apps.copilot.services.reports.holdings_morning import HoldingsMorningBriefGenerator
from apps.copilot.services.reports.dispatcher import ReportDispatcher, ReportPush
from apps.copilot.services.reports.ledger_adapter import ReportLedgerAdapter
from apps.copilot.services.reports.monthly import MonthlyReportGenerator
from apps.copilot.services.reports.pdf import WeasyPDFRenderer
from apps.copilot.services.reports.renderer import ReportRenderer
from apps.copilot.services.reports.weekly import WeeklyReportGenerator

log = logging.getLogger(__name__)


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


_WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


async def run_daily_for_all(
    *,
    session_factory,
    alert_dispatcher: AlertDispatcher,
    now: date | None = None,
) -> None:
    today = now or date.today()
    mode = (settings.daily_report_mode or "holdings_merged").strip().lower()
    async with session_factory() as session:
        renderer = ReportRenderer()
        dispatcher = ReportDispatcher(alert_dispatcher)

        if mode == "holdings_merged":
            gen = HoldingsMorningBriefGenerator(session)
            try:
                for user_id in settings.report_user_ids:
                    ctx = await gen.aggregate(user_id, today)
                    html_body = renderer.render("holdings_morning", "html", ctx)
                    md_body = renderer.render("holdings_morning", "md", ctx)
                    digest = f"hm{today.strftime('%Y%m%d')}"
                    cd = ctx.payload.get("color_distribution") or {}
                    push = ReportPush(
                        title=(
                            f"[diting] 持仓早报 · {ctx.period_label} · "
                            f"🟢{cd.get('green',0)} 🟡{cd.get('yellow',0)} "
                            f"🟠{cd.get('orange',0)} 🔴{cd.get('red',0)}"
                        ),
                        html_body=html_body,
                        markdown_body=md_body,
                        user_id=user_id,
                        is_demo=ctx.is_demo,
                        digest_symbol=digest,
                    )
                    result = await dispatcher.push(push)
                    session.add(
                        DailyReport(
                            user_id=user_id,
                            report_date=today,
                            summary=dict(ctx.payload),
                            html_path=None,
                            markdown=md_body,
                            is_demo=ctx.is_demo,
                            sent_at=result["sent_at"],
                        )
                    )
                    log.info(
                        "holdings morning brief sent user=%s ok=%s",
                        user_id,
                        result.get("any_ok"),
                    )
                await session.commit()
            finally:
                await gen.close()
            return

        ledger = ReportLedgerAdapter(session_factory)
        gen = DailyReportGenerator(session, ledger)
        for user_id in settings.report_user_ids:
            ctx = await gen.aggregate(user_id, today)
            html_body = renderer.render("daily", "html", ctx)
            md_body = renderer.render("daily", "md", ctx)
            digest = f"d{today.strftime('%Y%m%d')}"
            push = ReportPush(
                title=f"日报 · {ctx.period_label}",
                html_body=html_body,
                markdown_body=md_body,
                user_id=user_id,
                is_demo=ctx.is_demo,
                digest_symbol=digest,
            )
            result = await dispatcher.push(push)
            session.add(
                DailyReport(
                    user_id=user_id,
                    report_date=today,
                    summary=dict(ctx.payload),
                    html_path=None,
                    markdown=md_body,
                    is_demo=ctx.is_demo,
                    sent_at=result["sent_at"],
                )
            )
            log.info("daily report sent user=%s result=%s", user_id, result.get("any_ok"))
        await session.commit()


async def run_weekly_for_all(
    *,
    session_factory,
    alert_dispatcher: AlertDispatcher,
    now: date | None = None,
) -> None:
    target = now or date.today()
    async with session_factory() as session:
        ledger = ReportLedgerAdapter(session_factory)
        gen = WeeklyReportGenerator(session, ledger)
        renderer = ReportRenderer()
        dispatcher = ReportDispatcher(alert_dispatcher)

        for user_id in settings.report_user_ids:
            ctx = await gen.aggregate(user_id, target)
            html_body = renderer.render("weekly", "html", ctx)
            md_body = renderer.render("weekly", "md", ctx)
            digest = f"w{ctx.payload['iso_year']:04d}{ctx.payload['iso_week']:02d}"
            push = ReportPush(
                title=f"周报 · {ctx.period_label}",
                html_body=html_body,
                markdown_body=md_body,
                user_id=user_id,
                is_demo=ctx.is_demo,
                digest_symbol=digest,
            )
            result = await dispatcher.push(push)
            session.add(
                WeeklyReport(
                    user_id=user_id,
                    iso_year=ctx.payload["iso_year"],
                    iso_week=ctx.payload["iso_week"],
                    summary=dict(ctx.payload),
                    html_path=None,
                    markdown=md_body,
                    is_demo=ctx.is_demo,
                    sent_at=result["sent_at"],
                )
            )
            log.info("weekly report sent user=%s ok=%s", user_id, result.get("any_ok"))
        await session.commit()


async def run_monthly_pdf_for_all(
    *,
    session_factory,
) -> None:
    """生成上一自然月 step08 月报 PDF 并落库。"""
    today = date.today()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    last_day = calendar.monthrange(y, m)[1]
    target = date(y, m, min(15, last_day))
    renderer = WeasyPDFRenderer()
    out_root = Path(settings.ledger_reports_dir)

    for user_id in settings.report_user_ids:
        async with session_factory() as session:
            ledger = ReportLedgerAdapter(session_factory)
            gen = MonthlyReportGenerator(session, ledger)
            ctx = await gen.aggregate(user_id, target)
            out = out_root / f"monthly_{user_id}_{ctx.period_label}.pdf"
            renderer.render(ctx, out)
            await gen.persist(ctx, str(out))
        log.info("monthly step08 done user=%s period=%s", user_id, ctx.period_label)


def register_report_jobs(
    scheduler: AsyncIOScheduler,
    *,
    session_factory,
    alert_dispatcher: AlertDispatcher,
) -> None:
    async def _daily_job() -> None:
        await run_daily_for_all(
            session_factory=session_factory, alert_dispatcher=alert_dispatcher
        )

    async def _weekly_job() -> None:
        await run_weekly_for_all(
            session_factory=session_factory, alert_dispatcher=alert_dispatcher
        )

    async def _monthly_job() -> None:
        await run_monthly_pdf_for_all(session_factory=session_factory)

    dh, dm = _parse_hhmm(settings.daily_report_time)
    scheduler.add_job(
        _daily_job,
        trigger=CronTrigger(hour=dh, minute=dm),
        id="copilot.daily_report",
        replace_existing=True,
        misfire_grace_time=600,
    )

    wh, wm = _parse_hhmm(settings.weekly_report_time)
    weekday = _WEEKDAY_MAP[settings.weekly_report_day.lower()]
    scheduler.add_job(
        _weekly_job,
        trigger=CronTrigger(day_of_week=weekday, hour=wh, minute=wm),
        id="copilot.weekly_report",
        replace_existing=True,
        misfire_grace_time=900,
    )
    scheduler.add_job(
        _monthly_job,
        trigger=CronTrigger(
            day=settings.monthly_cron_day,
            hour=settings.monthly_cron_hour,
            minute=0,
        ),
        id="copilot.monthly_report",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    log.info(
        "registered report jobs: daily=%02d:%02d, weekly=%s %02d:%02d, monthly=day%d %02d:00",
        dh,
        dm,
        settings.weekly_report_day,
        wh,
        wm,
        settings.monthly_cron_day,
        settings.monthly_cron_hour,
    )
