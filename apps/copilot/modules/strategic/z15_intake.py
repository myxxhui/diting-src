"""Z1.5 intake 校验 · 携带 Z0 段永平双闸只读包。

[Ref: 32_ §2.4.9.c · cognition_gates.yaml]
"""
from __future__ import annotations

from typing import Any, Optional

from apps.copilot.modules.strategic.duan_config import load_cognition_gates


def validate_z15_intake(
    *,
    node_duan_verdict: str,
    stock_duan_verdict: str,
    gate_a_passed: bool = True,
) -> tuple[bool, list[str]]:
    """Z1.5 启动硬条件。"""
    cfg = load_cognition_gates().get("z15_intake_requires") or {}
    allowed_node = cfg.get("node_duan_verdict") or ["pass", "review"]
    allowed_stock = cfg.get("stock_duan_anchor") or ["anchor", "watch"]
    errors: list[str] = []
    if node_duan_verdict not in allowed_node:
        errors.append(f"node_duan_verdict={node_duan_verdict} not in {allowed_node}")
    if stock_duan_verdict not in allowed_stock:
        errors.append(f"stock_duan_anchor={stock_duan_verdict} not in {allowed_stock}")
    if cfg.get("gate_a") == "pass" and not gate_a_passed:
        errors.append("gate_a_not_pass")
    return (len(errors) == 0, errors)


def build_z15_intake_payload(
    symbol: str,
    *,
    node_duan_pack: dict[str, Any],
    stock_duan_anchor: dict[str, Any],
    cvm_snapshot: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Z1.5 输入携带（只读）。"""
    return {
        "symbol": symbol,
        "node_duan_pack": node_duan_pack,
        "stock_duan_anchor": stock_duan_anchor,
        "cvm_snapshot": cvm_snapshot or {},
        "z0_depth_boundary": "L3_only_in_z15",
    }


def extract_duan_from_stock_pool(
    stock_pool: dict[str, Any],
    symbol: str,
    node_id: Optional[str] = None,
) -> tuple[Optional[dict], Optional[dict]]:
    """从 BOM stock_pool 提取某标的的双闸 pack。"""
    for node in stock_pool.get("bom_nodes") or []:
        nid = str(node.get("node_id", ""))
        if node_id and nid != node_id:
            continue
        node_pack = node.get("node_duan_pack")
        for st in node.get("stocks") or []:
            if st.get("symbol") == symbol:
                return node_pack, st.get("stock_duan_anchor")
    return None, None
