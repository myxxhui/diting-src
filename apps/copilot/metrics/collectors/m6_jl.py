"""Z0-M6 · 战略 JL1/JL2 探针值采集与板块红灯聚合。

[Ref: 34_ §3.5 · jl_catalog.py]
JL1 宏观 — CPI-PPI/铜价 · 每 board 配置不同 keys
JL2 行业 — GPU交期/CoWoS/Capex · 行业风险因子
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ─── JL1 探针采集器 ────────────────────────────────────────────────

def collect_jl1_cpi_ppi_spread(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """JL1: 通胀剪刀差 — 从 M1 继承 CPI-PPI spread。"""
    snap = (metrics or {}).get("M.macro.cpi_ppi_spread") or {}
    if snap.get("status") != "ok":
        return _probe_result("cpi_ppi_spread", "pending", "no_data", None, "M1 CPI-PPI 未采集")
    data = snap.get("data") or {}
    spread = data.get("spread_ppt")
    if spread is None:
        return _probe_result("cpi_ppi_spread", "pending", "no_data", None)
    # spread < -2 (通缩压力) → red; > 0 → green
    level = "red" if spread < -2 else "yellow" if spread < 0 else "green"
    return _probe_result("cpi_ppi_spread", level, f"剪刀差={spread}ppt", spread)


def collect_jl1_copper_price() -> dict[str, Any]:
    """JL1: 铜价极端行情 — LME/SHFE 期货。"""
    try:
        import akshare as ak

        df = ak.futures_spot_price_previous()
        if df is None or df.empty:
            return _probe_result("lme_copper_spike", "pending", "no_data", None)
    except Exception as exc:  # noqa: BLE001
        return _probe_result("lme_copper_spike", "pending", "no_data", None, f"akshare: {exc}")
    return _probe_result("lme_copper_spike", "green", "铜价正常（启动期默认绿）", 0)


# ─── JL2 探针采集器 ────────────────────────────────────────────────

def collect_jl2_cloud_capex(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """JL2: 四云 Capex 共识 — 从 M3 继承。"""
    snap = (metrics or {}).get("M.policy.capex_total") or {}
    if snap.get("status") != "ok":
        return _probe_result("cloud_capex_consensus", "pending", "no_data", None, "M3 Capex 未采集")
    data = snap.get("data") or {}
    yoy = data.get("yoy_pct")
    level = "green" if yoy and yoy > 10 else "yellow" if yoy and yoy > 0 else "red" if yoy else "pending"
    return _probe_result("cloud_capex_consensus", level, f"Capex YoY={yoy}%", yoy)


def collect_jl2_dram_cycle() -> dict[str, Any]:
    """JL2: 存储周期 — 启动期默认 neutral（需 SEMI 报告）。"""
    return _probe_result("dram_cycle_peak", "green", "启动期默认 — 待接入 SEMI", 0)


def collect_jl2_gpu_leadtime(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """JL2: GPU 交期 — 间接从 Capex 增速 + US10Y 推断。"""
    us10y = (metrics or {}).get("M.macro.us10y") or {}
    capex = (metrics or {}).get("M.policy.capex_total") or {}
    c_yoy = (capex.get("data") or {}).get("yoy_pct") if capex.get("status") == "ok" else None
    level = "yellow" if c_yoy and c_yoy > 20 else "green"  # Capex 飙涨 → GPU 紧张
    return _probe_result("nvda_gpu_leadtime", level, f"间接推断 Capex_YoY={c_yoy}%", c_yoy)


def collect_jl2_tsmc_cowos(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """JL2: CoWoS 封装产能 — 启动期默认（需台积电法说）。"""
    return _probe_result("tsmc_cowos_capacity", "green", "启动期默认 — 待接台积电法说", 0)


# ─── 探针辅助函数 ──────────────────────────────────────────────────

def _probe_result(
    probe_key: str,
    level: str = "green",
    detail: str = "",
    value: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    return {
        "probe_key": probe_key,
        "level": level,  # green | yellow | red | pending
        "detail": detail or note or level,
        "value": value,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }


# ─── JL 聚合面板 ────────────────────────────────────────────────────

def aggregate_jl_panel(
    metrics: dict[str, Any] | None = None,
    board_id: int | None = None,
) -> dict[str, Any]:
    """聚合 JL1+JL2 探针 → 板块级红灯面板。

    Returns:
        { status, panel: { jl1: [...], jl2: [...], red_count, yellow_count, overall }
    """
    jl1_probes = [
        collect_jl1_cpi_ppi_spread(metrics),
        collect_jl1_copper_price(),
    ]
    jl2_probes = [
        collect_jl2_cloud_capex(metrics),
        collect_jl2_dram_cycle(),
        collect_jl2_gpu_leadtime(metrics),
        collect_jl2_tsmc_cowos(metrics),
    ]

    all_probes = jl1_probes + jl2_probes
    reds = [p for p in all_probes if p["level"] == "red"]
    yellows = [p for p in all_probes if p["level"] == "yellow"]

    overall = "green"
    if len(reds) >= 2:
        overall = "red"
    elif len(reds) >= 1 or len(yellows) >= 2:
        overall = "yellow"

    # 产生红灯摘要
    alert_summary = ""
    if reds:
        alert_summary = " | ".join(
            f"{r['probe_key']}={r['detail']}" for r in reds
        )

    return {
        "status": "ok" if overall != "pending" else "partial",
        "metric_id": "M.strategic.jl_panel",
        "board_id": board_id,
        "panel": {
            "jl1": jl1_probes,
            "jl2": jl2_probes,
            "red_count": len(reds),
            "yellow_count": len(yellows),
            "overall": overall,
            "red_probes": [r["probe_key"] for r in reds],
            "yellow_probes": [p["probe_key"] for p in yellows],
        },
        "alert_summary": alert_summary or None,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "rule:z0_jl_v1",
    }
