# apps/industry_graph/backend/scripts/seed_data.py
"""CLI 入口：Python -m 调用导入种子数据"""

import asyncio
import logging
from ..services.graph_seed import seed_graph
from ..engine.neo4j_client import close_driver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    result = await seed_graph()
    logger.info(f"导入结果: {result}")
    await close_driver()


if __name__ == "__main__":
    asyncio.run(main())
