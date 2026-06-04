"""601138 profile · 25 probe keys。

[Ref: 28_ §4.5]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROBE_KEYS: tuple[str, ...] = (
    "nvda_gpu_leadtime",
    "tsmc_cowos_capacity",
    "parent_honhai_revenue",
    "cloud_capex_consensus",
    "smci_quanta_share",
    "gb200_iteration_node",
    "inventory_turnover",
    "contract_liabilities",
    "copper_cost_pressure",
    "cpi_ppi_spread",
    "exchange_rate_impact",
    "mgmt_and_core_team",
    "related_party_trans",
    "gross_margin_trend",
    "qmt_atr_trailing",
    "volume_price_div",
    "northbound_net_flow",
    "level2_super_order",
    "margin_short_skew",
    "turnover_acceleration",
    "block_trade_discount",
    "retail_concentration",
    "insider_sell_actual",
    "etf_redemption_impact",
    "tech_beta_correlation",
)

L3_KEYS = PROBE_KEYS[:14]
L4_KEYS = PROBE_KEYS[14:]


def load_profile(profile: str = "601138") -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4] / "data" / "config" / "executing_profiles"
    path = root / f"{profile}.yaml"
    if not path.is_file():
        return {"symbol": "601138", "probes": {}}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
