#!/usr/bin/env python3
"""CLI：从 SoT 导入 copilot holdings."""
from __future__ import annotations

import asyncio

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.services.sot_importer import import_sot_holdings


async def _main() -> None:
    await init_db()
    async with AsyncSessionLocal() as session:
        summary = await import_sot_holdings(session)
    print(f"✅ imported {summary['imported']} rows from {summary['source']}")
    print(f"   active symbols: {summary['active_symbols']}")


if __name__ == "__main__":
    asyncio.run(_main())
