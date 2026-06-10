"""T1 防置换契约 JSON（精简版 · 喂 T2）。

[Ref: 28_ §2.2 fii_twse_cloud · T1 Contract Layer]
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from apps.copilot.modules.executing.l3.fii_twse_cloud.t1_solver import solve_cloud_revenue_range

_CST = timezone(timedelta(hours=8))


def build_t1_contract(t0_payload: dict[str, Any]) -> dict[str, Any]:
    solved = solve_cloud_revenue_range(t0_payload)
    y, m = t0_payload["report_year"], t0_payload["report_month"]
    period = f"{y}-{m:02d}"
    total = int(t0_payload["total_revenue_ntd"])
    mom = float(t0_payload["total_mom_pct"])
    yoy = float(t0_payload["total_yoy_pct"])
    bounds = solved["cloud_revenue_ntd"]
    lo, hi = int(bounds["lo"]), int(bounds["hi"])
    mid = (lo + hi) // 2
    pr_evidence = solved["pr_evidence"]
    rank = pr_evidence.get("cloud_mom_rank")
    rank_note = (
        f"云端MoM增速四板块第{rank}位"
        if isinstance(rank, int)
        else "云端板块文本约束"
    )
    terms = pr_evidence.get("fuzzy_terms") or []
    term_note = f"、IR用词「{'」「'.join(terms)}」" if terms else ""

    return {
        "indicator_id": "fii_twse_cloud",
        "audit_timestamp": datetime.now(_CST).isoformat(),
        "period": period,
        "macro": {
            "total_ntd": total,
            "mom_pct": round(mom, 2),
            "yoy_pct": round(yoy, 2),
            "breakdown_published": False,
        },
        "cloud_revenue_ntd": {"lo": lo, "hi": hi, "mid": mid},
        "segments": solved["segments"],
        "pr_evidence": pr_evidence,
        "solver": solved["solver"],
        "fact_statement": (
            f"鸿海{period}合并营收{total // 1_000_000_000}亿NTD(MoM{mom:+.1f}%)，"
            f"官方未披露分板块金额。{rank_note}{term_note}，"
            f"方程约束下云端营收∈[{lo/1e9:.1f}–{hi/1e9:.1f}亿]NTD。"
        ),
    }
