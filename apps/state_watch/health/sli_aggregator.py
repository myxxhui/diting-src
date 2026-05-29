"""SLI 聚合器:把节点上 N 个 SLI 加权融合为 sli_score(0-100).

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SLIDef:
    id: str
    metric: str
    threshold: float
    operator: str = ">"
    weight: float = 1.0
    probe_type: str = "financial"
    current_value: Optional[float] = None


@dataclass
class SLIScoreDetail:
    sli_id: str
    score: float
    weight: float
    reason: str


_OP = {
    ">": lambda v, t: v > t,
    ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t,
    "<=": lambda v, t: v <= t,
    "==": lambda v, t: abs(v - t) < 1e-9,
    "!=": lambda v, t: abs(v - t) >= 1e-9,
}


def _score_one(sli: SLIDef) -> SLIScoreDetail:
    if sli.current_value is None:
        return SLIScoreDetail(sli.id, 50.0, sli.weight, "no_data")

    op = _OP.get(sli.operator, _OP[">"])
    v = sli.current_value
    t = sli.threshold

    if op(v, t):
        return SLIScoreDetail(sli.id, 100.0, sli.weight, f"pass {sli.operator} {t}")

    soft_t = t * 0.9 if t != 0 else (t - 0.1)
    if op(v, soft_t):
        return SLIScoreDetail(sli.id, 60.0, sli.weight, f"soft pass(90%): {v} {sli.operator} {soft_t:.4f}")

    soft_t2 = t * 0.7 if t != 0 else (t - 0.3)
    if op(v, soft_t2):
        return SLIScoreDetail(sli.id, 30.0, sli.weight, f"weak: {v} {sli.operator} {soft_t2:.4f}")

    return SLIScoreDetail(sli.id, 0.0, sli.weight, f"fail: {v} {sli.operator} {t}")


def aggregate(slis: list[SLIDef]) -> tuple[float, list[SLIScoreDetail]]:
    """返回 (sli_score 总分 0-100, 各 SLI 明细)."""
    if not slis:
        return 100.0, []
    total_w = sum(max(s.weight, 0) for s in slis)
    if total_w <= 0:
        return 100.0, []
    details = [_score_one(s) for s in slis]
    weighted = sum(d.score * d.weight for d in details)
    return round(weighted / total_w, 4), details
