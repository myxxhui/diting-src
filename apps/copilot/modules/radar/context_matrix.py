"""T1 矩阵压缩：把 T0 akshare 原始集压成喂 Opus 的紧凑事实矩阵（省 token）。

只保留 status=ok 的真实事实；error 源标注 unavailable，让 Opus 知道缺口（不编造）。

[Ref: step_14 §3.1 · ContextMatrixBuilder]
"""
from __future__ import annotations

from typing import Any


def build_context_matrix(t0_raw: dict[str, Any]) -> dict[str, Any]:
    """启动期纯规则压缩（t1_fallback=rule），输出 {matrix, unavailable}。"""
    quote = t0_raw.get("quote") or {}
    profile = t0_raw.get("profile") or {}
    fin = t0_raw.get("financials") or {}
    val = t0_raw.get("valuation") or {}

    matrix: dict[str, Any] = {}
    unavailable: list[str] = []

    if quote.get("status") == "ok":
        matrix["行情"] = {
            "最新收盘": quote.get("last_close"),
            "涨跌幅_1日_%": quote.get("pct_chg_1d"),
            "涨跌幅_5日_%": quote.get("pct_chg_5d"),
            "涨跌幅_20日_%": quote.get("pct_chg_20d"),
            "涨跌幅_60日_%": quote.get("pct_chg_60d"),
            "量比_5日": quote.get("volume_ratio_5d"),
            "截至": quote.get("as_of"),
        }
    else:
        unavailable.append("行情:" + str(quote.get("detail") or "缺"))

    if profile.get("status") == "ok":
        matrix["公司资料"] = {
            "简称": profile.get("name"),
            "行业": profile.get("industry"),
            "总市值_亿": profile.get("total_mv_yi"),
            "流通市值_亿": profile.get("float_mv_yi"),
            "上市时间": profile.get("listing_date"),
        }
    else:
        unavailable.append("公司资料:" + str(profile.get("detail") or "缺"))

    if fin.get("status") == "ok":
        matrix["财务摘要"] = {
            k: v
            for k, v in fin.items()
            if k not in ("status", "detail")
        }
    else:
        unavailable.append("财务摘要:" + str(fin.get("detail") or "缺"))

    if val.get("status") == "ok":
        matrix["估值"] = {
            "PE_TTM": val.get("pe_ttm"),
            "PE历史分位_%": val.get("pe_percentile"),
            "PB": val.get("pb"),
            "历史样本点": val.get("history_points"),
        }
    else:
        unavailable.append("估值:" + str(val.get("detail") or "缺"))

    return {
        "model_id": "rule:context_matrix",
        "t1_fallback": "rule",
        "symbol": t0_raw.get("symbol"),
        "name": t0_raw.get("name"),
        "matrix": matrix,
        "unavailable": unavailable,
        "fact_count": len(matrix),
    }
