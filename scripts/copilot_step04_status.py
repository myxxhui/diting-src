"""D0 copilot step04 推荐池状态脚本。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_04]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> None:
    from sqlalchemy import func, select

    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import EventLog, ThesisCard

    await init_db()
    async with AsyncSessionLocal() as s:
        total = await s.scalar(select(func.count()).select_from(ThesisCard))
        mapper = await s.scalar(
            select(func.count())
            .select_from(ThesisCard)
            .where(ThesisCard.thesis_id.like("mapper:%"))
        )
        evts = await s.scalar(
            select(func.count())
            .select_from(EventLog)
            .where(EventLog.stream_key == "events:deep_strike:thesis_proposed")
        )

    print(f"  thesis_cards 总数={total}（其中 mapper_candidate={mapper}）")
    print(f"  events:deep_strike:thesis_proposed event_logs={evts}")
    if total:
        print("  推荐池状态: 非空 ✅")
    else:
        print("  推荐池状态: 空池（BLOCKED-B 路径，等待 D2 thesis 真流）⚠️")
    print()
    print("▶ 做了什么: 查询 copilot DB thesis_cards + event_logs 快照")
    print(f"▶ 期望什么: 若 D2 Mapper 已运行，mapper_candidate ≥ 1")
    print(f"▶ 实际什么: total={total} mapper={mapper} events={evts}")


if __name__ == "__main__":
    asyncio.run(main())
