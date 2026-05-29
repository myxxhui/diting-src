"""ThesisCard → D0 ThesisProposedPayload 转换。

[Ref: 03_/02_维度二/.../step_05 §7.1 G]
[Ref: apps/copilot/modules/recommendation/schema.py ThesisProposedPayload]
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from apps.deep_strike.engines.thesis.schema import ThesisCardSchema

# D0 ThesisProposedPayload 顶层字段（与 copilot schema 一致）
D0_PAYLOAD_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "timestamp",
        "trace_id",
        "thesis_id",
        "symbol",
        "name",
        "thesis_summary",
        "evidence_chain",
        "risks",
        "valuation_anchor",
        "action",
        "pass_event_id",
    }
)

D0_VALUATION_FIELDS = frozenset({"method", "target_price", "target_pe", "target_pb", "note"})


def card_to_d0_payload(
    card: ThesisCardSchema,
    *,
    event_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """将 D2 thesis 卡转为 D0 events:thrust:thesis_proposed payload。"""
    va = card.valuation_anchor
    d0_va: dict[str, Any] = {
        "method": va.method,
        "target_price": va.target_price,
        "note": va.basis or None,
    }
    if va.method == "PE" and va.target_price is not None:
        d0_va["target_pe"] = round(va.target_price / max(card.confidence, 0.01), 2)

    evidence = [
        f"{item.evidence_type}: {item.content}" if item.evidence_type else item.content
        for item in card.evidence_chain
    ]

    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": "thesis_proposed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "trace_id": trace_id,
        "thesis_id": card.thesis_id,
        "symbol": card.symbol,
        "name": card.name or card.symbol,
        "thesis_summary": card.thesis_summary,
        "evidence_chain": evidence,
        "risks": list(card.risks),
        "valuation_anchor": d0_va,
        "action": card.action,
        "pass_event_id": card.pass_event_id,
    }


def d0_field_diff(payload: dict[str, Any]) -> list[str]:
    """返回相对 D0 契约的多余顶层字段（空列表 = diff 0）。"""
    extra = set(payload.keys()) - D0_PAYLOAD_FIELDS
    return sorted(extra)
