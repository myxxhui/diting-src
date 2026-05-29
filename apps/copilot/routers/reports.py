"""手动查看日报 / 周报 HTML。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_07]
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.config import settings
from apps.copilot.db.database import AsyncSessionLocal, get_db
from apps.copilot.services.reports.daily import DailyReportGenerator
from apps.copilot.services.reports.ledger_adapter import ReportLedgerAdapter
from apps.copilot.services.reports.monthly import MonthlyReportGenerator
from apps.copilot.services.reports.pdf import WeasyPDFRenderer
from apps.copilot.services.reports.renderer import ReportRenderer
from apps.copilot.services.reports.weekly import WeeklyReportGenerator

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/daily/{report_date}", response_class=HTMLResponse)
async def get_daily(
    report_date: str,
    user_id: str = "default",
    session: AsyncSession = Depends(get_db),
):
    try:
        d = date.fromisoformat(report_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="report_date 须为 YYYY-MM-DD") from exc
    ledger = ReportLedgerAdapter(AsyncSessionLocal)
    gen = DailyReportGenerator(session, ledger)
    ctx = await gen.aggregate(user_id, d)
    return ReportRenderer().render("daily", "html", ctx)


@router.get("/weekly/{iso_label}", response_class=HTMLResponse)
async def get_weekly(
    iso_label: str,
    user_id: str = "default",
    session: AsyncSession = Depends(get_db),
):
    """iso_label 形如 ``2026-W20``。"""
    try:
        year_s, week_s = iso_label.upper().split("-W")
        iso_year, iso_week = int(year_s), int(week_s)
        any_day = date.fromisocalendar(iso_year, iso_week, 7)
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail="iso_label 须为 YYYY-Www") from exc
    ledger = ReportLedgerAdapter(AsyncSessionLocal)
    gen = WeeklyReportGenerator(session, ledger)
    ctx = await gen.aggregate(user_id, any_day)
    return ReportRenderer().render("weekly", "html", ctx)


@router.get("/monthly/{year_month}/pdf")
async def get_monthly_pdf(
    year_month: str,
    user_id: str = "default",
    session: AsyncSession = Depends(get_db),
):
    """``year_month`` 形如 ``2026-05``。首次请求生成 PDF 并落库。"""
    try:
        parts = year_month.split("-")
        if len(parts) != 2:
            raise ValueError
        year, month = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="year_month 须为 YYYY-MM") from exc

    ledger = ReportLedgerAdapter(AsyncSessionLocal)
    gen = MonthlyReportGenerator(session, ledger)
    target = date(year, month, 15)
    ctx = await gen.aggregate(user_id, target)
    out = Path(settings.ledger_reports_dir) / f"monthly_{user_id}_{ctx.period_label}.pdf"
    if not out.exists():
        WeasyPDFRenderer().render(ctx, out)
        await gen.persist(ctx, str(out))
    return FileResponse(str(out), media_type="application/pdf", filename=out.name)
