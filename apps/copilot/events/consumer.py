"""通用 Redis Stream 消费者(消费组 'copilot_group',含 xack)。

启动方式: python -m apps.copilot.events.consumer

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
[Ref: 03_/00_维度零/.../02_技术方案与代码架构.md#三-核心模块设计.3.1]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.config import settings
from apps.copilot.db.database import AsyncSessionLocal, init_db

logger = logging.getLogger("copilot.consumer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

Handler = Callable[[AsyncSession, dict[str, Any], str], Awaitable[None]]

CONSUMER_GROUP = "copilot_group"
CONSUMER_NAME = os.environ.get("COPILOT_CONSUMER_NAME", "copilot_1")


class EventConsumer:
    """订阅多个 stream,通过消费组拉取,处理后 xack。"""

    def __init__(self, redis_url: str, streams: list[str]) -> None:
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.streams = streams
        self.handlers: dict[str, Handler] = {}

    def register(self, stream: str, handler: Handler) -> None:
        self.handlers[stream] = handler

    async def _ensure_groups(self) -> None:
        for s in self.streams:
            try:
                await self.redis.xgroup_create(s, CONSUMER_GROUP, id="0", mkstream=True)
                logger.info("created group %s on %s", CONSUMER_GROUP, s)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def consume_forever(self, block_ms: int = 1000, batch: int = 16) -> None:
        await self._ensure_groups()
        while True:
            try:
                entries = await self.redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=CONSUMER_NAME,
                    streams={s: ">" for s in self.streams},
                    count=batch,
                    block=block_ms,
                )
            except redis.ConnectionError as exc:
                logger.warning("redis disconnected: %s; retry in 3s", exc)
                await asyncio.sleep(3)
                continue

            if not entries:
                continue

            async with AsyncSessionLocal() as session:
                for stream, messages in entries:
                    handler = self.handlers.get(stream)
                    if not handler:
                        logger.warning(
                            "no handler for %s, skipping %d msgs",
                            stream,
                            len(messages),
                        )
                        for msg_id, _ in messages:
                            await self.redis.xack(stream, CONSUMER_GROUP, msg_id)
                        continue
                    for msg_id, data in messages:
                        try:
                            payload = _parse(data)
                            await handler(session, payload, msg_id)
                            await self.redis.xack(stream, CONSUMER_GROUP, msg_id)
                        except Exception:
                            logger.exception("handler failed for %s %s", stream, msg_id)


def _parse(data: dict[str, str]) -> dict[str, Any]:
    """Redis Stream 字段全部为 str,允许单一 'json' 字段或多字段。"""
    if "json" in data:
        return json.loads(data["json"])
    parsed: dict[str, Any] = {}
    for k, v in data.items():
        try:
            parsed[k] = json.loads(v)
        except (TypeError, ValueError):
            parsed[k] = v
    return parsed


async def _main() -> None:
    from apps.copilot.events.handlers.health_change import handle_health_change
    from apps.copilot.events.handlers.mapper_thesis import handle_mapper_thesis
    from apps.copilot.events.handlers.thesis_proposed import handle_thesis_proposed

    await init_db()
    consumer = EventConsumer(
        redis_url=settings.redis_url,
        streams=[
            "events:monitor:health_change",
            "events:thrust:thesis_proposed",
            # The Mapper（D2 step_04）产出候选
            "events:deep_strike:thesis_proposed",
        ],
    )
    consumer.register("events:monitor:health_change", handle_health_change)
    consumer.register("events:thrust:thesis_proposed", handle_thesis_proposed)
    consumer.register("events:deep_strike:thesis_proposed", handle_mapper_thesis)
    logger.info("copilot event consumer started, listening %s", consumer.streams)
    await consumer.consume_forever()


if __name__ == "__main__":
    asyncio.run(_main())
