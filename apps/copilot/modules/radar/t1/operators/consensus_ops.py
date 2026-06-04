"""T1 算子 op_t12~op_t13。

[Ref: 27_ §3.5]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t1.operators.types import OpResult, node


def op_t12_eps_growth(t0_raw: dict[str, Any]) -> OpResult:
    eps = (t0_raw.get("consensus") or {}).get("eps_forecast") or {}
    if eps.get("status") != "ok":
        return OpResult("consensus", "eps_growth_forecast", None, "缺少 T0-12 一致预期")
    val = eps.get("forecast_eps")
    tag = "高成长预期" if val is not None else "预期待更新"
    return OpResult(
        "consensus",
        "eps_growth_forecast",
        node(val, tag, f"研报 {eps.get('report_count')} 份 · 预测 EPS {val}"),
    )


def op_t13_rating_surge(t0_raw: dict[str, Any]) -> OpResult:
    rc = (t0_raw.get("consensus") or {}).get("rating_changes") or {}
    if rc.get("status") != "ok":
        return OpResult("consensus", "rating_momentum", None, "缺少 T0-13 评级变动")
    up = int(rc.get("upgrade_proxy") or 0)
    tag = "机构密集翻多" if up >= 3 else "评级平稳"
    return OpResult(
        "consensus",
        "rating_momentum",
        node(up, tag, f"近六月买入+增持 {up} 家（proxy）"),
    )
