"""JL1/JL2 指标库（与 28_ §2.0 对齐）。

[Ref: 33_五区工作台_前端区际联动与数据携带契约.md §4.3]
"""
from __future__ import annotations

from typing import Any

JL_PROBE_CATALOG: dict[str, dict[str, Any]] = {
    "cpi_ppi_spread": {
        "layer": "JL1",
        "label": "通胀剪刀差",
        "cadence": "月",
        "source_hint": "国家统计局 CPI/PPI",
    },
    "cloud_capex_consensus": {
        "layer": "JL2",
        "label": "四云 Capex 共识",
        "cadence": "季",
        "source_hint": "MSFT/GOOG/META/AMZN 季报",
    },
    "nvda_gpu_leadtime": {
        "layer": "JL2",
        "label": "GPU 交期",
        "cadence": "月",
        "source_hint": "供应链交期跟踪",
    },
    "tsmc_cowos_capacity": {
        "layer": "JL2",
        "label": "CoWoS 封装产能",
        "cadence": "季",
        "source_hint": "台积电法说会",
    },
    "lme_copper_spike": {
        "layer": "JL1",
        "label": "铜价极端行情",
        "cadence": "日",
        "source_hint": "LME/SHFE 铜期货",
    },
    "copper_optical_shift": {
        "layer": "JL2",
        "label": "铜退光缓",
        "cadence": "动态",
        "source_hint": "NVDA/AMD 互联规范",
    },
    "dram_cycle_peak": {
        "layer": "JL2",
        "label": "存储周期见顶",
        "cadence": "季",
        "source_hint": "三星/海力士 Capex",
    },
    "cxl_adoption_risk": {
        "layer": "JL2",
        "label": "CXL 架构退潮",
        "cadence": "动态",
        "source_hint": "OCP 峰会 / 云架构白皮书",
    },
    "intel_platform_delay": {
        "layer": "JL2",
        "label": "服务器平台推迟",
        "cadence": "动态",
        "source_hint": "Intel/AMD 路线图",
    },
    "eda_ip_sanction": {
        "layer": "JL2",
        "label": "EDA/IP 断供",
        "cadence": "动态",
        "source_hint": "BIS / ARM/Synopsys 公告",
    },
    "tsmc_advanced_restriction": {
        "layer": "JL2",
        "label": "先进制程受限",
        "cadence": "动态",
        "source_hint": "台湾出口管制 / TSMC 法说",
    },
    "tfln_disruption": {
        "layer": "JL2",
        "label": "薄膜铌酸锂替代",
        "cadence": "动态",
        "source_hint": "OFC / 龙头新品",
    },
    "domestic_optical_price_war": {
        "layer": "JL2",
        "label": "国内光器件价格战",
        "cadence": "动态",
        "source_hint": "三大运营商集采",
    },
}


def catalog_entry(probe_key: str) -> dict[str, Any]:
    meta = JL_PROBE_CATALOG.get(probe_key) or {}
    return {
        "probe_key": probe_key,
        "layer": meta.get("layer", "JL2"),
        "label": meta.get("label", probe_key),
        "cadence": meta.get("cadence", "—"),
        "source_hint": meta.get("source_hint", "—"),
    }
