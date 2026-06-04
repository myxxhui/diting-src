"""T0-4~7 产业生态采集。

[Ref: 27_ §2.3]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call
from apps.copilot.modules.radar.t0.llm_enrich import enrich_profile_llm_tag


def collect_profile_extended(sym: str) -> dict[str, Any]:
    """T0-4 · 基础档案（复用 scanner 逻辑 + 简介 + DeepSeek llm_tag）。"""
    from apps.copilot.modules.radar.scanner import _collect_profile

    base = _collect_profile(sym)
    if base.get("status") != "ok":
        return base
    try:
        import akshare as ak
    except ImportError:
        return enrich_profile_llm_tag(base)

    intro = ""
    try:
        df = ak_call(ak.stock_individual_info_em, symbol=sym)
        if df is not None and not df.empty:
            info = dict(zip(df["item"].astype(str), df["value"]))
            intro = str(info.get("主营业务") or info.get("经营范围") or "")[:2000]
    except Exception:
        pass
    base["business_intro"] = intro or None
    return enrich_profile_llm_tag(base)


def collect_segment_breakdown(sym: str) -> dict[str, Any]:
    """T0-5 · 主营构成（东财 datacenter RPT_F10_FN_MAINOP · 无数据即 error）。"""
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_main_op_segments

    segments = fetch_main_op_segments(sym, mainop_type="2")
    if not segments:
        return {
            "status": "error",
            "detail": "T0-5 主营构成分部未获取（东财 RPT_F10_FN_MAINOP 无返回）",
        }
    return {
        "status": "ok",
        "source": "eastmoney:RPT_F10_FN_MAINOP",
        "segments": segments[:10],
    }


def collect_supply_chain(sym: str) -> dict[str, Any]:
    """T0-6 · 前五大客户销售占比（巨潮年报 PDF · 禁止股东冒充）。"""
    from apps.copilot.modules.radar.t0.collectors.cninfo_reports import (
        fetch_top5_customers_from_annual,
    )

    return fetch_top5_customers_from_annual(sym)


def collect_peer_rank(sym: str, *, industry: str | None = None) -> dict[str, Any]:
    from apps.copilot.modules.radar.t0.collectors.peer_rank import (
        collect_peer_rank as _rank,
    )

    return _rank(sym, industry=industry)
