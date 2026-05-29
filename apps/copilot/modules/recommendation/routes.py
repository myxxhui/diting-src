"""推荐池路由(M2):页面 + API + PDF。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.modules.recommendation.schema import UserActionPayload
from apps.copilot.modules.recommendation.service import (
    export_pdf,
    get_thesis,
    list_pool,
    record_action,
)

router = APIRouter()


def _tpl(request: Request):
    return request.app.state.templates


@router.get("/recommendations", response_class=HTMLResponse)
async def page_pool(request: Request, session: AsyncSession = Depends(get_db)):
    pool = await list_pool(session)
    return _tpl(request).TemplateResponse(
        request, "recommendation/pool.html", {"pool": pool}
    )


@router.post("/api/recommendations/{thesis_id}/action", response_class=HTMLResponse)
async def action(
    thesis_id: str,
    payload: UserActionPayload,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    view = await get_thesis(session, thesis_id)
    if view is None:
        raise HTTPException(status_code=404, detail="thesis 不存在")
    updated = await record_action(session, thesis_id, payload)
    return _tpl(request).TemplateResponse(
        request, "recommendation/_card.html", {"t": updated}
    )


@router.get("/api/recommendations/{thesis_id}/pdf")
async def pdf(thesis_id: str, session: AsyncSession = Depends(get_db)):
    data = await export_pdf(session, thesis_id)
    if data is None:
        raise HTTPException(status_code=404, detail="thesis 不存在")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="thesis_{thesis_id}.pdf"'},
    )
