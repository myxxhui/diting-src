"""push_level / HealthOrchestrator / HealthChangeEvent 单测。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1]
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from apps.state_watch.events.health_change import HealthChangeEvent
from apps.state_watch.events.publisher import HealthChangePublisher
from apps.state_watch.health.orchestrator import HealthOrchestrator, PositionSnapshot
from apps.state_watch.health.push_level import health_to_push_level
from tests.state_watch.fixtures.positions_10 import POSITIONS_10


class TestPushLevel:
    @pytest.mark.parametrize(
        "score,level",
        [
            (0, 3),
            (29, 3),
            (30, 2),
            (59, 2),
            (60, 1),
            (79, 1),
            (80, 0),
            (100, 0),
        ],
    )
    def test_boundaries(self, score: float, level: int) -> None:
        assert health_to_push_level(score) == level


class TestHealthChangeEvent:
    def test_stream_payload_d0_d4_fields(self) -> None:
        ev = HealthChangeEvent(
            symbol="601138",
            name="工业富联",
            old_state="growing",
            new_state="warning",
            old_health=80.0,
            new_health=55.0,
            narrative_label="neutral",
            narrative_invalid_count=0,
        )
        p = ev.to_stream_payload()
        for key in (
            "event_id",
            "symbol",
            "new_state",
            "narrative_label",
            "narrative_invalid_count",
            "old_health",
            "new_health",
            "push_level",
            "change_reason",
            "node_state",
            "timestamp",
        ):
            assert key in p


class TestHealthOrchestrator:
    def test_t2_growing_to_warning_publishes(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "1-0"
        pub = HealthChangePublisher(redis_client=mock_redis)
        orch = HealthOrchestrator(publisher=pub)
        snap = POSITIONS_10[0].snapshot
        result = orch.process(snap)
        assert result.new_state == "warning"
        assert result.rule_id == "T2"
        assert result.published is True
        assert mock_redis.xadd.called

    def test_no_transition_no_publish_when_push_unchanged(self) -> None:
        mock_redis = MagicMock()
        pub = HealthChangePublisher(redis_client=mock_redis)
        orch = HealthOrchestrator(publisher=pub)
        snap = PositionSnapshot(
            symbol="300499",
            state="growing",
            health_score=82.0,
            push_level=0,
        )
        result = orch.process(snap)
        assert result.new_state == "growing"
        assert result.published is False
        mock_redis.xadd.assert_not_called()

    def test_push_only_change_publishes(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "2-0"
        pub = HealthChangePublisher(redis_client=mock_redis)
        orch = HealthOrchestrator(publisher=pub)
        snap = PositionSnapshot(
            symbol="601138",
            state="growing",
            health_score=55.0,
            push_level=0,
        )
        result = orch.process(snap)
        assert result.push_changed is True
        assert result.published is True


class TestPublisher:
    def test_xadd_uses_json_field(self) -> None:
        mock_redis = MagicMock()
        mock_redis.xadd.return_value = "99-0"
        pub = HealthChangePublisher(redis_client=mock_redis)
        ev = HealthChangeEvent(symbol="601138", new_state="exit", new_health=20.0)
        msg_id = pub.publish(ev)
        assert msg_id == "99-0"
        fields = mock_redis.xadd.call_args[0][1]
        payload = json.loads(fields["json"])
        assert payload["symbol"] == "601138"
