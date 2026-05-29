"""管理员接口：自我熔断状态与重置。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.config import settings
from apps.copilot.db.database import get_db
from apps.copilot.services.circuit_breaker import SelfCircuitBreaker

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_redis(request: Request):
    return request.app.state.redis


async def _ensure_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="invalid admin token")


@router.get("/circuit-breaker/status")
async def circuit_breaker_status(
    session: AsyncSession = Depends(get_db),
    r=Depends(get_redis),
):
    cb = SelfCircuitBreaker(session, r)
    return await cb.status()


@router.post("/circuit-breaker/reset", dependencies=[Depends(_ensure_admin)])
async def circuit_breaker_reset(
    operator: str = Query(...),
    note: str = Query(""),
    session: AsyncSession = Depends(get_db),
    r=Depends(get_redis),
):
    cb = SelfCircuitBreaker(session, r)
    return await cb.reset(operator=operator, note=note)
