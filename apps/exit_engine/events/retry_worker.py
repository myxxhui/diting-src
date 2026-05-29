"""failed_stream_publish 后台重试 worker（同步最小实现）。

[Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md §7.1 D]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.exit_engine.config import settings
from apps.exit_engine.models.failed_publish import FailedStreamPublishORM

logger = logging.getLogger(__name__)


class StreamRetryWorker:
    def __init__(
        self,
        session: Session,
        redis_client: Optional[redis.Redis] = None,
    ) -> None:
        self.session = session
        self._client = redis_client

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def retry_pending(self, *, limit: int = 50) -> int:
        stmt = (
            select(FailedStreamPublishORM)
            .where(FailedStreamPublishORM.retried_at.is_(None))
            .order_by(FailedStreamPublishORM.created_at.asc())
            .limit(limit)
        )
        rows = list(self.session.scalars(stmt).all())
        ok = 0
        for row in rows:
            try:
                payload = json.loads(row.payload)
                self.client.xadd(row.stream_key, payload)
                row.retried_at = datetime.now(timezone.utc)
                ok += 1
            except Exception as exc:
                row.error = f"{row.error} | retry_failed: {exc}"
                logger.warning("重试失败 id=%s: %s", row.id, exc)
        if rows:
            self.session.commit()
        return ok
