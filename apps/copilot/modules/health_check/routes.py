"""持仓体检 API + 页面路由(M1)。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.modules.health_check.service import get_dashboard, get_detail

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


@router.get("/api/health/dashboard")
async def api_dashboard(session: AsyncSession = Depends(get_db)):
    return await get_dashboard(session)


@router.get("/api/health/{symbol}")
async def api_detail(symbol: str, session: AsyncSession = Depends(get_db)):
    return await get_detail(session, symbol)


@router.get("/health-dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request, session: AsyncSession = Depends(get_db)):
    data = await get_dashboard(session)
    return _templates(request).TemplateResponse(
        request, "health/dashboard.html", data
    )


@router.get("/health-detail/{symbol}", response_class=HTMLResponse)
async def page_detail(
    symbol: str, request: Request, session: AsyncSession = Depends(get_db)
):
    detail = await get_detail(session, symbol)
    return _templates(request).TemplateResponse(
        request, "health/holding_detail.html", detail
    )
