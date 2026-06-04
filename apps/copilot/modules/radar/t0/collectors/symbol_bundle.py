"""单标的 T0 全域 bundle（17 项键 · P3）。

[Ref: 27_ §2 · §5.1]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t0.collectors.consensus import collect_consensus
from apps.copilot.modules.radar.t0.collectors.ecosystem import (
    collect_peer_rank,
    collect_profile_extended,
    collect_segment_breakdown,
    collect_supply_chain,
)
from apps.copilot.modules.radar.t0.collectors.microstructure import collect_microstructure
from apps.copilot.modules.radar.t0.collectors.risk import collect_risk_bundle
from apps.copilot.modules.radar.t0.collectors.sector import collect_sector_context


def collect_symbol_domains(
    sym: str,
    *,
    macro_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """并行域采集（同步 · 供 scanner / Cron 调用）。"""
    profile = collect_profile_extended(sym)
    industry = profile.get("industry") if profile.get("status") == "ok" else None
    sector = collect_sector_context(sym, industry=industry)
    eco_profile = profile
    segments = collect_segment_breakdown(sym)
    supply = collect_supply_chain(sym)
    peer = collect_peer_rank(sym, industry=industry)
    micro = collect_microstructure(sym)
    consensus = collect_consensus(sym)
    risk = collect_risk_bundle(sym)

    macro = {
        "market_sentiment": macro_snapshot
        if macro_snapshot and macro_snapshot.get("status") == "ok"
        else {"status": "error", "detail": "T0-1 宏观快照未注入或采集失败"},
        **sector,
    }
    ecosystem = {
        "profile": eco_profile,
        "segment_breakdown": segments,
        "supply_chain": supply,
        "peer_ranking": peer,
    }
    return {
        "macro": macro,
        "ecosystem": ecosystem,
        "micro": micro,
        "consensus": consensus,
        "risk": risk,
    }
