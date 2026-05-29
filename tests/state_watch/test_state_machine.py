"""状态机 4 态 + 6 条转移单元测试.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from apps.state_watch.state_machine.graph import get_graph
from apps.state_watch.state_machine.states import NodeState, VALID_TRANSITIONS, is_valid_transition
from apps.state_watch.state_machine.transitions import TransitionContext, evaluate


class TestStates:
    def test_node_state_values(self) -> None:
        assert NodeState.GROWING.value == "growing"
        assert NodeState.STABLE.value == "stable"
        assert NodeState.WARNING.value == "warning"
        assert NodeState.EXIT.value == "exit"

    def test_exit_is_terminal(self) -> None:
        assert VALID_TRANSITIONS[NodeState.EXIT] == []

    def test_growing_can_skip_to_warning(self) -> None:
        assert is_valid_transition(NodeState.GROWING, NodeState.WARNING)

    def test_growing_cannot_skip_to_exit(self) -> None:
        assert not is_valid_transition(NodeState.GROWING, NodeState.EXIT)


class TestTransitionRules:
    def test_t1_growing_to_stable(self) -> None:
        ctx = TransitionContext(
            current_state=NodeState.GROWING,
            health_score=85,
            narrative_label="entailment",
            held_for_days=200,
        )
        result = evaluate(ctx)
        assert result.target_state == NodeState.STABLE
        assert result.rule_id == "T1"

    def test_t2_growing_to_warning(self) -> None:
        ctx = TransitionContext(current_state=NodeState.GROWING, health_score=55)
        result = evaluate(ctx)
        assert result.target_state == NodeState.WARNING
        assert result.rule_id == "T2"

    def test_t3_stable_to_warning_by_health(self) -> None:
        ctx = TransitionContext(current_state=NodeState.STABLE, health_score=55)
        result = evaluate(ctx)
        assert result.target_state == NodeState.WARNING
        assert result.rule_id == "T3"

    def test_t3_stable_to_warning_by_contradiction(self) -> None:
        ctx = TransitionContext(
            current_state=NodeState.STABLE,
            health_score=70,
            narrative_label="contradiction",
        )
        result = evaluate(ctx)
        assert result.target_state == NodeState.WARNING
        assert result.rule_id == "T3"

    def test_t4_stable_to_exit(self) -> None:
        ctx = TransitionContext(
            current_state=NodeState.STABLE,
            health_score=65,
            narrative_invalid_count=3,
        )
        result = evaluate(ctx)
        assert result.target_state == NodeState.EXIT
        assert result.rule_id == "T4"

    def test_t5_warning_to_stable(self) -> None:
        ctx = TransitionContext(
            current_state=NodeState.WARNING,
            health_score=80,
            health_above_75_days=10,
        )
        result = evaluate(ctx)
        assert result.target_state == NodeState.STABLE
        assert result.rule_id == "T5"

    def test_t6_warning_to_exit_by_health(self) -> None:
        ctx = TransitionContext(current_state=NodeState.WARNING, health_score=25)
        result = evaluate(ctx)
        assert result.target_state == NodeState.EXIT
        assert result.rule_id == "T6"

    def test_no_transition_when_stable_and_healthy(self) -> None:
        ctx = TransitionContext(current_state=NodeState.STABLE, health_score=70)
        result = evaluate(ctx)
        assert result.target_state is None


class TestLangGraph:
    def test_graph_runs_growing_to_warning(self) -> None:
        g = get_graph()
        out = g.invoke(
            {
                "node_id": "n1",
                "current_state": "growing",
                "health_score": 50.0,
                "narrative_label": "neutral",
            }
        )
        assert out["target_state"] == "warning"
        assert out["rule_id"] == "T2"

    def test_graph_idle_when_no_rule(self) -> None:
        g = get_graph()
        out = g.invoke(
            {
                "node_id": "n2",
                "current_state": "growing",
                "health_score": 90.0,
                "narrative_label": "neutral",
                "held_for_days": 1,
            }
        )
        assert out["target_state"] == "growing"
        assert out["rule_id"] == "NONE"
