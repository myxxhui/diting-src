"""持仓管理路由 - 维护页 + Excel 导入。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.db.models import Holding
from apps.copilot.services.excel_importer import (
    ExcelImportError,
    ensure_default_user,
    parse_excel,
    upsert_holdings,
)

router = APIRouter()


def _templates(request: Request):
    return request.app.state.templates


async def _list_holdings(session: AsyncSession, user_pk: int) -> list[Holding]:
    res = await session.scalars(
        select(Holding).where(Holding.user_pk == user_pk).order_by(Holding.symbol)
    )
    return list(res.all())


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _templates(request).TemplateResponse(request, "index.html", {})


@router.get("/holdings", response_class=HTMLResponse)
async def holdings_page(request: Request, session: AsyncSession = Depends(get_db)):
    user = await ensure_default_user(session)
    holdings = await _list_holdings(session, user.id)
    return _templates(request).TemplateResponse(
        request, "portfolio/list.html", {"holdings": holdings}
    )


@router.post("/holdings", response_class=HTMLResponse)
async def create_holding(
    request: Request,
    symbol: str = Form(...),
    name: str = Form(...),
    shares: float = Form(...),
    cost_price: float = Form(...),
    notes: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_db),
):
    user = await ensure_default_user(session)
    await upsert_holdings(
        session,
        user.id,
        [
            {
                "symbol": symbol.strip().zfill(6),
                "name": name,
                "shares": shares,
                "cost_price": cost_price,
                "notes": notes,
            }
        ],
    )
    holdings = await _list_holdings(session, user.id)
    return _templates(request).TemplateResponse(
        request, "portfolio/_list_table.html", {"holdings": holdings}
    )


@router.post("/holdings/import", response_class=HTMLResponse)
async def import_excel(
    request: Request,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
):
    user = await ensure_default_user(session)
    try:
        rows = parse_excel(await file.read())
    except ExcelImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await upsert_holdings(session, user.id, rows)
    holdings = await _list_holdings(session, user.id)
    return _templates(request).TemplateResponse(
        request, "portfolio/_list_table.html", {"holdings": holdings}
    )
