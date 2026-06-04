#!/usr/bin/env python3
"""从 MY_HOLDINGS_YAML 导入 portfolio 至 user_positions（一次性）。

[Ref: 28_ §5.3]
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> int:
    from apps.common.holdings_sot import load_holdings_sot
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.modules.executing.positions import upsert_position
    from apps.copilot.modules.executing.universe import upsert_executing_collect

    await init_db()
    sot = load_holdings_sot()
    n = 0
    async with AsyncSessionLocal() as session:
        for h in sot.holdings:
            if getattr(h, "role", "") != "portfolio" and not (
                h.quantity and h.cost_price
            ):
                continue
            if not h.active:
                continue
            await upsert_position(
                session,
                {
                    "symbol": h.symbol,
                    "name": h.name,
                    "quantity": float(h.quantity or 0),
                    "cost_price": float(h.cost_price or 0),
                    "source": "import_yaml",
                    "notes": h.notes or "",
                },
            )
            if h.symbol == "601138":
                await upsert_executing_collect(session, h.symbol, enabled=True)
            n += 1
        await session.commit()
    print(f"✅ 导入 {n} 条 portfolio → user_positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
