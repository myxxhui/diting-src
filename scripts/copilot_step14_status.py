#!/usr/bin/env python3
"""step_14 状态快照。"""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select


async def main() -> None:
    from apps.copilot.db.database import AsyncSessionLocal, init_db
    from apps.copilot.db.models import (
        ModelProfile,
        RadarCandidate,
        RadarScan,
        StageArtifact,
        WorkspaceArtifact,
    )

    await init_db()
    async with AsyncSessionLocal() as session:
        scans = await session.scalar(select(func.count()).select_from(RadarScan)) or 0
        cands = await session.scalar(select(func.count()).select_from(RadarCandidate)) or 0
        arts = await session.scalar(select(func.count()).select_from(StageArtifact)) or 0
        wa = await session.scalar(select(func.count()).select_from(WorkspaceArtifact)) or 0
        mp = await session.scalar(select(func.count()).select_from(ModelProfile)) or 0
        print(f"radar_scans={scans} candidates={cands} stage_artifacts={arts} workspace_artifacts={wa} model_profile={mp}")


if __name__ == "__main__":
    asyncio.run(main())
