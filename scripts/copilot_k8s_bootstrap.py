"""K8s Pod 启动前：建表并从 SoT 导入持仓（含 601138 等）。"""
from __future__ import annotations

import asyncio
import logging

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.services.sot_importer import import_sot_holdings

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("copilot.k8s.bootstrap")


async def _main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        result = await import_sot_holdings(session, user_id="default")
        await session.commit()
    log.info("SoT 导入完成: %s", result)


if __name__ == "__main__":
    asyncio.run(_main())
