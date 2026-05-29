"""6 条状态转移规则(T1~T6).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from apps.state_watch.state_machine.states import NodeState, is_valid_transition


@dataclass
class TransitionContext:
    current_state: NodeState
    health_score: float
    narrative_label: str = "neutral"
    narrative_invalid_count: int = 0
    held_for_days: int = 0
    health_above_75_days: int = 0


@dataclass
class TransitionResult:
    target_state: Optional[NodeState]
    rule_id: Optional[str]
    reason: str


def _t1_growing_to_stable(ctx: TransitionContext) -> Optional[TransitionResult]:
    if (
        ctx.current_state == NodeState.GROWING
        and ctx.held_for_days > 180
        and ctx.narrative_label != "contradiction"
    ):
        return TransitionResult(
            NodeState.STABLE,
            "T1",
            f"持仓 {ctx.held_for_days}d > 180d 且 thesis 仍成立",
        )
    return None


def _t2_growing_to_warning(ctx: TransitionContext) -> Optional[TransitionResult]:
    if ctx.current_state == NodeState.GROWING and ctx.health_score < 60:
        return TransitionResult(NodeState.WARNING, "T2", f"GROWING 健康度 {ctx.health_score:.1f} < 60")
    return None


def _t3_stable_to_warning(ctx: TransitionContext) -> Optional[TransitionResult]:
    if ctx.current_state == NodeState.STABLE and (
        ctx.health_score < 60 or ctx.narrative_label == "contradiction"
    ):
        reason = (
            f"健康度 {ctx.health_score:.1f} < 60"
            if ctx.health_score < 60
            else "叙事一致性 contradiction"
        )
        return TransitionResult(NodeState.WARNING, "T3", reason)
    return None


def _t4_stable_to_exit(ctx: TransitionContext) -> Optional[TransitionResult]:
    if ctx.current_state == NodeState.STABLE and ctx.narrative_invalid_count >= 3:
        return TransitionResult(
            NodeState.EXIT,
            "T4",
            f"thesis 完全失效(narrative<30 连续 {ctx.narrative_invalid_count} 次)",
        )
    return None


def _t5_warning_to_stable(ctx: TransitionContext) -> Optional[TransitionResult]:
    if (
        ctx.current_state == NodeState.WARNING
        and ctx.health_score > 75
        and ctx.health_above_75_days >= 7
    ):
        return TransitionResult(
            NodeState.STABLE,
            "T5",
            f"WARNING 恢复 健康度 {ctx.health_score:.1f}>75 持续 {ctx.health_above_75_days}d",
        )
    return None


def _t6_warning_to_exit(ctx: TransitionContext) -> Optional[TransitionResult]:
    if ctx.current_state == NodeState.WARNING and (
        ctx.health_score < 30 or ctx.narrative_invalid_count >= 3
    ):
        reason = (
            f"健康度 {ctx.health_score:.1f} < 30"
            if ctx.health_score < 30
            else "thesis 失效"
        )
        return TransitionResult(NodeState.EXIT, "T6", reason)
    return None


_RULES = [
    _t1_growing_to_stable,
    _t2_growing_to_warning,
    _t3_stable_to_warning,
    _t4_stable_to_exit,
    _t5_warning_to_stable,
    _t6_warning_to_exit,
]


def evaluate(ctx: TransitionContext) -> TransitionResult:
    for rule in _RULES:
        result = rule(ctx)
        if result is not None:
            if result.target_state and not is_valid_transition(ctx.current_state, result.target_state):
                continue
            return result
    return TransitionResult(None, None, "no transition")
