"""Z0 段永平双闸 · 单元测试 [Ref: 32_ §2.4.9]"""
from __future__ import annotations

import pytest

from apps.copilot.modules.strategic import cvm_scorer
from apps.copilot.modules.strategic.duan_config import clear_config_cache
from apps.copilot.modules.strategic.duan_dual_gate import compute_duan_dual_gates
from apps.copilot.modules.strategic.z15_intake import build_z15_intake_payload, validate_z15_intake


@pytest.fixture(autouse=True)
def _clear_cfg():
    clear_config_cache()
    yield
    clear_config_cache()


# ── Z0-A 节点闸 ──


def test_node_provisional_without_t2():
    nd = cvm_scorer.score_node_segment_duan(
        node_id="n1", tier="核心", ecosystem_layer="L2",
    )
    assert nd["verdict"] == "provisional"
    assert "待" in nd["display"]
    assert nd["provisional"] is True


def test_node_pass_with_t2():
    t2 = {
        "segment_bypass_risk": "low",
        "profit_pool_anchor": "in_segment",
        "horizon_outlook": "expand",
    }
    nd = cvm_scorer.score_node_segment_duan(
        node_id="n2", tier="核心", ecosystem_layer="L2", node_t2=t2,
    )
    assert nd["verdict"] == "pass"
    assert nd["display"] == "✅好生意"


def test_node_n1_marginal_goes_review_not_reject():
    t2 = {
        "segment_bypass_risk": "low",
        "profit_pool_anchor": "in_segment",
        "horizon_outlook": "expand",
    }
    nd = cvm_scorer.score_node_segment_duan(
        node_id="n3", tier="重要", ecosystem_layer="L5", node_t2=t2,
    )
    assert nd["n1_status"] == "marginal"
    assert nd["verdict"] == "review"
    assert nd["display"] == "❓需深研"


def test_node_reject_n1_fail():
    t2 = {
        "segment_bypass_risk": "low",
        "profit_pool_anchor": "in_segment",
        "horizon_outlook": "expand",
    }
    nd = cvm_scorer.score_node_segment_duan(
        node_id="n4", tier="配套", ecosystem_layer="L4", node_t2=t2,
    )
    assert nd["n1_status"] == "fail"
    assert nd["verdict"] == "reject"


# ── Z0-B 标的闸 ──


def test_stock_inherit_provisional_node():
    nd = cvm_scorer.score_node_segment_duan(node_id="x", tier="核心", ecosystem_layer="L2")
    st = cvm_scorer.score_stock_duan_anchor(
        symbol="300308", node_duan=nd, ecosystem_position="光模块龙头",
    )
    assert st["verdict"] == "inherit_wait"
    assert "待环节T2" in st["display"]


def test_stock_review_node_capped_at_watch():
    t2 = {"segment_bypass_risk": "mid", "profit_pool_anchor": "in_segment", "horizon_outlook": "stable"}
    nd = cvm_scorer.score_node_segment_duan(
        node_id="r", tier="核心", ecosystem_layer="L2", node_t2=t2,
    )
    assert nd["verdict"] == "review"
    st = cvm_scorer.score_stock_duan_anchor(
        symbol="300308", node_duan=nd, ecosystem_position="光模块龙头",
    )
    assert st["verdict"] == "watch"
    assert "🟡" in st["display"]


def test_stock_oem_sentinel_reject():
    t2 = {"segment_bypass_risk": "low", "profit_pool_anchor": "in_segment", "horizon_outlook": "expand"}
    nd = cvm_scorer.score_node_segment_duan(node_id="o", tier="核心", ecosystem_layer="L2", node_t2=t2)
    st = cvm_scorer.score_stock_duan_anchor(
        symbol="000001", node_duan=nd, ecosystem_position="代工制造",
    )
    assert st["verdict"] == "reject"
    assert "伪龙头" in st["display"]


def test_top2_anchor_cap():
    packs = {
        "n:a": {"verdict": "anchor", "display": "🟢", "irreplaceability": 0.9, "pool_gate_passed": True},
        "n:b": {"verdict": "anchor", "display": "🟢", "irreplaceability": 0.8, "pool_gate_passed": True},
        "n:c": {"verdict": "anchor", "display": "🟢", "irreplaceability": 0.7, "pool_gate_passed": True},
    }
    capped = cvm_scorer.apply_top2_anchor_cap(packs, max_green=2)
    anchors = [p for p in capped.values() if p["verdict"] == "anchor"]
    watches = [p for p in capped.values() if p["verdict"] == "watch"]
    assert len(anchors) == 2
    assert len(watches) == 1
    assert watches[0].get("reason") == "top2_cap_exceeded"


# ── 编排 + Z1.5 ──


def test_compute_dual_gates_on_minimal_pool():
    pool = {
        "status": "ok",
        "bom_nodes": [{
            "node_id": "gpu",
            "name": "GPU",
            "tier": "核心",
            "ecosystem_layer": "L2",
            "node_duan_t2": {
                "segment_bypass_risk": "low",
                "profit_pool_anchor": "in_segment",
                "horizon_outlook": "expand",
            },
            "stocks": [{"symbol": "300308", "ecosystem_position": "光模块龙头"}],
        }],
    }
    node_scores, stock_scores, enriched = compute_duan_dual_gates(pool, persist_to_pool=True)
    assert "gpu" in node_scores
    assert "gpu:300308" in stock_scores
    assert enriched["bom_nodes"][0].get("node_duan_pack")
    assert enriched["bom_nodes"][0]["stocks"][0].get("stock_duan_anchor")


def test_z15_intake_validation():
    ok, errs = validate_z15_intake(
        node_duan_verdict="pass", stock_duan_verdict="anchor", gate_a_passed=True,
    )
    assert ok and not errs
    ok2, errs2 = validate_z15_intake(
        node_duan_verdict="reject", stock_duan_verdict="anchor", gate_a_passed=True,
    )
    assert not ok2
    assert errs2

    payload = build_z15_intake_payload(
        "300308",
        node_duan_pack={"verdict": "pass"},
        stock_duan_anchor={"verdict": "anchor"},
    )
    assert payload["node_duan_pack"]["verdict"] == "pass"
