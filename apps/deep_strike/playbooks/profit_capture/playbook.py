"""ProfitCapturePlaybook：LangGraph StateGraph 编排器。[Ref: step_04]"""
from __future__ import annotations

import logging
from typing import Any, Optional

from langgraph.graph import END, StateGraph

from apps.deep_strike.db.database import AsyncSessionLocal
from apps.deep_strike.db.models import ScanLog
from apps.deep_strike.playbooks.base_playbook import BasePlaybook, PlaybookResult, SignalResult
from apps.deep_strike.playbooks.profit_capture.nodes import (
    make_node_build_evidence,
    make_node_load_metrics,
    node_classify_decision,
    node_score_signals,
)
from apps.deep_strike.playbooks.profit_capture.state import ProfitCaptureState

logger = logging.getLogger(__name__)


def _normalize_signals(raw: Any) -> list[SignalResult]:
    if not raw:
        return []
    out: list[SignalResult] = []
    for s in raw:
        if isinstance(s, SignalResult):
            out.append(s)
        elif isinstance(s, dict):
            out.append(SignalResult.model_validate(s))
        else:
            out.append(SignalResult.model_validate(dict(s)))
    return out


class ProfitCapturePlaybook(BasePlaybook):
    id = "profit_capture"
    cn_name = "利润截留扫描仪"
    priority = "P0"

    def __init__(self, session_factory=AsyncSessionLocal) -> None:
        self.session_factory = session_factory
        self._compiled = self._compile()

    def _compile(self):
        g = StateGraph(ProfitCaptureState)
        g.add_node("load_metrics", make_node_load_metrics(self.session_factory))
        g.add_node("score_signals", node_score_signals)
        g.add_node("build_evidence", make_node_build_evidence(self.session_factory))
        g.add_node("classify_decision", node_classify_decision)

        g.set_entry_point("load_metrics")
        g.add_edge("load_metrics", "score_signals")
        g.add_edge("score_signals", "build_evidence")
        g.add_edge("build_evidence", "classify_decision")
        g.add_edge("classify_decision", END)
        return g.compile()

    async def scan(self, symbol: str, *, pass_event_id: Optional[str] = None) -> PlaybookResult:
        logger.info("[profit_capture] scan symbol=%s", symbol)
        initial: ProfitCaptureState = {"symbol": symbol, "pass_event_id": pass_event_id}
        final: dict[str, Any] = await self._compiled.ainvoke(initial)
        signals = _normalize_signals(final.get("signals"))
        result = PlaybookResult(
            playbook_id=self.id,
            symbol=symbol,
            decision=final.get("decision", "discard"),
            confidence=float(final.get("confidence", 0.0)),
            signals=signals,
            raw_metrics=final.get("raw_metrics") or {},
            evidence=final.get("evidence") or [],
            pass_event_id=pass_event_id,
            error=final.get("error"),
        )
        await self._persist_scan_log(result)
        return result

    async def _persist_scan_log(self, r: PlaybookResult) -> None:
        async with self.session_factory() as s:
            s.add(
                ScanLog(
                    playbook_id=r.playbook_id,
                    symbol=r.symbol,
                    decision=r.decision,
                    confidence=r.confidence,
                    signals=[sig.model_dump() for sig in r.signals],
                    raw_metrics=r.raw_metrics,
                    pass_event_id=r.pass_event_id,
                    error=r.error,
                )
            )
            await s.commit()
