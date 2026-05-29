"""Redis Stream 事件发布器（同步 redis-py）。

负责向 events:deep_strike:thesis_proposed 投递 ThesisProposedEvent。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_04_利润截留扫描仪剧本.md §3.5.4 M6]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEEP_STRIKE_THESIS_STREAM = "events:deep_strike:thesis_proposed"
DEEP_STRIKE_TIMER_STREAM = "events:deep_strike:timer_signal"


class RedisPublisher:
    """同步 Redis Stream 发布器。

    在 Redis 不可用时退入本地队列（in-memory）并记录告警，
    保证 Mapper 主流程不因 Redis 异常中断。
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._url = redis_url
        self._local_queue: list[dict] = []
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            import redis  # 延迟导入，避免测试不需要 Redis 时报错

            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def xadd(
        self,
        stream: str,
        payload: dict[str, Any],
        maxlen: int = 10_000,
    ) -> Optional[str]:
        """向 stream 写入一条消息，返回 msg_id；失败时落本地队列。"""
        data = {"json": json.dumps(payload, ensure_ascii=False, default=str)}
        try:
            client = self._get_client()
            msg_id: str = client.xadd(stream, data, maxlen=maxlen)
            logger.debug("[publisher] xadd stream=%s msg_id=%s", stream, msg_id)
            return msg_id
        except Exception as exc:
            logger.warning(
                "[publisher] redis xadd 失败 stream=%s: %s；退入本地队列",
                stream,
                exc,
            )
            self._local_queue.append({"stream": stream, "payload": payload})
            return None

    def publish_mapper_thesis(
        self,
        *,
        cluster_id: str,
        symbol: str,
        target_symbol: str,
        elasticity_ratio: float,
        market_cap_tier: str,
        scan_date: str,
        mapper_output_id: Optional[int] = None,
    ) -> Optional[str]:
        """投递 The Mapper 产出的 thesis_proposed 事件。"""
        payload: dict[str, Any] = {
            "event_type": "mapper_thesis_proposed",
            "source": "the_mapper",
            "cluster_id": cluster_id,
            "symbol": symbol,
            "target_symbol": target_symbol,
            "elasticity_ratio": elasticity_ratio,
            "market_cap_tier": market_cap_tier,
            "scan_date": scan_date,
            "mapper_output_id": mapper_output_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return self.xadd(DEEP_STRIKE_THESIS_STREAM, payload)

    def publish_timer_signal(
        self,
        *,
        thesis_card_id: str,
        symbol: str,
        stage: str,
        evidence_url: str = "",
        financial_report_date: str = "",
        event_id: str | None = None,
    ) -> Optional[str]:
        """投递 The Timer 三段窗口信号（供 D4 SP5 消费）。"""
        import uuid

        payload: dict[str, Any] = {
            "event_type": "timer_signal",
            "event_id": event_id or str(uuid.uuid4()),
            "thesis_card_id": thesis_card_id,
            "symbol": symbol,
            "stage": stage,
            "evidence_url": evidence_url,
            "financial_report_date": financial_report_date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "execute_mode": "advisory",
        }
        return self.xadd(DEEP_STRIKE_TIMER_STREAM, payload)

    def publish_timer_phases_from_card(
        self,
        *,
        thesis_card_id: str,
        symbol: str,
        timer_signal: dict[str, Any],
    ) -> list[str]:
        """按当前 active stage 投递一条 timer_signal（启动期简化：取 main_wave 若存在）。"""
        msg_ids: list[str] = []
        three = timer_signal.get("three_phases") or timer_signal
        stage = "main_wave"
        if isinstance(three, dict):
            if three.get("main_wave") or three.get("main_surge"):
                stage = "main_wave"
            elif three.get("incubation"):
                stage = "left_accumulate"
            elif three.get("retreat"):
                stage = "retreat"
        anchors = timer_signal.get("cycle_anchors") or []
        evidence_url = ""
        financial_report_date = ""
        if anchors and isinstance(anchors, list):
            first = anchors[0]
            if isinstance(first, dict):
                financial_report_date = str(first.get("expected_window", [""])[0])
        mid = self.publish_timer_signal(
            thesis_card_id=thesis_card_id,
            symbol=symbol,
            stage=stage,
            evidence_url=evidence_url,
            financial_report_date=financial_report_date,
        )
        if mid:
            msg_ids.append(mid)
        return msg_ids

    def flush_local_queue(self) -> int:
        """尝试将本地队列中积压的消息重新发布；返回成功数。"""
        if not self._local_queue:
            return 0
        flushed = 0
        remaining = []
        for item in self._local_queue:
            msg_id = self.xadd(item["stream"], item["payload"])
            if msg_id:
                flushed += 1
            else:
                remaining.append(item)
        self._local_queue = remaining
        return flushed

    @property
    def pending_count(self) -> int:
        return len(self._local_queue)


# 模块级默认实例（Mapper 直接调用；测试可替换）
_default_publisher: Optional[RedisPublisher] = None


def get_publisher(redis_url: str = "redis://localhost:6379/0") -> RedisPublisher:
    global _default_publisher
    if _default_publisher is None:
        _default_publisher = RedisPublisher(redis_url)
    return _default_publisher
