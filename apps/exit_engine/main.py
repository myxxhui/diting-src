"""exit-engine FastAPI 入口.[Ref: 03_/04_维度四/.../step_01] [Ref: step_02 portfolio+scheduler]"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI

from apps.exit_engine.config import settings
from apps.exit_engine.protocols import PROTOCOL_CLASSES
from apps.exit_engine.routers.buffer_router import router as buffer_router
from apps.exit_engine.routers.consumer_router import router as consumer_router
from apps.exit_engine.routers.portfolio_router import router as portfolio_router
from apps.exit_engine.routers.positions_router import router as positions_router
from apps.exit_engine.routers.protocol_router import router as protocol_router
from apps.exit_engine.routers.sp3_sp5_router import router as sp3_sp5_router
from apps.exit_engine.services.quote_scheduler import start_background_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    app.state.scheduler = start_background_scheduler()
    try:
        yield
    finally:
        app.state.scheduler.shutdown(wait=False)
        await app.state.redis.aclose()


app = FastAPI(title="exit-engine · 维度四·卖出决策", version="0.1.0", lifespan=lifespan)
app.include_router(portfolio_router)
app.include_router(positions_router)
app.include_router(protocol_router)
app.include_router(sp3_sp5_router)
app.include_router(consumer_router)
app.include_router(buffer_router)


@app.get("/api/quote/health")
async def quote_health() -> dict[str, Any]:
    """行情多源健康（腾讯/新浪/东财 + K 线源断路器状态）。"""
    from apps.exit_engine.data.quote_fetcher import QuoteFetcher

    fetcher = QuoteFetcher()
    health_map = fetcher.health()
    return {
        "sources": {
            name: {
                "status": h.status,
                "consecutive_failures": h.consecutive_failures,
                "last_ok_at": h.last_ok_at.isoformat() if h.last_ok_at else None,
                "tripped_until": h.tripped_until.isoformat() if h.tripped_until else None,
            }
            for name, h in health_map.items()
        }
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    protocols_status: dict[str, str] = {}
    for cls in PROTOCOL_CLASSES:
        try:
            instance = cls()
            _ = instance.protocol_name
            protocols_status[cls.__name__] = "loaded"
        except Exception as exc:
            protocols_status[cls.__name__] = f"error: {exc}"

    upstream_status: dict[str, Any] = {}
    for stream in [settings.health_change_stream]:
        try:
            info = await app.state.redis.xinfo_stream(stream)
            upstream_status[stream] = {"ok": True, "length": info.get("length", 0)}
        except Exception as exc:
            msg = str(exc).lower()
            reason = "stream not found (mock mode)" if "no such key" in msg else str(exc)
            upstream_status[stream] = {"ok": False, "reason": reason}

    return {
        "status": "ok",
        "service": settings.service_name,
        "version": "0.1.0",
        "protocols": protocols_status,
        "upstream": upstream_status,
        "output_stream": settings.output_stream,
        "listen_port": settings.port,
    }


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.service_name, "doc": "/docs"}
