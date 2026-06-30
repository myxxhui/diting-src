# apps/industry_graph/backend/config.py
"""产业图谱服务配置中心 — pydantic-settings 从 .env 读取"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """产业图谱后端配置"""

    # ---- Neo4j ----
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "changeme"
    NEO4J_DATABASE: str = "neo4j"

    # ---- PostgreSQL L2 ----
    PG_L2_DSN: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/diting"

    # ---- Redis ----
    REDIS_URL: str = "redis://localhost:6379/2"

    # ---- AI/LLM ----
    CLAUDE_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-3-5-sonnet-20240620"
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 4096

    # ---- 服务配置 ----
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8090
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "*"

    # ---- 功能开关 ----
    ENABLE_LLM_REASONING: bool = True
    ENABLE_AUTO_MONITOR: bool = False
    ENABLE_GRAPH_RAG: bool = False

    model_config = {
        "env_file": [".env", os.path.join(os.path.dirname(__file__), "..", ".env")],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
