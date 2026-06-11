"""fii_gb200_milestone 卡片战略层 · DeepSea 纯语义状态机。

[Ref: 28_ §2.2 fii_gb200_milestone · Contract Layer]
"""
from __future__ import annotations

from typing import Any


def _deepsea_layer(contract: dict[str, Any]) -> dict[str, Any]:
    dc = contract.get("deepsea_contract")
    return dc if isinstance(dc, dict) else {}


def build_card_strategy(t0: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    sm = contract.get("state_machine") if isinstance(contract.get("state_machine"), dict) else {}
    paradox = contract.get("temporal_check") if isinstance(contract.get("temporal_check"), dict) else {}
    dc = _deepsea_layer(contract)
    sv = contract.get("shadow_validation") if isinstance(contract.get("shadow_validation"), dict) else {}
    if not sv:
        sv = dc.get("shadow_validation") if isinstance(dc.get("shadow_validation"), dict) else {}
    aw = contract.get("event_window") or contract.get("analysis_window") or {}

    evidence_quotes = dc.get("evidence_quotes") or contract.get("evidence_quotes") or []
    if isinstance(evidence_quotes, str):
        evidence_quotes = [evidence_quotes]
    momentum = dc.get("momentum_delta") or contract.get("momentum_delta") or "unknown"
    signal_status = dc.get("signal_status") or sm.get("current_stage")

    if paradox.get("paradox"):
        status, label = "red", "时序悖论"
    elif sm.get("confirmed_breakthrough"):
        status, label = "green", "MP·侧翼确认"
    elif sm.get("trade_trigger"):
        status, label = "green", "MP+备料验真"
    elif sm.get("mp_starting_gun"):
        status, label = "yellow", "MP·待发令"
    elif signal_status == "PVT":
        status, label = "yellow", "PVT建底仓"
    elif signal_status in ("DVT", "EVT"):
        status, label = "gray", "左侧观察"
    elif signal_status == "RUMOR":
        status, label = "gray", "传闻跟踪"
    else:
        status, label = "gray", "跟踪中"

    return {
        "signal": {"status": status, "label": label},
        "stage": sm.get("current_stage_label") or signal_status,
        "signal_status": signal_status,
        "transition": sm.get("transition"),
        "momentum_delta": momentum,
        "momentum_rationale": dc.get("momentum_rationale") or contract.get("momentum_rationale"),
        "evidence_quotes": [str(q) for q in evidence_quotes if str(q).strip()],
        "mp_starting_gun": sm.get("mp_starting_gun"),
        "confirmed_breakthrough": sm.get("confirmed_breakthrough"),
        "trade_trigger": sm.get("trade_trigger"),
        "shadow_validation": sv,
        "analysis_window": aw,
        "announcement_title": t0.get("announcement_title"),
        "published_date": t0.get("published_date"),
        "doc_id": dc.get("doc_id") or t0.get("doc_id"),
        "cache_group": dc.get("cache_group") or contract.get("cache_group"),
        "llm_tag": contract.get("llm_tag") or dc.get("llm_tag"),
        "help": "DeepSea 纯语义 · 多点 evidence_quotes 拼图 · 无假方程",
    }


def refresh_card_strategy_for_node(node: dict[str, Any]) -> dict[str, Any]:
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    t0 = rm.get("t0_payload") if isinstance(rm.get("t0_payload"), dict) else {}
    contract = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
    if t0 and contract:
        return build_card_strategy(t0, contract)
    cs = rm.get("card_strategy")
    return cs if isinstance(cs, dict) else {}


def _status_badge(status: str) -> str:
    palette = {
        "PASS": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "FAIL": "bg-red-100 text-red-800 border-red-300",
        "true": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "false": "bg-amber-100 text-amber-900 border-amber-300",
    }
    cls = palette.get(status, "bg-gray-100 text-gray-700 border-gray-300")
    return f'<span class="inline-block px-1.5 py-0.5 rounded border text-[10px] font-semibold {cls}">{status}</span>'


def render_gb200_milestone_body(node: dict[str, Any]) -> str:
    import html

    _esc = html.escape
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    contract = node.get("t1_json") if isinstance(node.get("t1_json"), dict) else {}
    sm = contract.get("state_machine") if isinstance(contract.get("state_machine"), dict) else {}
    dc = _deepsea_layer(contract)
    cs = refresh_card_strategy_for_node(node)

    title = cs.get("announcement_title") or rm.get("announcement_title") or "—"
    pub = cs.get("published_date") or rm.get("published_date") or "—"
    stage = cs.get("stage") or sm.get("current_stage_label") or sm.get("current_stage") or "未识别"
    transition = sm.get("transition") or "—"
    momentum = cs.get("momentum_delta") or "—"
    quotes = cs.get("evidence_quotes") or dc.get("evidence_quotes") or contract.get("evidence_quotes") or []
    sv = cs.get("shadow_validation") or contract.get("shadow_validation") or {}
    aw = cs.get("analysis_window") or contract.get("event_window") or {}
    window_label = aw.get("label_zh") or "近12个月"

    quotes_html = ""
    if quotes:
        items = "".join(
            f'<li class="text-[10px] text-gray-700 leading-relaxed pl-2 border-l-2 border-orange-300 mb-1.5">'
            f"{_esc(str(q)[:400])}</li>"
            for q in quotes[:5]
        )
        quotes_html = (
            f'<div class="mt-2"><p class="text-[10px] font-semibold text-gray-500 mb-1">'
            f'证据原句（{len(quotes)} 处拼图）</p><ul class="list-none m-0 p-0">{items}</ul></div>'
        )
    else:
        quotes_html = (
            '<p class="text-[10px] text-amber-700 mt-2">'
            "语料未提取到 GB200/NVL 进度原句 · 请检查公告/业绩会实录</p>"
        )

    sv_pass = sv.get("passed")
    sv_badge = _status_badge("PASS" if sv_pass else "待验")
    cross = sv.get("cross_refs") or []
    cross_txt = " · ".join(cross) if cross else "—"
    sv_note = str(sv.get("note") or "")[:200]

    mom_rationale = cs.get("momentum_rationale") or dc.get("momentum_rationale") or ""
    mom_block = ""
    if mom_rationale:
        mom_block = (
            f'<p class="text-[10px] text-gray-600 mt-1.5 leading-relaxed">'
            f'<span class="font-semibold text-gray-500">动量：</span>{_esc(momentum)} · {_esc(mom_rationale[:280])}</p>'
        )

    fact = str(node.get("fact_statement") or contract.get("fact_statement") or "")[:320]
    fact_block = ""
    if fact.strip():
        fact_block = (
            f'<details class="mt-2 border border-gray-200 rounded-md bg-gray-50/80">'
            f'<summary class="cursor-pointer list-none px-2 py-1.5 text-[10px] text-gray-600 '
            f'[&::-webkit-details-marker]:hidden">事实契约 ▾</summary>'
            f'<p class="px-2 pb-2 text-[10px] text-gray-700 leading-relaxed">{_esc(fact)}</p>'
            f"</details>"
        )

    return (
        f'<div class="mt-3 rounded-xl border border-orange-200 bg-gradient-to-b from-orange-50/60 to-white px-3 py-2.5" '
        f'onclick="event.stopPropagation()">'
        f'<p class="text-xs font-bold text-gray-900">NPI · {_esc(str(stage))} · 跃迁 {_esc(str(transition))}</p>'
        f'<p class="text-[10px] text-gray-600 mt-1 truncate" title="{_esc(str(title))}">'
        f"来源：{_esc(str(title))} · {pub} · 窗口 {_esc(window_label)}</p>"
        f"{quotes_html}"
        f"{mom_block}"
        f'<p class="text-[10px] font-semibold text-gray-500 mt-2 mb-0.5">侧翼验真 {sv_badge}</p>'
        f'<p class="text-[10px] text-gray-600">交叉引用 {cross_txt}</p>'
        f'<p class="text-[10px] text-gray-500 mt-0.5">{_esc(sv_note)}</p>'
        f"{fact_block}"
        f"</div>"
    )
