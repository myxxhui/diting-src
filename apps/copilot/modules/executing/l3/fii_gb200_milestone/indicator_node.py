"""fii_gb200_milestone T1 指标节点。

[Ref: 28_ §4.1]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.executing.l3.fii_gb200_milestone.constants import CONTRACT_VERSION, INDICATOR_ID
from apps.copilot.modules.executing.l3.fii_gb200_milestone.card_strategy import build_card_strategy
from apps.copilot.modules.executing.l3.fii_gb200_milestone.t1_contract import build_t1_contract
from apps.copilot.modules.executing.probe_labels import probe_indicator_name


def build_fii_gb200_milestone_blocker_node(
    blocker: str,
    *,
    source: str = "T0",
) -> dict[str, Any]:
    """T0 失败仍返回可见卡片 · 禁止前端静默消失。"""
    msg = str(blocker or "T0 未采集").strip()
    card_strategy = {
        "signal": {"status": "gray", "label": "采集中断"},
        "help": msg,
    }
    return {
        "indicator_name": probe_indicator_name("fii_gb200_milestone"),
        "value": "待数据",
        "value_detail": msg[:120],
        "fact_statement": msg,
        "calculation_logic": "T0_blocker",
        "source": source,
        "t1_json": {
            "indicator_id": INDICATOR_ID,
            "contract_version": CONTRACT_VERSION,
            "blocker": msg,
        },
        "raw_metrics": {
            "card_strategy": card_strategy,
            "blocker": msg,
        },
    }


def build_fii_gb200_milestone_node(
    t0_payload: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    contract = build_t1_contract(t0_payload)
    sm = contract.get("state_machine") or {}
    stage_raw = sm.get("current_stage_label") or sm.get("current_stage")
    stage = stage_raw if stage_raw and stage_raw not in ("—", "UNKNOWN", None) else "未识别NPI"
    transition = sm.get("transition") or "—"
    aw = contract.get("analysis_window") or contract.get("event_window") or {}
    aw_label = aw.get("label_zh") or "近12个月"
    card_strategy = build_card_strategy(t0_payload, contract)

    dc = contract.get("deepsea_contract") or {}
    sig_status = dc.get("signal_status") or sm.get("current_stage")
    mom = dc.get("momentum_delta") or "—"
    sv = contract.get("shadow_validation") or {}

    if sm.get("confirmed_breakthrough"):
        value = f"{sig_status}·确认"
        value_detail = f"{transition} · 备料侧翼验真PASS · {mom} · {aw_label}"
    elif sm.get("mp_starting_gun"):
        value = f"{sig_status}·发令"
        value_detail = f"{transition} · 侧翼{'PASS' if sv.get('passed') else '待验'} · {mom} · {aw_label}"
    else:
        value = str(sig_status or stage)
        sv_pass = "PASS" if sv.get("passed") else "待验"
        value_detail = f"{transition} · 动量{mom} · 侧翼{sv_pass} · {aw_label}"

    calc = (
        f"deepsea={contract.get('contract_version')} · cache_group=fii-cninfo-dynamic · "
        f"signal_status={sig_status} · momentum={mom} · "
        f"gun={sm.get('mp_starting_gun')} · llm_tag={contract.get('llm_tag')}"
    )

    return {
        "indicator_name": probe_indicator_name("fii_gb200_milestone"),
        "value": value,
        "value_detail": value_detail,
        "fact_statement": contract["fact_statement"],
        "calculation_logic": calc,
        "source": source,
        "t1_json": contract,
        "raw_metrics": {
            "published_date": t0_payload.get("published_date"),
            "announcement_title": t0_payload.get("announcement_title"),
            "official_announcement_text": (t0_payload.get("official_announcement_text") or "")[:1500],
            "investor_relations_qa": (t0_payload.get("investor_relations_qa") or "")[:1500],
            "state_machine": sm,
            "shadow_proxies": t0_payload.get("shadow_proxies"),
            "card_strategy": card_strategy,
            "t0_payload": t0_payload,
        },
    }
