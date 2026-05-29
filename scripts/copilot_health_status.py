"""copilot health_records / event_logs 数量快照."""
import asyncio

from sqlalchemy import func, select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import EventLog, HealthRecord


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as s:
        hr = await s.scalar(select(func.count()).select_from(HealthRecord))
        el = await s.scalar(select(func.count()).select_from(EventLog))
        print(f"  health_records={hr} event_logs={el}")


if __name__ == "__main__":
    asyncio.run(main())
