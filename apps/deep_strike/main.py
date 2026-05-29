"""deep-strike FastAPI 入口.

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from sqlalchemy import text

from apps.deep_strike import __service__, __version__
from apps.deep_strike.api import routes as api_routes
from apps.deep_strike.api.routes_human_gate import router as human_gate_router
from apps.deep_strike.api.routes_thesis import router as thesis_router
from apps.deep_strike.config import settings
from apps.deep_strike.db.database import AsyncSessionLocal, engine, init_db

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="deep-strike · 纵深进攻", lifespan=lifespan)
app.include_router(api_routes.router)
app.include_router(thesis_router)
app.include_router(human_gate_router)

from apps.deep_strike.api.routes_lighthouse import router as lighthouse_router  # noqa: E402

app.include_router(lighthouse_router)


@app.get("/health")
async def health():
    upstream_status: dict[str, dict] = {}
    for stream in settings.upstream_streams:
        try:
            info = await app.state.redis.xinfo_stream(stream)
            upstream_status[stream] = {"ok": True, "length": info.get("length", 0)}
        except Exception as exc:
            msg = str(exc).lower()
            upstream_status[stream] = {
                "ok": False,
                "reason": "stream not found (mock mode)" if "no such key" in msg else str(exc)[:200],
            }

    db_ok = True
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        log.warning("db health probe failed: %s", exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "service": settings.service_name,
        "version": __version__,
        "upstream": upstream_status,
        "db": "ok" if db_ok else "down",
        "weekly_quota": settings.weekly_thesis_quota,
    }
