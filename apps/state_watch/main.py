"""state-watch FastAPI 入口.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import redis.asyncio as redis_async
from fastapi import FastAPI

from apps.state_watch.config import settings
from apps.state_watch.db.session import init_db, ping_db
from apps.state_watch.api.routes.probes import router as probes_router
from apps.state_watch.api.routes.state_machine import router as state_machine_router
from apps.state_watch.api.routes.monitor_dict import router as monitor_dict_router
from apps.state_watch.api.routes.market_phase import router as market_phase_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis_async.from_url(settings.redis_url, decode_responses=True)
    await init_db()
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(title="state-watch", lifespan=lifespan)
app.include_router(state_machine_router)
app.include_router(probes_router)
app.include_router(monitor_dict_router)
app.include_router(market_phase_router)


@app.get("/health")
async def health():
    redis_ok = False
    try:
        pong = await app.state.redis.ping()
        redis_ok = bool(pong)
    except Exception:
        redis_ok = False
    db_ok = await ping_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.service_name,
        "db": "ok" if db_ok else "down",
        "redis": "ok" if redis_ok else "mock",
    }
