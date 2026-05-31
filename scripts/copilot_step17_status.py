"""step_17 状态快照：执行中 Campaign + 建议分布 + 安全 verdict。

[Ref: step_17_执行中仓位指导.md §9]
"""
from __future__ import annotations
import asyncio
import sys
sys.path.insert(0, ".")

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, ExecutionAdvice
from sqlalchemy import select, func


async def main():
    await init_db()

    async with AsyncSessionLocal() as s:
        camps = list(await s.scalars(
            select(Campaign).where(Campaign.status == "executing").limit(10)
        ))
        print(f"执行中 Campaign 数: {len(camps)}")

        total = await s.scalar(select(func.count()).select_from(ExecutionAdvice))
        print(f"全部执行建议记录数: {total}")

        rows = list(await s.scalars(
            select(ExecutionAdvice).order_by(ExecutionAdvice.as_of.desc()).limit(20)
        ))
        if not rows:
            print("暂无执行建议记录 · 请先运行 make copilot-step17-advise")
            return

        print("\n最近 20 条执行建议：")
        print(f"  {'symbol':<12} {'advice_action':<30} {'pnl%':<8} {'safety':<10} as_of")
        for r in rows:
            pnl = f"{r.unrealized_pnl_pct:+.1f}" if r.unrealized_pnl_pct is not None else "—"
            print(f"  {r.symbol:<12} {r.advice_action[:28]:<30} {pnl:<8} {r.safety_status:<10} {str(r.as_of)[:16]}")

        # 建议分布
        print("\n建议分布：")
        from collections import Counter
        counter = Counter(r.advice_action[:20] for r in rows)
        for action, cnt in counter.most_common():
            print(f"  {cnt:>3}x  {action}")

        # 安全状态
        print("\n安全扫描 verdict 分布：")
        safety_cnt = Counter(r.safety_status for r in rows)
        for k, v in safety_cnt.most_common():
            print(f"  {k}: {v}")

    print("\n✅ step17 status 完成")


if __name__ == "__main__":
    asyncio.run(main())
