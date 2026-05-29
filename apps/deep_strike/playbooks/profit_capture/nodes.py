"""LangGraph 节点函数。[Ref: step_04]"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.deep_strike.config import settings
from apps.deep_strike.db.models import FinancialIndicator
from apps.deep_strike.engines.evidence_builder import EvidenceChainBuilder
from apps.deep_strike.playbooks.base_playbook import Decision, SignalResult
from apps.deep_strike.playbooks.profit_capture.signals.cost_revenue_gap import (
    CostGrowthBelowRevenueSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.gross_margin import (
    GrossMarginQoQUpSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.inventory import (
    InventoryTurnoverUpSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.operating_leverage import (
    OperatingLeverageSignal,
)
from apps.deep_strike.playbooks.profit_capture.signals.receivable import (
    ReceivableTurnoverUpSignal,
)
from apps.deep_strike.playbooks.profit_capture.state import ProfitCaptureState

SIGNALS = [
    GrossMarginQoQUpSignal(),
    CostGrowthBelowRevenueSignal(),
    OperatingLeverageSignal(),
    ReceivableTurnoverUpSignal(),
    InventoryTurnoverUpSignal(),
]


def make_node_load_metrics(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def _node(state: ProfitCaptureState) -> dict[str, Any]:
        symbol = state["symbol"]
        async with session_factory() as s:
            res = await s.execute(
                select(FinancialIndicator)
                .where(FinancialIndicator.symbol == symbol)
                .order_by(FinancialIndicator.period_end.desc())
                .limit(1)
            )
            row = res.scalars().first()
        if row is None:
            return {"error": f"no financial_indicator for {symbol}", "raw_metrics": {}}
        metrics = {
            "gross_margin": row.gross_margin,
            "gross_margin_qoq": row.gross_margin_qoq,
            "gross_margin_yoy": row.gross_margin_yoy,
            "revenue_growth_yoy": row.revenue_growth_yoy,
            "cost_growth_yoy": row.cost_growth_yoy,
            "net_profit_growth_yoy": row.net_profit_growth_yoy,
            "receivable_turnover": row.receivable_turnover,
            "receivable_turnover_qoq": row.receivable_turnover_qoq,
            "inventory_turnover": row.inventory_turnover,
            "inventory_turnover_qoq": row.inventory_turnover_qoq,
            "pe": row.pe,
            "pb": row.pb,
            "period": row.period,
        }
        return {"raw_metrics": metrics}

    return _node


def node_score_signals(state: ProfitCaptureState) -> dict[str, Any]:
    if state.get("error"):
        return {"signals": [], "confidence": 0.0}
    metrics = state.get("raw_metrics") or {}
    results: list[SignalResult] = []
    score = 0.0
    for sig in SIGNALS:
        r = sig.evaluate(metrics)
        results.append(r)
        if r.hit:
            score += r.weight
    return {"signals": results, "confidence": round(score, 4)}


def make_node_build_evidence(session_factory: async_sessionmaker[AsyncSession]):
    async def _node(state: ProfitCaptureState) -> dict[str, Any]:
        if state.get("error"):
            return {"evidence": []}
        symbol = state["symbol"]
        async with session_factory() as s:
            chain = await EvidenceChainBuilder(s).build(symbol)
        return {"evidence": [e.model_dump(mode="json") for e in chain.items]}

    return _node


def node_classify_decision(state: ProfitCaptureState) -> dict[str, Any]:
    if state.get("error"):
        return {"decision": "discard"}
    c = state.get("confidence", 0.0)
    if c >= settings.propose_confidence_threshold:
        decision: Decision = "propose"
    elif c >= settings.watch_confidence_threshold:
        decision = "watch"
    else:
        decision = "discard"
    return {"decision": decision}
