"""health_change_publisher 单测。

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_05_NLI叙事一致性.md §7.1]
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.state_watch.events.health_change_publisher import (
    HEALTH_CHANGE_STREAM,
    map_score_to_state,
    publish_health_change,
)


# ---------- map_score_to_state ----------

class TestMapScoreToState:
    def test_below_30_is_exit(self):
        assert map_score_to_state(0.0) == "exit"
        assert map_score_to_state(29.9) == "exit"

    def test_30_to_60_is_warning(self):
        assert map_score_to_state(30.0) == "warning"
        assert map_score_to_state(59.9) == "warning"

    def test_60_and_above_is_growing(self):
        assert map_score_to_state(60.0) == "growing"
        assert map_score_to_state(100.0) == "growing"


# ---------- publish_health_change ----------

@pytest.mark.asyncio
class TestPublishHealthChange:
    async def test_xadd_called_with_correct_payload(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1234567890-0")

        msg_id = await publish_health_change(
            mock_redis,
            symbol="601138",
            new_state="exit",
            health_score=20.0,
            prev_score=85.0,
            narrative_label="叙事漂移",
            narrative_invalid_count=3,
            source_probe="financial",
        )

        assert mock_redis.xadd.called
        call_args = mock_redis.xadd.call_args
        stream_key = call_args[0][0]
        data = call_args[0][1]
        assert stream_key == HEALTH_CHANGE_STREAM
        assert "json" in data
        payload = json.loads(data["json"])
        assert payload["symbol"] == "601138"
        assert payload["new_state"] == "exit"
        assert payload["health_score"] == 20.0
        assert payload["prev_score"] == 85.0
        assert payload["narrative_label"] == "叙事漂移"
        assert payload["narrative_invalid_count"] == 3
        assert "event_id" in payload
        assert "emitted_at" in payload

    async def test_returns_msg_id_on_success(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1779999999-0")

        result = await publish_health_change(
            mock_redis,
            symbol="300308",
            new_state="warning",
            health_score=45.0,
            prev_score=70.0,
        )
        assert result == "1779999999-0"

    async def test_returns_none_on_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis connection refused"))

        result = await publish_health_change(
            mock_redis,
            symbol="300308",
            new_state="exit",
            health_score=10.0,
            prev_score=80.0,
        )
        # 不抛出，返回 None
        assert result is None

    async def test_event_id_is_unique_per_call(self):
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value=b"1-0")

        event_ids: list[str] = []
        for i in range(5):
            await publish_health_change(
                mock_redis,
                symbol="601088",
                new_state="growing",
                health_score=80.0,
                prev_score=75.0,
            )
            call_data = mock_redis.xadd.call_args[0][1]
            payload = json.loads(call_data["json"])
            event_ids.append(payload["event_id"])

        assert len(set(event_ids)) == 5, "每次 publish 的 event_id 必须唯一"

    async def test_stream_key_constant(self):
        assert HEALTH_CHANGE_STREAM == "events:monitor:health_change"
