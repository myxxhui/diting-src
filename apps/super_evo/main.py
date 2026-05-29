"""super-evo FastAPI 入口。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_01]
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from apps.super_evo.config import settings
from apps.super_evo.deployment.wandb_tracker import WandbTracker
from apps.super_evo.storage.minio_client import MinIOClient
from apps.super_evo.versioning.dvc_manager import DVCManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.minio = MinIOClient()
    app.state.dvc = DVCManager()
    app.state.wandb = WandbTracker()
    yield
    await app.state.redis.aclose()


app = FastAPI(title="super-evo · 演进飞轮", lifespan=lifespan, version="0.1.0")

from apps.super_evo.api.routes.distill import router as distill_router  # noqa: E402
from apps.super_evo.api.routes.labeling import router as labeling_router  # noqa: E402

app.include_router(distill_router)
app.include_router(labeling_router)


async def _redis_health(r: aioredis.Redis) -> dict:
    try:
        pong = await r.ping()
        return {"ok": bool(pong)}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


@app.get("/health")
async def health() -> dict:
    redis_status = await _redis_health(app.state.redis)
    minio_status = app.state.minio.health()
    dvc_status = app.state.dvc.health()
    wandb_status = app.state.wandb.health()

    overall_ok = redis_status["ok"] and minio_status["ok"] and dvc_status["ok"]

    return {
        "status": "ok" if overall_ok else "degraded",
        "service": settings.service_name,
        "components": {
            "redis": redis_status,
            "minio": minio_status,
            "dvc": dvc_status,
            "wandb": wandb_status,
        },
        "output_stream": settings.output_stream,
    }


@app.get("/")
async def root() -> dict:
    return {"service": settings.service_name, "doc": "/docs", "health": "/health"}
