"""Z0-M4 · 生态位 E1～E5 评分器（规则版 T1 · per niche_template）。

[Ref: 34_ §3.3 · 32_ §2.4.4]
依赖 M2 政策赛道 + M3 Capex · 按 phase×niche 定制输出 ecosystem_scores
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def score_e1_profit_position(
    capex: dict[str, Any] | None,
    niche_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """E1 利润卡位 — 钱在链上哪一环 · 依赖 M3 Capex 方向。

    启动期 T1 规则：Capex YoY 增速越高 → 上游硬件利润卡位越强。
    """
    cdata = (capex.get("data") or {}) if capex and capex.get("status") == "ok" else {}
    yoy = cdata.get("yoy_pct")
    total = cdata.get("capex_total_b")
    if yoy is None and total is None:
        return {"band": "pending", "score": 0.0, "trend": "flat", "reason": "Capex 不可用"}

    band = "pending"
    if yoy is not None:
        if yoy > 20:
            band = "high"
        elif yoy > 10:
            band = "mid_high"
        elif yoy > 0:
            band = "mid"
        else:
            band = "low"

    score = _clamp01(0.5 + (yoy or 0) / 40.0)
    return {
        "band": band,
        "score": round(score, 4),
        "trend": "up" if yoy and yoy > 5 else "flat",
        "inputs": {"capex_yoy_pct": yoy, "capex_total_b": total},
        "reason": f"Capex YoY={yoy}%",  # noqa
    }


def score_e2_scarcity_bottleneck(
    policy: dict[str, Any] | None,
    niche_themes: set[str] | None = None,
) -> dict[str, Any]:
    """E2 稀缺/卡脖子 — 供给约束是否利好本环节。

    启动期 T1 规则：政策赛道命中高顺风方向 + niche 主题匹配 → 高稀缺分。
    """
    pdata = (policy.get("data") or {}) if policy and policy.get("status") == "ok" else {}
    top_sectors = pdata.get("top_sectors") or []
    themes = niche_themes or set()

    matched = [s for s in top_sectors if s.get("sector") in themes]
    score = min(0.9, 0.4 + len(matched) * 0.15)
    band = "high" if score >= 0.7 else "mid_high" if score >= 0.5 else "mid"
    return {
        "band": band,
        "score": round(score, 4),
        "matched_themes": [m["sector"] for m in matched],
        "reason": f"政策命中 {len(matched)}/{len(themes)} 主题",
    }


def score_e3_policy_wind(
    policy: dict[str, Any] | None,
) -> dict[str, Any]:
    """E3 政策顺逆 — 从 M2 政策方向继承。

    启动期：直接复用 M2 policy_direction 的输出。
    """
    pdata = (policy.get("data") or {}) if policy and policy.get("status") == "ok" else {}
    top = (pdata.get("top_sectors") or [])
    if not top:
        return {"band": "pending", "score": 0.35, "trend": "flat", "reason": "政策数据缺失"}

    max_score = max(s.get("policy_score", 0) for s in top)
    band = "high" if max_score >= 7 else "mid_high" if max_score >= 5 else "mid"
    return {
        "band": band,
        "score": round(_clamp01(max_score / 12.0), 4),
        "trend": "tailwind" if band in ("high", "mid_high") else "neutral",
        "reason": f"政策首位得分={max_score:.1f}",
    }


def score_e4_stage_fit(
    capex: dict[str, Any] | None,
    s_curve_position: str = "early",
) -> dict[str, Any]:
    """E4 阶段契合 — S 曲线位置与 Capex 周期对齐度。

    启动期 T1：early=S曲线早期看 Capex 增速 · mature=看利润拐点。
    """
    cdata = (capex.get("data") or {}) if capex and capex.get("status") == "ok" else {}
    yoy = cdata.get("yoy_pct")

    band = "pending"
    if s_curve_position == "early":
        if yoy is not None:
            band = "high" if yoy > 15 else "mid_high" if yoy > 5 else "mid"
    elif s_curve_position == "growth":
        band = "high" if yoy and yoy > 5 else "mid_high"
    elif s_curve_position == "mature":
        band = "high" if yoy and 0 <= yoy <= 10 else "mid"

    score = _clamp01(0.5 + (yoy or 0) / 30.0)
    return {
        "band": band,
        "score": round(score, 4),
        "stage": s_curve_position,
        "reason": f"S曲线={s_curve_position} Capex YoY={yoy}%",
    }


def score_e5_sustainability(
    e1: dict[str, Any],
    e2: dict[str, Any],
    e3: dict[str, Any],
    e4: dict[str, Any],
) -> dict[str, Any]:
    """E5 持续性 — 综合 E1～E4 是否 2～3 年主线。

    启动期 T1：取 E1～E4 加权综合。
    """
    scores = [
        e1.get("score", 0),
        e2.get("score", 0),
        e3.get("score", 0),
        e4.get("score", 0),
    ]
    avg = sum(scores) / max(len(scores), 1)
    band = "high" if avg >= 0.7 else "mid_high" if avg >= 0.5 else "mid"
    return {
        "band": band,
        "score": round(avg, 4),
        "sub_scores": {
            "e1": e1.get("score"),
            "e2": e2.get("score"),
            "e3": e3.get("score"),
            "e4": e4.get("score"),
        },
        "reason": f"E1~E4综合={avg:.2f}",
    }


def score_ecosystem_bundle(
    *,
    capex_metric: dict[str, Any] | None = None,
    policy_metric: dict[str, Any] | None = None,
    niche_themes: set[str] | None = None,
    s_curve_position: str = "early",
) -> dict[str, Any]:
    """段 C · 按 niche 输出完整 ecosystem_scores。

    Returns:
        { status, ecosystem_scores: {e1, e2, e3, e4, e5}, as_of }
    """
    e1 = score_e1_profit_position(capex_metric)
    e2 = score_e2_scarcity_bottleneck(policy_metric, niche_themes)
    e3 = score_e3_policy_wind(policy_metric)
    e4 = score_e4_stage_fit(capex_metric, s_curve_position=s_curve_position)
    e5 = score_e5_sustainability(e1, e2, e3, e4)

    ok = all(
        s["band"] != "pending"
        for s in (e1, e2, e3, e4)
    )
    return {
        "status": "ok" if ok else "partial",
        "metric_id": "M.niche.ecosystem_scores",
        "niche_themes": list(niche_themes or []),
        "s_curve_position": s_curve_position,
        "ecosystem_scores": {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5},
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "rule:z0_ecosystem_v1",
    }
