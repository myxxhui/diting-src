# apps/industry_graph/backend/api/health.py
"""健康检查与就绪探针"""

from fastapi import APIRouter
from ..engine.neo4j_client import get_driver

router = APIRouter()


@router.get("/health", summary="存活探针")
async def health_check():
    """K8s liveness probe — 仅确认进程存活"""
    return {"status": "ok", "service": "industry-graph"}


@router.get("/ready", summary="就绪探针")
async def readiness_check():
    """K8s readiness probe — 确认 Neo4j 连接可用"""
    try:
        driver = await get_driver()
        await driver.verify_connectivity()
        return {"status": "ready", "neo4j": "connected"}
    except Exception as e:
        return {"status": "not_ready", "neo4j": str(e)}
