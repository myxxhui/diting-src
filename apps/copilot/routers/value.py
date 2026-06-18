"""价值账本 API：仪表盘 + 月报下载 + HTMX 页面。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select

from apps.copilot.services.ledger.models import MonthlyReport

router = APIRouter(prefix="/api/value", tags=["value"])
view_router = APIRouter(prefix="/value", tags=["value-view"])


def _services(request: Request) -> dict[str, Any]:
    s = getattr(request.app.state, "ledger", None)
    if not s:
        raise HTTPException(status_code=503, detail="ledger services not ready")
    return s


@router.get("/dashboard")
async def dashboard(request: Request, user_id: str = Query("default")):
    svc = _services(request)
    today = date.today()
    start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    end_year, end_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)

    scs_co = await svc["scs"].calculate(user_id=user_id, start=start, end=end)
    ev_co = await svc["ev"].calculate(user_id=user_id, start=start, end=end)
    breaker_state = await svc["breaker"].evaluate(user_id)

    return {
        "user_id": user_id,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "scs": scs_co.__dict__,
        "ev": ev_co.__dict__,
        "circuit_breaker": {
            "paused": breaker_state.paused,
            "reason": breaker_state.reason,
            "window": breaker_state.last_window_size,
            "bh_ratio": breaker_state.last_bh_ratio,
            "updated_at": breaker_state.updated_at.isoformat()
            if breaker_state.updated_at
            else None,
        },
    }


@router.get("/monthly-report/{period}")
async def monthly_report(
    request: Request,
    period: str,
    user_id: str = Query("default"),
    regenerate: bool = Query(False),
):
    try:
        year_s, month_s = period.split("-")
        year, month = int(year_s), int(month_s)
        if not (1 <= month <= 12):
            raise ValueError
    except Exception as exc:
        raise HTTPException(status_code=400, detail="period 必须为 YYYY-MM") from exc

    svc = _services(request)
    factory = request.app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(
                select(MonthlyReport)
                .where(MonthlyReport.user_id == user_id)
                .where(MonthlyReport.year == year)
                .where(MonthlyReport.month == month)
            )
        ).scalar_one_or_none()

    if row is None or regenerate:
        row = await svc["report"].generate(user_id=user_id, year=year, month=month)

    if not row.pdf_path:
        raise HTTPException(status_code=500, detail="月报文件不存在")

    path = Path(row.pdf_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=500, detail="月报文件不存在")

    media = "application/pdf" if str(path).endswith(".pdf") else "text/html"
    filename = path.name
    return FileResponse(str(path), media_type=media, filename=filename)


@view_router.get("", response_class=HTMLResponse)
async def value_page(request: Request, user_id: str = Query("default")):
    """兼容旧 /value 入口 → 决策复盘库 Tab。"""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/planning?view=ledger&user_id={user_id}", status_code=302)


@view_router.get("/dashboard", response_class=HTMLResponse)
async def value_dashboard_full(request: Request, user_id: str = Query("default")):
    svc = _services(request)
    templates = request.app.state.templates
    today = date.today()
    start = datetime(today.year, today.month, 1, tzinfo=timezone.utc)
    end_year, end_month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    end = datetime(end_year, end_month, 1, tzinfo=timezone.utc)

    scs_co = await svc["scs"].calculate(user_id=user_id, start=start, end=end)
    ev_co = await svc["ev"].calculate(user_id=user_id, start=start, end=end)
    breaker = await svc["breaker"].evaluate(user_id)

    return templates.TemplateResponse(
        "value/value_dashboard.html",
        {
            "request": request,
            "user_id": user_id,
            "scs": scs_co,
            "ev": ev_co,
            "breaker": breaker,
            "year": today.year,
            "month": today.month,
        },
    )
