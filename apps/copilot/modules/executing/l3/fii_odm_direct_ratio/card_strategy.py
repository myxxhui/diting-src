"""fii_odm_direct_ratio 卡片战略层。

[Ref: 28_ §2.2 · JL3 折叠卡]
"""
from __future__ import annotations

import html
from typing import Any

_HELP = """
<p><strong>fii_odm_direct_ratio</strong> 衡量工业富联云业务客户结构：
<strong>ODM 直供 CSP</strong>（北美云巨头） vs <strong>传统 OEM 通道</strong>。</p>
<p class="mt-1.5">DeepSeek 从季报 + IR 记录表抽取<strong>原文证据短句</strong>，评估 CSP/ODM 景气；
占比仅在财报披露或高置信语义推断时显示数字。</p>
"""

_DIMENSION_ZH = {
    "cloud_revenue_growth": "云营收增速",
    "csp_odm_deepening": "CSP/ODM合作",
    "order_volume_surge": "订单/出货",
    "revenue_mix_shift": "结构抬升",
    "negative_or_uncertain": "风险",
}


def _evidence_section_html(sem: dict[str, Any]) -> str:
    quotes = sem.get("evidence_quotes") if isinstance(sem.get("evidence_quotes"), list) else []
    if not quotes:
        return '<p class="text-xs text-gray-500">暂无语义证据短句</p>'
    rows: list[str] = []
    for q in quotes[:6]:
        if not isinstance(q, dict):
            continue
        dim = _DIMENSION_ZH.get(str(q.get("dimension") or ""), str(q.get("dimension") or ""))
        src = "季报" if q.get("source_doc") == "quarterly_report" else "IR实录"
        quote = html.escape(str(q.get("quote_zh") or "")[:280])
        strength = str(q.get("strength") or "")
        rows.append(
            f'<li class="text-xs text-gray-700 leading-relaxed border-l-2 border-indigo-300 pl-2 mb-2">'
            f'<span class="text-[10px] text-indigo-700 font-medium">[{src}·{dim}·{strength}]</span><br/>'
            f'「{quote}」</li>'
        )
    return f'<ul class="list-none pl-0 mt-1">{"".join(rows)}</ul>'


def build_card_strategy(t0: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    ratio = contract.get("odm_ratio_pct") or {}
    lo = float(ratio.get("lo") or 0)
    hi = float(ratio.get("hi") or lo)
    mid_raw = ratio.get("mid")
    mid = float(mid_raw) if mid_raw is not None else None
    solver = contract.get("solver") if isinstance(contract.get("solver"), dict) else {}
    method = str(solver.get("method") or "")
    sem_sig = contract.get("semantic_signal") if isinstance(contract.get("semantic_signal"), dict) else {}
    sem = contract.get("semantic_evidence_layer") if isinstance(contract.get("semantic_evidence_layer"), dict) else {}
    status = str(sem_sig.get("status") or "yellow")
    label = str(sem_sig.get("label") or "观察")
    yoy = t0.get("total_cloud_yoy_pct")
    yoy_s = f"{float(yoy):.0f}%" if yoy is not None else "—"
    cloud_b = round(int(t0["total_cloud_revenue_cny"]) / 1e8, 1)
    n_ev = len(sem.get("evidence_quotes") or [])

    if method == "semantic_evidence_only":
        summary = f"{label} · 云 {cloud_b}亿 YoY {yoy_s} · {n_ev}条证据"
    elif mid is not None:
        summary = f"{label} · ODM {lo:.0f}–{hi:.0f}% · 云 {cloud_b}亿"
    else:
        summary = f"{label} · 云 {cloud_b}亿 YoY {yoy_s}"

    sections: list[dict[str, Any]] = [
        {
            "title": "云业务硬锚",
            "subtitle": str(t0.get("report_title") or "")[:80],
            "table": {
                "rows": [
                    {
                        "period": t0.get("report_period"),
                        "cloud_billion_cny": cloud_b,
                        "yoy_pct": yoy,
                        "odm_lo_pct": lo if mid is not None else None,
                        "odm_hi_pct": hi if mid is not None else None,
                        "semantic_label": label,
                    }
                ],
                "value_key": "cloud_billion_cny",
                "value_label": "云营收(亿元)",
                "column_helps": {},
            },
        },
        {
            "title": "语义证据原句",
            "custom_html": _evidence_section_html(sem),
        },
        {
            "title": "评估摘要",
            "custom_html": (
                f'<p class="text-xs text-gray-600 leading-relaxed">'
                f"{html.escape(str(contract.get('physical_fact_contract') or '')[:600])}"
                f"</p>"
            ),
        },
    ]

    return {
        "panel_title": f"ODM直供 · {t0.get('report_period', '')}",
        "help_html": _HELP.strip(),
        "signal": {
            "status": status,
            "label": label,
            "summary": summary,
        },
        "sections": sections,
    }


def refresh_card_strategy_for_node(node: dict[str, Any]) -> dict[str, Any]:
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    cs = rm.get("card_strategy")
    if isinstance(cs, dict) and cs.get("signal"):
        return cs
    t0 = rm.get("t0_payload") if isinstance(rm.get("t0_payload"), dict) else {}
    contract = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
    if t0 and contract:
        return build_card_strategy(t0, contract)
    return cs if isinstance(cs, dict) else {}
