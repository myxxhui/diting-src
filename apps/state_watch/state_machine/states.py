"""节点 4 态枚举与合法迁移路径.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from enum import Enum


class NodeState(str, Enum):
    GROWING = "growing"
    STABLE = "stable"
    WARNING = "warning"
    EXIT = "exit"


VALID_TRANSITIONS: dict[NodeState, list[NodeState]] = {
    NodeState.GROWING: [NodeState.STABLE, NodeState.WARNING],
    NodeState.STABLE: [NodeState.GROWING, NodeState.WARNING, NodeState.EXIT],
    NodeState.WARNING: [NodeState.STABLE, NodeState.EXIT],
    NodeState.EXIT: [],
}


def is_valid_transition(from_state: NodeState, to_state: NodeState) -> bool:
    if from_state == to_state:
        return True
    return to_state in VALID_TRANSITIONS.get(from_state, [])
