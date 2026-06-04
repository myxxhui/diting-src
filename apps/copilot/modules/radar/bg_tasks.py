"""旁路异步落库（stage_artifacts · 独立 DB 会话）。

[Ref: 27_ §1.4]
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import StageArtifact

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class BackgroundArtifactSink:
    """fire-and-forget stage artifact 写入；主链路不 await。"""

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []

    def fire(
        self,
        *,
        stage: str,
        model_id: str,
        payload: dict,
        symbol: str,
        scan_id: Optional[int] = None,
        candidate_id: Optional[int] = None,
        latency_ms: int = 0,
        token_cost: float = 0.0,
    ) -> None:
        task = asyncio.create_task(
            _save_artifact_bg(
                stage=stage,
                model_id=model_id,
                payload=payload,
                symbol=symbol,
                scan_id=scan_id,
                candidate_id=candidate_id,
                latency_ms=latency_ms,
                token_cost=token_cost,
            )
        )
        self._tasks.append(task)

    async def drain(self) -> None:
        """测试/CLI 用：等待已调度旁路任务完成。"""
        if not self._tasks:
            return
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


async def _save_artifact_bg(
    *,
    stage: str,
    model_id: str,
    payload: dict,
    symbol: str,
    scan_id: Optional[int],
    candidate_id: Optional[int],
    latency_ms: int,
    token_cost: float,
) -> None:
    # 略等主事务 commit 释放 SQLite 写锁（PostgreSQL 无影响）
    await asyncio.sleep(0.05)
    delay = 0.5
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            from apps.copilot.db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                art = StageArtifact(
                    symbol=symbol,
                    scan_id=scan_id,
                    candidate_id=candidate_id,
                    workspace="radar",
                    stage=stage,
                    model_id=model_id,
                    input_refs=[],
                    payload_json=payload,
                    latency_ms=latency_ms,
                    token_cost=token_cost,
                )
                session.add(art)
                await session.commit()
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "旁路 artifact 写入失败 stage=%s symbol=%s attempt=%s: %s",
                stage,
                symbol,
                attempt,
                exc,
            )
            if attempt >= _MAX_RETRIES:
                logger.error(
                    "旁路 artifact write_failed stage=%s symbol=%s scan_id=%s",
                    stage,
                    symbol,
                    scan_id,
                )
                return
            await asyncio.sleep(delay)
            delay *= 2


async def save_artifact_sync(
    session: AsyncSession,
    *,
    stage: str,
    model_id: str,
    payload: dict,
    symbol: str,
    scan_id: Optional[int] = None,
    candidate_id: Optional[int] = None,
    input_refs: Optional[list[int]] = None,
    latency_ms: int = 0,
    token_cost: float = 0.0,
) -> StageArtifact:
    """同步落库（collect-only 等无 scan 旁路场景仍可用）。"""
    art = StageArtifact(
        symbol=symbol,
        scan_id=scan_id,
        candidate_id=candidate_id,
        workspace="radar",
        stage=stage,
        model_id=model_id,
        input_refs=input_refs or [],
        payload_json=payload,
        latency_ms=latency_ms,
        token_cost=token_cost,
    )
    session.add(art)
    await session.flush()
    return art
