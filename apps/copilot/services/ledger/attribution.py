"""8 象限归因引擎。

象限判定规则：
    advice 维度：BUY / SELL（含告警止损/止盈/thesis 失效）
    action 维度：与 advice 一致则为 EXECUTED
    result 维度：由 pnl 正负刻画

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_06]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from apps.copilot.services.ledger.models import Octant


@dataclass
class AttributionInput:
    advice: str
    action: str
    pnl: float


@dataclass
class AttributionOutput:
    octant: Octant
    scs_delta: float
    ev_delta: float
    text: str


_OCTANT_CONFIG: Dict[Octant, Dict[str, object]] = {
    Octant.A: {"scs": +10.0, "ev_factor": +1.0,
               "text": "系统建议正确，用户执行到位 → 双赢"},
    Octant.B: {"scs": -8.0, "ev_factor": +1.0,
               "text": "系统建议买入但亏损 → 系统需复盘"},
    Octant.C: {"scs": +10.0, "ev_factor": +1.0,
               "text": "系统及时预警卖出，用户执行避亏"},
    Octant.D: {"scs": 0.0, "ev_factor": 0.0,
               "text": "系统已预警卖出，用户未执行 → 用户责任"},
    Octant.E: {"scs": 0.0, "ev_factor": 0.0,
               "text": "系统建议买入但用户未买，错过涨幅 → 用户错过"},
    Octant.F: {"scs": +6.0, "ev_factor": +1.0,
               "text": "系统建议买入但用户未买，结果下跌 → 系统避坑"},
    Octant.G: {"scs": -8.0, "ev_factor": 0.0,
               "text": "系统建议卖出但用户未执行，结果上涨 → 系统误判"},
    Octant.H: {"scs": -8.0, "ev_factor": -1.0,
               "text": "系统建议卖出且用户执行，结果上涨 → 系统卖飞误判"},
}


def _is_executed(advice: str, action: str) -> bool:
    a = advice.lower().strip()
    u = action.lower().strip()
    if a == "buy":
        return u == "buy"
    if a == "sell":
        return u == "sell"
    return False


def classify(inp: AttributionInput) -> Octant:
    advice = inp.advice.lower()
    executed = _is_executed(inp.advice, inp.action)
    positive = inp.pnl > 0

    if advice == "buy":
        if executed:
            return Octant.A if positive else Octant.B
        return Octant.E if positive else Octant.F

    if advice == "sell":
        if executed:
            return Octant.C if positive else Octant.H
        return Octant.D if not positive else Octant.G

    raise ValueError(f"unsupported advice: {advice}")


def attribute(inp: AttributionInput) -> AttributionOutput:
    oct_ = classify(inp)
    cfg = _OCTANT_CONFIG[oct_]
    scs_delta = float(cfg["scs"])
    ev_delta = float(cfg["ev_factor"]) * abs(inp.pnl)
    return AttributionOutput(
        octant=oct_,
        scs_delta=scs_delta,
        ev_delta=ev_delta,
        text=str(cfg["text"]),
    )
