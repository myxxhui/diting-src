"""exit_engine Redis Stream 消费器（XREADGROUP + xack）。

[Ref: 03_/04_维度四/.../step_05 §7.1 B/I HealthChangeConsumer / TimerSignalConsumer]
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import redis
from redis.exceptions import ResponseError

from apps.exit_engine.config import settings
from apps.exit_engine.db.session import SessionLocal
from apps.exit_engine.services.stream_consumer import (
    HEALTH_CHANGE_STREAM,
    HEALTH_CONSUMER_GROUP,
    SP5_CONSUMER_GROUP,
    TIMER_SIGNAL_STREAM,
    ConsumerProcessResult,
    parse_stream_payload,
    process_health_change,
    process_timer_signal,
)

logger = logging.getLogger(__name__)


class ExitStreamRedisRunner:
    """同步 Redis Stream 消费器：ensure_group → xreadgroup → 处理 → xack。"""

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: Optional[redis.Redis] = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def ping(self) -> bool:
        return bool(self.client.ping())

    def ensure_group(self, stream: str, group: str) -> None:
        try:
            self.client.xgroup_create(stream, group, id="0", mkstream=True)
            logger.info("created consumer group %s on %s", group, stream)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def ensure_all_groups(self) -> None:
        self.ensure_group(HEALTH_CHANGE_STREAM, HEALTH_CONSUMER_GROUP)
        self.ensure_group(TIMER_SIGNAL_STREAM, SP5_CONSUMER_GROUP)

    def poll_once(
        self,
        stream: str,
        group: str,
        *,
        consumer_name: str = "exit_engine_1",
        block_ms: int = 2000,
        count: int = 16,
    ) -> list[ConsumerProcessResult]:
        """拉取一批新消息并处理；返回 ConsumerProcessResult 列表。"""
        self.ensure_group(stream, group)
        entries = self.client.xreadgroup(
            groupname=group,
            consumername=consumer_name,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
        if not entries:
            return []

        results: list[ConsumerProcessResult] = []
        db = SessionLocal()
        try:
            for _stream_name, messages in entries:
                for msg_id, data in messages:
                    payload = parse_stream_payload(data)
                    if stream == HEALTH_CHANGE_STREAM:
                        result = process_health_change(db, payload, msg_id=msg_id)
                    elif stream == TIMER_SIGNAL_STREAM:
                        result = process_timer_signal(db, payload, msg_id=msg_id)
                    else:
                        logger.warning("unknown stream %s", stream)
                        self.client.xack(stream, group, msg_id)
                        continue
                    self.client.xack(stream, group, msg_id)
                    results.append(result)
        finally:
            db.close()
        return results

    def publish_and_consume(
        self,
        stream: str,
        group: str,
        payload: dict[str, Any],
        *,
        consumer_name: str = "exit_e2e",
    ) -> tuple[Optional[str], Optional[ConsumerProcessResult]]:
        """xadd → poll_once（同 stream）；用于 e2e 联调。"""
        import json

        data = {"json": json.dumps(payload, ensure_ascii=False, default=str)}
        msg_id: str = self.client.xadd(stream, data)
        results = self.poll_once(stream, group, consumer_name=consumer_name, block_ms=3000)
        matched = next((r for r in results if r.handled), None)
        return msg_id, matched
