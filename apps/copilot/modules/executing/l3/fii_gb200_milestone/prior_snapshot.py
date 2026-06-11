"""从 T1 快照提取上期语义状态 · 供动量推演。

[Ref: 28_ §2.2 fii_gb200_milestone · DeepSea 记忆加载]
"""
from __future__ import annotations

from typing import Any


def prior_signal_snapshot_from_t1(prev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not prev or not isinstance(prev.get("t1_json"), dict):
        return None
    t1 = prev["t1_json"]
    dc = t1.get("deepsea_contract") if isinstance(t1.get("deepsea_contract"), dict) else {}
    sm = t1.get("state_machine") if isinstance(t1.get("state_machine"), dict) else {}
    status = dc.get("signal_status") or sm.get("current_stage")
    if not status:
        return None
    return {"signal_status": str(status).strip().upper()}


def prior_lifecycle_stage_from_t1(prev: dict[str, Any] | None) -> str | None:
    snap = prior_signal_snapshot_from_t1(prev)
    return snap.get("signal_status") if snap else None


__all__ = ["prior_lifecycle_stage_from_t1", "prior_signal_snapshot_from_t1"]
