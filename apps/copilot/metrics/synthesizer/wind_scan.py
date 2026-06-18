"""Z0-M0 wind_scan 规则合成（T1 为主 · 可选 T2 不在此模块）。

[Ref: 34_ §3.0a · 32_ §2.4.1]
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def build_p0_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    regime = metrics.get("M.liq.regime_composite") or {}
    pmi = metrics.get("M.macro.pmi") or {}
    rdata = (regime.get("data") or {}) if regime.get("status") == "ok" else {}
    pdata = (pmi.get("data") or {}) if pmi.get("status") == "ok" else {}
    return {
        "liquidity_regime": rdata.get("liquidity_regime", "pending"),
        "p0_prime": rdata.get("p0_prime"),
        "macro_regime": rdata.get("macro_regime") or pdata.get("regime", "pending"),
        "pmi": pdata.get("pmi"),
    }


def _liquidity_modifier(p0: dict[str, Any]) -> float:
    lr = p0.get("liquidity_regime")
    if lr == "risk_off" or p0.get("p0_prime"):
        return 0.75
    if lr == "risk_on":
        return 1.05
    if lr == "mild_inflow":
        return 1.0
    return 0.95


def _macro_modifier(p0: dict[str, Any]) -> float:
    mr = p0.get("macro_regime")
    if mr == "expansion":
        return 1.05
    if mr == "contraction":
        return 0.9
    return 1.0


def _merge_sector_inputs(metrics: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """合并概念热度 + 政策支路 → 去重 sector 输入。"""
    merged: dict[str, dict[str, Any]] = {}
    sources: list[str] = []

    heat = metrics.get("M.sector.concept_heat") or {}
    if heat.get("status") == "ok":
        sources.append(str(heat.get("source", "concept_heat")))
        for item in (heat.get("data") or {}).get("top_sectors") or []:
            sector = str(item.get("sector", "")).strip()
            if not sector:
                continue
            merged[sector] = {
                "sector": sector,
                "raw_change_pct": float(item.get("change_pct", 0)),
                "policy_boost": 0.0,
                "evidence_summary": f"概念/板块近端涨跌幅 {item.get('change_pct')}%",
                "metric_ids": ["M.sector.concept_heat"],
                "evidence_spans": [
                    {
                        "source": heat.get("source", "market"),
                        "span": f"涨跌幅 {item.get('change_pct')}%",
                        "metric_id": "M.sector.concept_heat",
                    }
                ],
            }

    policy = metrics.get("M.sector.policy_direction") or {}
    if policy.get("status") == "ok":
        sources.append(str(policy.get("source", "policy")))
        pdata = policy.get("data") or {}
        ev_map: dict[str, list[dict[str, Any]]] = {}
        for ev in pdata.get("evidence") or []:
            sec = str(ev.get("sector", "")).strip()
            if sec:
                ev_map.setdefault(sec, []).append(ev)

        for item in pdata.get("top_sectors") or []:
            sector = str(item.get("sector", "")).strip()
            if not sector:
                continue
            boost = min(0.25, float(item.get("policy_score", 0)) / 20.0)
            snippet = ""
            ev_list = ev_map.get(sector) or []
            if ev_list:
                snippet = str(ev_list[0].get("snippet", ""))[:120]
            if sector in merged:
                merged[sector]["policy_boost"] = max(merged[sector].get("policy_boost", 0), boost)
                merged[sector]["metric_ids"].append("M.sector.policy_direction")
                merged[sector]["evidence_spans"].append(
                    {
                        "source": policy.get("source"),
                        "span": snippet or f"政策命中 {item.get('hit_count')} 次",
                        "metric_id": "M.sector.policy_direction",
                    }
                )
                merged[sector]["evidence_summary"] += f" · 政策支路命中"
            else:
                merged[sector] = {
                    "sector": sector,
                    "raw_change_pct": 0.0,
                    "policy_boost": boost,
                    "evidence_summary": snippet or f"DeepSea 政策/产业文档命中 {item.get('hit_count')} 次",
                    "metric_ids": ["M.sector.policy_direction"],
                    "evidence_spans": [
                        {
                            "source": policy.get("source"),
                            "span": snippet or f"policy_score={item.get('policy_score')}",
                            "metric_id": "M.sector.policy_direction",
                        }
                    ],
                }

    return list(merged.values()), sources


def synthesize_wind_scan(metrics: dict[str, Any], *, top_n: int = 10) -> dict[str, Any]:
    """从已采集 metric 快照合成 wind_scan 候选池。"""
    p0 = build_p0_snapshot(metrics)
    m1_ok = metrics.get("M.macro.pmi", {}).get("status") == "ok"
    m5_ok = metrics.get("M.liq.regime_composite", {}).get("status") == "ok"
    if not (m1_ok and m5_ok):
        missing = []
        if not m1_ok:
            missing.append("M1 宏观")
        if not m5_ok:
            missing.append("M5 流动性")
        return {
            "status": "empty",
            "blocker": f"采集未就绪：{', '.join(missing)} · 请先 z0-bootstrap-all",
            "p0_snapshot": p0,
            "candidates": [],
            "advisory_only": True,
        }

    sector_inputs, merge_sources = _merge_sector_inputs(metrics)
    liq_mod = _liquidity_modifier(p0)
    macro_mod = _macro_modifier(p0)

    candidates: list[dict[str, Any]] = []
    for s in sector_inputs:
        chg = float(s.get("raw_change_pct", 0))
        base = _clamp01(0.5 + chg / 20.0 + float(s.get("policy_boost", 0)))
        score = round(_clamp01(base * liq_mod * macro_mod), 4)
        candidates.append(
            {
                "sector": s["sector"],
                "wind_score": score,
                "rank": 0,
                "evidence_summary": s.get("evidence_summary"),
                "evidence_spans": s.get("evidence_spans") or [],
                "macro_wind_refs": ["M.macro.pmi", "M.liq.regime_composite"]
                + list(dict.fromkeys(s.get("metric_ids") or [])),
            }
        )

    candidates.sort(key=lambda x: x["wind_score"], reverse=True)
    candidates = candidates[:top_n]
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i

    if not candidates:
        heat_st = (metrics.get("M.sector.concept_heat") or {}).get("status")
        pol_st = (metrics.get("M.sector.policy_direction") or {}).get("status")
        return {
            "status": "empty",
            "blocker": (
                f"M1/M5 已就绪 · M2 双支路均未产出赛道（concept={heat_st}, policy={pol_st}）"
                " · 可重试 z0-m2-sector-heat"
            ),
            "p0_snapshot": p0,
            "candidates": [],
            "advisory_only": True,
        }

    return {
        "status": "ready",
        "blocker": None,
        "p0_snapshot": p0,
        "candidates": candidates,
        "advisory_only": True,
        "merge_sources": merge_sources,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
