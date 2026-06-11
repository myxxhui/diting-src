"""DeepSea 批推探针注册表 · probe_key → infer 函数。

[Ref: 29_ §5.4 · 28_ §2.11.5 fii-cninfo-dynamic]
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from apps.copilot.services.deepsea.config_loader import get_l3_probe_config
from apps.copilot.services.deepsea.context_cache import ContextCacheRef, inject_cache_ref

logger = logging.getLogger(__name__)

InferFn = Callable[[dict[str, Any]], dict[str, Any]]


def _run_gb200_milestone(t0: dict[str, Any]) -> dict[str, Any]:
    from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_semantic import (
        infer_gb200_milestone_semantic,
    )

    return infer_gb200_milestone_semantic(t0)


def _run_odm_direct_ratio(t0: dict[str, Any]) -> dict[str, Any]:
    """ODM 需独立 T0 财务字段；批推时仅当 payload 含 total_cloud_revenue_cny 才执行。"""
    if t0.get("total_cloud_revenue_cny") is None:
        return {
            "probe_key": "fii_odm_direct_ratio",
            "status": "skipped",
            "reason": "批推共享 T0 缺 ODM 财务锚点 · 待季报 T0 合并",
        }
    from apps.copilot.modules.executing.l3.fii_odm_direct_ratio.t1_solver import solve_odm_direct_ratio

    solved = solve_odm_direct_ratio(t0)
    return {
        "probe_key": "fii_odm_direct_ratio",
        "signal_type": "semantic",
        "signal_status": solved.get("odm_growth_signal"),
        "value": solved.get("odm_ratio_pct"),
        "fact_statement": solved.get("fact_statement"),
        "evidence_quotes": [
            str(q.get("quote") or q) for q in (solved.get("evidence_quotes") or []) if q
        ],
        "momentum_delta": solved.get("odm_growth_signal"),
        "extra": {"solver": solved},
    }


PROBE_INFER_REGISTRY: dict[str, InferFn] = {
    "fii_gb200_milestone": _run_gb200_milestone,
    "fii_odm_direct_ratio": _run_odm_direct_ratio,
}


def is_probe_registered(probe_key: str) -> bool:
    return probe_key in PROBE_INFER_REGISTRY


def run_probe_infer(
    probe_key: str,
    t0: dict[str, Any],
    cache_ref: ContextCacheRef | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    sym = str(symbol or t0.get("symbol") or "").zfill(6)[-6:]
    t0_run = inject_cache_ref(t0, cache_ref) if cache_ref else dict(t0)
    fn = PROBE_INFER_REGISTRY.get(probe_key)
    if fn is None:
        try:
            cfg = get_l3_probe_config(sym, probe_key)
            pipeline = cfg.get("t1_pipeline")
        except (FileNotFoundError, KeyError):
            pipeline = None
        return {
            "probe_key": probe_key,
            "symbol": sym,
            "status": "pending",
            "reason": f"批推 runner 未注册 · pipeline={pipeline}",
        }
    try:
        out = fn(t0_run)
        if "probe_key" not in out:
            out = {**out, "probe_key": probe_key}
        if "symbol" not in out:
            out["symbol"] = sym
        out["status"] = out.get("status") or "ok"
        return out
    except Exception as exc:  # noqa: BLE001
        logger.exception("DeepSea probe %s 失败", probe_key)
        return {
            "probe_key": probe_key,
            "symbol": sym,
            "status": "error",
            "error": str(exc)[:300],
        }


__all__ = ["PROBE_INFER_REGISTRY", "is_probe_registered", "run_probe_infer"]
