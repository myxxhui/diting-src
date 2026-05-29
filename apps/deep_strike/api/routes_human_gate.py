"""D2 step_08 · 人工确认门禁 API（HumanGate）。

提供 confirm / reject / defer 三个操作端点。
唯一允许 status→confirmed 的代码路径。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_08_人工确认门禁与一致率.md]
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.deep_strike.config import settings
from apps.deep_strike.db.database import get_db
from apps.deep_strike.human_gate.gate import HumanGate

router = APIRouter(prefix="/api/thesis", tags=["human-gate"])


class ConfirmRequest(BaseModel):
    reviewer: str = Field(min_length=1, description="审核人标识")
    comment: Optional[str] = Field(default="", max_length=500)


def _get_gate() -> HumanGate:
    """获取 HumanGate 实例（含 Redis publisher）。"""
    try:
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        return HumanGate(redis_client=r)
    except Exception:
        return HumanGate(redis_client=None)


@router.post("/{thesis_id}/confirm")
async def confirm_thesis(
    thesis_id: str,
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """人工 confirm：唯一合法的 status→confirmed + 推送 events:thrust:thesis_proposed。"""
    gate = _get_gate()
    result = await gate.confirm(
        session,
        thesis_id=thesis_id,
        reviewer=body.reviewer,
        comment=body.comment or "",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "error"))
    return result


@router.post("/{thesis_id}/reject")
async def reject_thesis(
    thesis_id: str,
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """人工 reject：status→rejected，不推送 stream。"""
    gate = _get_gate()
    result = await gate.reject(
        session,
        thesis_id=thesis_id,
        reviewer=body.reviewer,
        comment=body.comment or "",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "error"))
    return result


@router.post("/{thesis_id}/defer")
async def defer_thesis(
    thesis_id: str,
    body: ConfirmRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """人工 defer：status→deferred，不推送 stream。"""
    gate = _get_gate()
    result = await gate.defer(
        session,
        thesis_id=thesis_id,
        reviewer=body.reviewer,
        comment=body.comment or "",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "error"))
    return result
