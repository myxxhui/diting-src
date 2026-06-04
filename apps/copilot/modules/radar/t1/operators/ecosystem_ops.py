"""T1 算子 op_t04~op_t07。

[Ref: 27_ §3.3]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.operators.types import OpResult, node


def op_t04_profile_llm(t0_raw: dict[str, Any]) -> OpResult:
    """DeepSeek 槽位 · 须真实 LLM 提炼；无则 unavailable。"""
    prof = (t0_raw.get("ecosystem") or {}).get("profile") or t0_raw.get("profile") or {}
    if prof.get("status") != "ok":
        return OpResult("ecosystem", "company_profile", None, "缺少 T0-4 公司档案")
    if not prof.get("llm_tag"):
        return OpResult(
            "ecosystem",
            "company_profile",
            None,
            "T0-4 DeepSeek 提炼未执行（须 vLLM/DeepSeek 接入并写入 profile.llm_tag）",
        )
    intro = str(prof.get("business_intro") or "")[:120]
    return OpResult(
        "ecosystem",
        "company_profile",
        node(None, str(prof["llm_tag"]), intro),
    )


def op_t05_segment_top3(t0_raw: dict[str, Any]) -> OpResult:
    seg = (t0_raw.get("ecosystem") or {}).get("segment_breakdown") or {}
    if seg.get("status") != "ok":
        return OpResult("ecosystem", "business_composition", None, "缺少 T0-5 主营构成")
    segments = seg.get("segments") or []
    top = segments[0] if segments else {}
    top1 = top.get("revenue_ratio_pct")
    tag = "主业高度集中" if top1 is not None and top1 >= 70 else "业务多元化"
    names = ", ".join(f"{s.get('name')}({s.get('revenue_ratio_pct')}%)" for s in segments[:3])
    return OpResult("ecosystem", "business_composition", node(top1, tag, names or "Top3 主营"))


def op_t06_supply_chain(t0_raw: dict[str, Any]) -> OpResult:
    sc = (t0_raw.get("ecosystem") or {}).get("supply_chain") or {}
    if sc.get("status") != "ok":
        return OpResult("ecosystem", "supply_chain_concentration", None, "缺少 T0-6 供应链披露")
    pct = sc.get("top5_customer_pct")
    tag = "大客户依赖"
    if pct is not None and pct >= 60:
        tag = "严重依赖单一客户"
    elif pct is not None and pct < 50:
        tag = "客户分散"
    return OpResult(
        "ecosystem",
        "supply_chain_concentration",
        node(pct, tag, sc.get("detail") or f"Top5 客户占比 {pct}%"),
    )


def op_t07_peer_rank(t0_raw: dict[str, Any]) -> OpResult:
    pr = (t0_raw.get("ecosystem") or {}).get("peer_ranking") or {}
    if pr.get("status") != "ok":
        return OpResult("ecosystem", "peer_rank", None, "缺少 T0-7 同业排名")
    rank = pr.get("rank")
    total = pr.get("peer_count")
    tag = "赛道龙一" if rank == 1 else ("赛道龙二" if rank == 2 else "赛道头部")
    if rank is not None and total and rank / total > 0.2:
        tag = "行业中游"
    return OpResult(
        "ecosystem",
        "peer_rank",
        node(rank, tag, f"总市值在 {pr.get('industry')} 内排名 {rank}/{total}"),
    )
