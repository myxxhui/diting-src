"""HealthOrchestrator — 状态/push_level 变化时发布 health_change。

[Ref: 03_/03_维度三/.../step_07_health_change事件流与10持仓测试.md §7.1 D]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from apps.state_watch.events.health_change import HealthChangeEvent
from apps.state_watch.events.publisher import HealthChangePublisher
from apps.state_watch.health.push_level import health_to_push_level
from apps.state_watch.state_machine.states import NodeState
from apps.state_watch.state_machine.transitions import TransitionContext, evaluate


@dataclass
class PositionSnapshot:
    symbol: str
    name: str = ""
    node_id: str = ""
    state: str = "growing"
    health_score: float = 100.0
    previous_health: Optional[float] = None
    push_level: int = 0
    narrative_label: str = "neutral"
    narrative_invalid_count: int = 0
    held_for_days: int = 0
    health_above_75_days: int = 0
    thesis_status: str = "valid"
    sli_snapshot: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OrchestratorResult:
    symbol: str
    old_state: str
    new_state: str
    old_push_level: int
    new_push_level: int
    state_changed: bool
    push_changed: bool
    rule_id: str
    reason: str
    published: bool
    msg_id: Optional[str] = None


def _thesis_status(state: str) -> str:
    return "invalid" if state == "exit" else "valid"


class HealthOrchestrator:
    """评估 T1~T6；state 或 push_level 变化时 XADD。"""

    def __init__(self, publisher: Optional[HealthChangePublisher] = None) -> None:
        self.publisher = publisher or HealthChangePublisher()

    def process(
        self,
        snap: PositionSnapshot,
        *,
        publish: bool = True,
    ) -> OrchestratorResult:
        old_state = snap.state
        old_push = snap.push_level if snap.push_level is not None else health_to_push_level(snap.health_score)

        try:
            current = NodeState(old_state)
        except ValueError:
            current = NodeState.GROWING

        ctx = TransitionContext(
            current_state=current,
            health_score=snap.health_score,
            narrative_label=snap.narrative_label,
            narrative_invalid_count=snap.narrative_invalid_count,
            held_for_days=snap.held_for_days,
            health_above_75_days=snap.health_above_75_days,
        )
        tr = evaluate(ctx)

        new_state = old_state
        rule_id = ""
        reason = "no transition"
        if tr.target_state is not None and tr.target_state.value != old_state:
            new_state = tr.target_state.value
            rule_id = tr.rule_id or ""
            reason = tr.reason

        new_push = health_to_push_level(snap.health_score)
        state_changed = new_state != old_state
        push_changed = new_push != old_push
        published = False
        msg_id: Optional[str] = None

        if publish and (state_changed or push_changed):
            old_health = snap.previous_health if snap.previous_health is not None else snap.health_score
            event = HealthChangeEvent(
                node_id=snap.node_id or snap.symbol,
                symbol=snap.symbol,
                name=snap.name or snap.symbol,
                old_state=old_state,
                new_state=new_state,
                old_health=old_health,
                new_health=snap.health_score,
                old_push_level=old_push,
                new_push_level=new_push,
                rule_id=rule_id,
                reason=reason,
                thesis_status=_thesis_status(new_state),
                narrative_label=snap.narrative_label,
                narrative_invalid_count=snap.narrative_invalid_count,
                sli_snapshot=snap.sli_snapshot,
            )
            msg_id = self.publisher.publish(event)
            published = msg_id is not None

        return OrchestratorResult(
            symbol=snap.symbol,
            old_state=old_state,
            new_state=new_state,
            old_push_level=old_push,
            new_push_level=new_push,
            state_changed=state_changed,
            push_changed=push_changed,
            rule_id=rule_id,
            reason=reason,
            published=published,
            msg_id=msg_id,
        )
