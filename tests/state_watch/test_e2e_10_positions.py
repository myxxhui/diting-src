"""10 持仓 e2e — 状态切换准确率 ≥0.90。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 F]
"""
from __future__ import annotations

from unittest.mock import MagicMock

from apps.state_watch.health.orchestrator import HealthOrchestrator
from apps.state_watch.events.publisher import HealthChangePublisher
from tests.state_watch.fixtures.positions_10 import POSITIONS_10


def test_e2e_10_positions_accuracy() -> None:
    mock_redis = MagicMock()
    mock_redis.xadd.return_value = "e2e-0"
    orch = HealthOrchestrator(publisher=HealthChangePublisher(redis_client=mock_redis))

    correct = 0
    total = len(POSITIONS_10)
    for case in POSITIONS_10:
        result = orch.process(case.snapshot, publish=False)
        if result.new_state == case.expected_state:
            correct += 1
        else:
            print(
                f"  mismatch {case.symbol}: expected={case.expected_state} "
                f"got={result.new_state} rule={result.rule_id}"
            )

    accuracy = correct / total
    assert accuracy >= 0.90, f"准确率 {accuracy:.2%} < 0.90 ({correct}/{total})"
