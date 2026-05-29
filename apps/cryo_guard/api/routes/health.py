"""/health 与 /api/decision-gate/health。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import redis.asyncio as redis_async
from fastapi import APIRouter, Request
from neo4j import AsyncGraphDatabase
from pymilvus import connections as milvus_conn

from apps.cryo_guard.config import settings

router = APIRouter()


def _vllm_health_url() -> str:
    u = settings.vllm_base_url.rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3].rstrip("/")
    return f"{u}/health"


async def _check_redis(client: redis_async.Redis) -> dict[str, Any]:
    try:
        await client.ping()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


async def _check_vllm() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(_vllm_health_url())
        return {"ok": r.status_code == 200, "status_code": r.status_code}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


async def _check_milvus() -> dict[str, Any]:
    try:
        await asyncio.to_thread(
            milvus_conn.connect,
            alias="health",
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )
        await asyncio.to_thread(milvus_conn.disconnect, alias="health")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


async def _check_neo4j() -> dict[str, Any]:
    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        async with driver.session() as session:
            res = await session.run("RETURN 1 AS x")
            row = await res.single()
        await driver.close()
        return {"ok": bool(row and row["x"] == 1)}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:200]}


async def _check_streams(client: redis_async.Redis) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for stream in settings.upstream_streams:
        try:
            info = await client.xinfo_stream(stream)
            out[stream] = {"ok": True, "length": info.get("length", 0)}
        except Exception as e:
            msg = str(e).lower()
            out[stream] = {
                "ok": False,
                "reason": "stream not found (mock mode)" if "no such key" in msg else str(e)[:200],
            }
    return out


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    redis_client: redis_async.Redis = request.app.state.redis
    deps_redis, deps_vllm, deps_milvus, deps_neo4j = await asyncio.gather(
        _check_redis(redis_client),
        _check_vllm(),
        _check_milvus(),
        _check_neo4j(),
    )
    upstream = await _check_streams(redis_client)
    return {
        "status": "ok",
        "service": settings.service_name,
        "engines": {
            "financial_fraud": "not_loaded",
            "shareholder_integrity": "not_loaded",
            "related_party": "not_loaded",
        },
        "dependencies": {
            "redis": deps_redis,
            "vllm": deps_vllm,
            "milvus": deps_milvus,
            "neo4j": deps_neo4j,
        },
        "upstream_streams": upstream,
    }


@router.get("/api/decision-gate/health")
async def decision_gate_health() -> dict[str, Any]:
    return {
        "status": "initializing",
        "phase": "stage_1_w01",
        "note": "decision_gate 将在 step_08 完整上线",
    }
