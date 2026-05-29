"""蒸馏 API 路由：单条 + 批量 + 健康。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from apps.super_evo.storage.minio_client import MinIOClient
from apps.super_evo.teacher.clients.anthropic_client import AnthropicTeacherClient
from apps.super_evo.teacher.distiller import TeacherDistiller
from apps.super_evo.teacher.rate_limiter import RateLimiter
from apps.super_evo.teacher.schemas import DistillInput

router = APIRouter(prefix="/api/distill", tags=["distill"])


def _build_distiller() -> TeacherDistiller:
    return TeacherDistiller(
        client=AnthropicTeacherClient(),
        rate_limiter=RateLimiter(per_minute=30, burst=5),
        minio=MinIOClient(),
        concurrency=4,
    )


@router.get("/health")
async def health() -> dict[str, Any]:
    client = AnthropicTeacherClient()
    return {
        "ok": True,
        "teacher_model": client.model_name,
        "dry_run": client.dry_run,
    }


@router.post("/single")
async def distill_single(item: DistillInput) -> dict[str, Any]:
    distiller = _build_distiller()
    try:
        out = await distiller.distill_one(item)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return out.model_dump()


@router.post("/batch")
async def distill_batch(items: list[DistillInput]) -> dict[str, Any]:
    if not items:
        raise HTTPException(status_code=400, detail="items must be non-empty")
    task_type = items[0].task_type
    distiller = _build_distiller()
    try:
        result = await distiller.distill_batch(items, task_type=task_type)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        **result.model_dump(mode="json"),
        "throughput_per_day": round(result.throughput_per_day, 2),
    }
