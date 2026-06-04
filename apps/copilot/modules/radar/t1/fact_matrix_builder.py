"""T1 fact_matrix 装配（启动期：四块 T0 → 五域 feature_node 骨架）。

[Ref: 27_ §3.7]
"""
from __future__ import annotations

from typing import Any


def _node(
    value: Any,
    tag: str,
    context: str,
) -> dict[str, Any]:
    return {"value": value, "tag": tag, "context": context}


def build_fact_matrix_from_legacy(
    t0_raw: dict[str, Any],
    matrix: dict[str, Any],
    unavailable: list[str],
) -> dict[str, Any]:
    """由现有四分区 matrix + T0 原始块推导五域 fact_matrix（P0 骨架）。"""
    quote = t0_raw.get("quote") or {}
    profile = t0_raw.get("profile") or {}
    financials = t0_raw.get("financials") or {}
    valuation = t0_raw.get("valuation") or {}

    m_quote = matrix.get("行情") or {}
    m_profile = matrix.get("公司资料") or {}
    m_fin = matrix.get("财务摘要") or {}
    m_val = matrix.get("估值") or {}

    price_action = None
    if quote.get("status") == "ok":
        pct20 = quote.get("pct_chg_20d")
        price_action = _node(
            pct20,
            "量价可用",
            f"近20日涨跌 {pct20}% · 量比 {quote.get('volume_ratio_5d')}",
        )

    peer_rank = None
    if profile.get("status") == "ok":
        mv = profile.get("total_mv_yi")
        peer_rank = _node(
            mv,
            "资料就绪",
            f"行业 {profile.get('industry') or '—'} · 总市值 {mv} 亿",
        )

    financial_quality = None
    if financials.get("status") == "ok":
        roe = financials.get("roe")
        financial_quality = _node(
            roe,
            "财务摘要就绪",
            f"ROE {roe}% · 毛利率 {financials.get('gross_margin')}%",
        )

    val_node = None
    if valuation.get("status") == "ok":
        pe_pct = valuation.get("pe_percentile")
        val_node = _node(
            pe_pct,
            "估值分位就绪",
            f"PE(TTM) {valuation.get('pe_ttm')} · 历史分位 {pe_pct}%",
        )

    unavailable_data = list(unavailable or [])
    for key, label in (
        ("quote", "T0-8 量价"),
        ("profile", "T0-4 基础档案"),
        ("financials", "T0-14 财务切片"),
        ("valuation", "T0 估值"),
    ):
        block = t0_raw.get(key) or {}
        if block.get("status") != "ok":
            msg = f"缺少 {label} 数据"
            if msg not in unavailable_data:
                unavailable_data.append(msg)

    return {
        "global_and_meso": {
            "market_temperature": _node(None, "待宏观 Cron", "T0-1 全市场情绪由全局 Job 供给"),
        },
        "ecosystem": {
            "company_profile": peer_rank or _node(None, "缺失", "无公司资料"),
            "business_composition": _node(None, "待扩展", "主营穿透算子 P3"),
        },
        "microstructure": {
            "price_action": price_action or _node(None, "缺失", "无量价数据"),
        },
        "consensus": {
            "eps_growth_forecast": _node(None, "待扩展", "一致预期算子 P3"),
        },
        "risks_red_flags": {
            "financial_quality": financial_quality or _node(None, "缺失", "无财务摘要"),
            "valuation_snapshot": val_node or _node(None, "缺失", "无估值分位"),
        },
        "_legacy_matrix": matrix,
    }, unavailable_data


def enrich_t1_payload(t0_raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """在既有 matrix/unavailable 上附加 fact_matrix + unavailable_data（含 P1 微观算子）。"""
    from apps.copilot.modules.radar.t1.radar_matrix_assembler import enrich_t1_payload as _assemble

    return _assemble(t0_raw, payload)
