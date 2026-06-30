# apps/industry_graph/backend/engine/neo4j_client.py
"""Neo4j 图数据库客户端封装"""

import logging
from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from ..config import settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    """获取或初始化 Neo4j 驱动（单例）"""
    global _driver
    if _driver is None:
        logger.info(f"Neo4j 连接中: {settings.NEO4J_URI}")
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            max_connection_lifetime=3600,
            max_connection_pool_size=10,
        )
        # 验证连接
        await _driver.verify_connectivity()
        logger.info("Neo4j 连接成功")
    return _driver


async def close_driver():
    """关闭 Neo4j 驱动"""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j 连接已关闭")


async def run_cypher(query: str, params: dict = None) -> list:
    """执行 Cypher 查询并返回记录列表"""
    driver = await get_driver()
    async with driver.session(database=settings.NEO4J_DATABASE) as session:
        result = await session.run(query, params or {})
        records = await result.data()
        return records


async def get_session() -> AsyncSession:
    """获取 Neo4j 会话（context manager）"""
    driver = await get_driver()
    return driver.session(database=settings.NEO4J_DATABASE)
