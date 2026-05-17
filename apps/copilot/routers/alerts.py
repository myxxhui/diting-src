"""告警 API 与页面。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_05]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.services.alerts.dispatcher import AlertDispatcher
from apps.copilot.services.alerts.models import Alert, AlertLog, AlertType

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
view_router = APIRouter(prefix="/alerts", tags=["alerts-view"])


def get_dispatcher(request: Request) -> AlertDispatcher:
    dispatcher: AlertDispatcher | None = getattr(request.app.state, "alert_dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="alert dispatcher not ready")
    return dispatcher


def get_session_factory(request: Request):
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise HTTPException(status_code=503, detail="db not ready")
    return factory


class AlertTestRequest(BaseModel):
    user_id: str = "default"
    alert_type: AlertType
    symbol: str
    name: str
    message: str = "手动触发测试告警"


@router.post("/test")
async def test_alert(
    req: AlertTestRequest, dispatcher: AlertDispatcher = Depends(get_dispatcher)
):
    alert = Alert.new(
        user_id=req.user_id,
        alert_type=req.alert_type,
        symbol=req.symbol,
        name=req.name,
        message=req.message,
        payload={"source": "manual_test"},
    )
    result = await dispatcher.dispatch(alert)
    return {"alert_id": alert.alert_id, "level": alert.level.value, "result": result}


@router.get("/history")
async def history(
    request: Request,
    level: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    since_hours: int = Query(72, ge=1, le=24 * 90),
    limit: int = Query(100, ge=1, le=1000),
):
    factory = get_session_factory(request)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    async with factory() as session:  # type: AsyncSession
        stmt = select(AlertLog).where(AlertLog.created_at >= since)
        if level:
            stmt = stmt.where(AlertLog.level == level)
        if alert_type:
            stmt = stmt.where(AlertLog.alert_type == alert_type)
        if symbol:
            stmt = stmt.where(AlertLog.symbol == symbol)
        stmt = stmt.order_by(AlertLog.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return {
        "count": len(rows),
        "alerts": [
            {
                "alert_id": r.alert_id,
                "user_id": r.user_id,
                "level": r.level,
                "alert_type": r.alert_type,
                "symbol": r.symbol,
                "name": r.name,
                "message": r.message,
                "channels_sent": r.channels_sent,
                "sla_met": r.sla_met,
                "latency_ms": r.latency_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@view_router.get("", response_class=HTMLResponse)
async def alerts_page(request: Request):
    factory = get_session_factory(request)
    templates = request.app.state.templates
    since = datetime.now(timezone.utc) - timedelta(hours=72)
    async with factory() as session:
        result = await session.execute(
            select(AlertLog)
            .where(AlertLog.created_at >= since)
            .order_by(AlertLog.created_at.desc())
            .limit(200)
        )
        rows = list(result.scalars().all())
    tpl = (
        "alerts/_alert_body.html"
        if (request.headers.get("hx-request") or "").lower() == "true"
        else "alerts/alert_history.html"
    )
    return templates.TemplateResponse(
        request,
        tpl,
        {"alerts": rows},
    )
