"""sell_signal Redis Stream 发布器。

[Ref: 03_/04_维度四/.../step_07_冲突处理与回测.md §7.1 C]
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import redis
from sqlalchemy.orm import Session

from apps.exit_engine.config import settings
from apps.exit_engine.models.failed_publish import FailedStreamPublishORM
from apps.exit_engine.models.sell_signal import SellSignalEvent
from apps.exit_engine.models.sell_signal_record import SellSignalRecordORM

logger = logging.getLogger(__name__)


class SellSignalPublisher:
    """XADD events:exit:sell_signal；失败落 failed_stream_publish。"""

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        stream_key: Optional[str] = None,
    ) -> None:
        self._client = redis_client
        self.stream_key = stream_key or settings.output_stream

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
        return self._client

    def publish(
        self,
        event: SellSignalEvent,
        *,
        session: Optional[Session] = None,
        triggered_protocols: Optional[list[str]] = None,
        user_id: str = "default",
    ) -> str:
        payload = event.to_stream_dict()
        try:
            msg_id: str = self.client.xadd(self.stream_key, payload)
        except Exception as exc:
            logger.error("sell_signal XADD 失败: %s", exc)
            if session is not None:
                session.add(
                    FailedStreamPublishORM(
                        stream_key=self.stream_key,
                        payload=json.dumps(payload, ensure_ascii=False),
                        error=str(exc),
                    )
                )
                session.commit()
            raise

        if session is not None:
            session.add(
                SellSignalRecordORM(
                    event_id=event.event_id,
                    stream_msg_id=msg_id,
                    symbol=event.symbol,
                    position_id=event.position_id,
                    signal_type=event.signal_type.value,
                    protocol=event.protocol,
                    trigger_price=event.trigger_price,
                    current_price=event.current_price,
                    advice=event.advice,
                    triggered_protocols=json.dumps(triggered_protocols or [event.protocol], ensure_ascii=False),
                    audit_id=event.audit_id or None,
                    user_id=user_id,
                )
            )
            session.commit()

        logger.info(
            "sell_signal 已发布 stream=%s msg_id=%s symbol=%s protocol=%s",
            self.stream_key,
            msg_id,
            event.symbol,
            event.protocol,
        )
        return msg_id
