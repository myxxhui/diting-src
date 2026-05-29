"""LangGraph 状态机定义.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_01]
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from apps.state_watch.state_machine.states import NodeState
from apps.state_watch.state_machine.transitions import TransitionContext, TransitionResult, evaluate


class GraphState(TypedDict, total=False):
    node_id: str
    current_state: str
    health_score: float
    narrative_label: str
    narrative_invalid_count: int
    held_for_days: int
    health_above_75_days: int
    target_state: str
    rule_id: str
    reason: str


def _evaluate_node(state: GraphState) -> GraphState:
    cur = state.get("current_state", "growing")
    if isinstance(cur, NodeState):
        ns = cur
    else:
        ns = NodeState(str(cur))
    ctx = TransitionContext(
        current_state=ns,
        health_score=float(state.get("health_score", 100.0)),
        narrative_label=str(state.get("narrative_label", "neutral")),
        narrative_invalid_count=int(state.get("narrative_invalid_count", 0)),
        held_for_days=int(state.get("held_for_days", 0)),
        health_above_75_days=int(state.get("health_above_75_days", 0)),
    )
    result: TransitionResult = evaluate(ctx)
    new_state: GraphState = dict(state)
    if result.target_state is not None:
        new_state["target_state"] = result.target_state.value
    else:
        new_state["target_state"] = str(cur) if not isinstance(cur, NodeState) else cur.value
    new_state["rule_id"] = result.rule_id or "NONE"
    new_state["reason"] = result.reason
    return new_state


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("evaluate", _evaluate_node)
    builder.set_entry_point("evaluate")
    builder.add_edge("evaluate", END)
    return builder.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
