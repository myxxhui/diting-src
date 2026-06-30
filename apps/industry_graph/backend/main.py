# apps/industry_graph/backend/main.py
"""产业关系图谱 — FastAPI 服务主入口"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import settings
from .engine.neo4j_client import get_driver, close_driver
from .api import health, graph_query, graph_reason, graph_update, graph_snapshot

# ---- 日志配置 ----
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动：预热 Neo4j 连接
    logger.info("产业图谱服务启动中...")
    try:
        await get_driver()
        logger.info("Neo4j 连接就绪")
    except Exception as e:
        logger.warning(f"Neo4j 连接失败（服务仍可启动）: {e}")
    yield
    # 关闭：释放连接
    await close_driver()
    logger.info("产业图谱服务已关闭")


app = FastAPI(
    title="产业关系图谱系统",
    description="智能产业关系拓扑图 + LLM 驱动变量推演引擎",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router)
app.include_router(graph_query.router)
app.include_router(graph_reason.router)
app.include_router(graph_update.router)
app.include_router(graph_snapshot.router)

# 静态文件（前端 SPA 构建产物）
import os
static_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    logger.info(f"前端静态文件: {static_dir}")


# ---- 统一异常处理 ----
class IndustryGraphError(Exception):
    def __init__(self, message: str, code: str, status_code: int = 500):
        self.message = message
        self.code = code
        self.status_code = status_code


@app.exception_handler(IndustryGraphError)
async def industry_graph_exception_handler(request, exc: IndustryGraphError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.code, "message": exc.message},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc: Exception):
    logger.exception(f"未处理异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_ERROR", "message": str(exc)},
    )
