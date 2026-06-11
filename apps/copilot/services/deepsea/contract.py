"""DeepSea T1 契约模型 · 防幻觉信号层。

[Ref: 29_ §5.2 · 28_ §2.2 fii_gb200_milestone Contract Layer]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DeepSeaContract:
    probe_key: str
    symbol: str
    signal_type: str
    batch_id: str
    cache_group: str
    signal_status: str | None
    value: Any
    calculation_logic: Any
    evidence_quotes: list[str] = field(default_factory=list)
    fact_statement: str = ""
    momentum_delta: str = "unknown"
    momentum_rationale: str = ""
    shadow_validation: dict[str, Any] = field(default_factory=dict)
    doc_id: str = ""
    inferred_at: str = ""
    source: str = ""
    llm_tag: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_semantic_dict(cls, raw: dict[str, Any]) -> "DeepSeaContract":
        quotes = raw.get("evidence_quotes") or []
        if isinstance(quotes, str):
            quotes = [quotes]
        return cls(
            probe_key=str(raw.get("probe_key") or ""),
            symbol=str(raw.get("symbol") or ""),
            signal_type=str(raw.get("signal_type") or "semantic"),
            batch_id=str(raw.get("batch_id") or raw.get("cache_group") or ""),
            cache_group=str(raw.get("cache_group") or ""),
            signal_status=raw.get("signal_status"),
            value=raw.get("value"),
            calculation_logic=raw.get("calculation_logic"),
            evidence_quotes=[str(q) for q in quotes if str(q).strip()],
            fact_statement=str(raw.get("fact_statement") or ""),
            momentum_delta=str(raw.get("momentum_delta") or "unknown"),
            momentum_rationale=str(raw.get("momentum_rationale") or ""),
            shadow_validation=raw.get("shadow_validation") if isinstance(raw.get("shadow_validation"), dict) else {},
            doc_id=str(raw.get("doc_id") or ""),
            inferred_at=str(raw.get("inferred_at") or datetime.utcnow().isoformat()),
            source=str(raw.get("source") or ""),
            llm_tag=raw.get("llm_tag"),
            extra={k: v for k, v in raw.items() if k not in {
                "probe_key", "symbol", "signal_type", "batch_id", "cache_group",
                "signal_status", "value", "calculation_logic", "evidence_quotes",
                "fact_statement", "momentum_delta", "momentum_rationale",
                "shadow_validation", "doc_id", "inferred_at", "source", "llm_tag",
            }},
        )

    def to_dict(self) -> dict[str, Any]:
        base = {
            "probe_key": self.probe_key,
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "batch_id": self.batch_id,
            "cache_group": self.cache_group,
            "signal_status": self.signal_status,
            "value": self.value,
            "calculation_logic": self.calculation_logic,
            "evidence_quotes": self.evidence_quotes,
            "fact_statement": self.fact_statement,
            "momentum_delta": self.momentum_delta,
            "momentum_rationale": self.momentum_rationale,
            "shadow_validation": self.shadow_validation,
            "doc_id": self.doc_id,
            "inferred_at": self.inferred_at,
            "source": self.source,
            "llm_tag": self.llm_tag,
        }
        base.update(self.extra)
        return base


__all__ = ["DeepSeaContract"]
