"""cryo-guard FastAPI 入口。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis_async
from fastapi import FastAPI

from apps.cryo_guard.api.routes import health
from apps.cryo_guard.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()


app = FastAPI(title="Diting Cryo-Guard", version="0.1.0", lifespan=lifespan)
app.include_router(health.router, tags=["health"])


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.service_name, "status": "running"}
