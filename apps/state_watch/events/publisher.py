"""health_change Redis Stream 发布器（同步 · MAXLEN · 失败兜底）。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 B]
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import redis
from sqlalchemy.orm import Session

from apps.state_watch.events.health_change import HealthChangeEvent

logger = logging.getLogger(__name__)

HEALTH_CHANGE_STREAM = "events:monitor:health_change"
STREAM_MAXLEN = 10_000


class HealthChangePublisher:
    """XADD events:monitor:health_change；失败落 failed_stream_publish。"""

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        redis_url: Optional[str] = None,
        stream_key: str = HEALTH_CHANGE_STREAM,
    ) -> None:
        self._client = redis_client
        self._redis_url = redis_url
        self.stream_key = stream_key

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            from apps.state_watch.config import settings

            url = self._redis_url or settings.redis_url
            self._client = redis.from_url(url, decode_responses=True)
        return self._client

    def publish(
        self,
        event: HealthChangeEvent,
        *,
        session: Optional[Session] = None,
    ) -> Optional[str]:
        fields = event.to_redis_fields()
        try:
            msg_id: str = self.client.xadd(
                self.stream_key,
                fields,
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
            logger.info(
                "health_change 已发布 symbol=%s %s→%s msg_id=%s",
                event.symbol,
                event.old_state,
                event.new_state,
                msg_id,
            )
            return msg_id
        except Exception as exc:
            logger.warning("health_change XADD 失败: %s", exc)
            if session is not None:
                from apps.state_watch.db.models import FailedStreamPublish

                session.add(
                    FailedStreamPublish(
                        stream_key=self.stream_key,
                        payload=json.dumps(event.to_stream_payload(), ensure_ascii=False),
                        error=str(exc),
                    )
                )
                session.commit()
            return None
