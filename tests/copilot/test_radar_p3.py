"""P3：17 T0 键 + 17 T1 算子装配。

[Ref: 27_ §3.7]
"""
from __future__ import annotations

from apps.copilot.modules.radar.t1.operators.registry import ALL_OPERATORS
from apps.copilot.modules.radar.t1.radar_matrix_assembler import assemble_fact_matrix


def _full_t0_raw() -> dict:
    return {
        "symbol": "601138",
        "macro": {
            "market_sentiment": {
                "status": "ok",
                "advance_ratio": 0.55,
                "total_turnover_yi": 9000.0,
                "turnover_vs_prev_pct": 2.0,
            },
            "sector_momentum": {
                "status": "ok",
                "industry": "电子",
                "pct_chg_3d": 4.5,
            },
            "sector_flow": {
                "status": "ok",
                "net_inflow_5d_yi": 12.3,
            },
        },
        "ecosystem": {
            "profile": {
                "status": "ok",
                "name": "工业富联",
                "industry": "电子制造",
                "business_intro": "智能制造与工业互联网",
                "llm_tag": "电子制造龙头",
            },
            "segment_breakdown": {
                "status": "ok",
                "segments": [
                    {"name": "通信设备", "revenue_ratio_pct": 72.0},
                    {"name": "云服务", "revenue_ratio_pct": 18.0},
                ],
            },
            "supply_chain": {
                "status": "ok",
                "top5_customer_pct": 45.0,
                "detail": "Top5 客户占比 45%",
            },
            "peer_ranking": {
                "status": "ok",
                "industry": "电子",
                "rank": 1,
                "peer_count": 80,
            },
        },
        "micro": {
            "bars_250d": {
                "status": "ok",
                "bars_count": 251,
                "summary": {
                    "above_ma20": True,
                    "ma20": 20.0,
                    "limit_up_count_20d": 1,
                    "side_tag": "多头排列",
                },
            },
            "northbound": {"status": "ok", "net_buy_5d_yi": 2.0, "net_buy_30d_yi": 5.0},
            "margin": {"status": "ok", "roc_5d": 0.02, "latest_date": "20250603"},
            "dragon_tiger": {"status": "skip", "detail": "无榜"},
        },
        "consensus": {
            "eps_forecast": {"status": "ok", "forecast_eps": 1.2, "report_count": 8},
            "rating_changes": {"status": "ok", "upgrade_proxy": 4},
        },
        "risk": {
            "financial_slice": {
                "status": "ok",
                "roe": 15.0,
                "operating_cashflow": 100.0,
                "net_profit_parent": 80.0,
            },
            "pledge": {"status": "ok", "pledge_ratio_pct": 12.0},
            "unlock_schedule": {
                "status": "ok",
                "events": [{"date": "2026-12-01", "ratio_pct": "2%"}],
            },
            "regulatory_events": {
                "status": "ok",
                "raw_text": "常规公告",
                "llm_tag": "监管常规",
            },
        },
    }


def test_all_seventeen_operators_registered():
    assert len(ALL_OPERATORS) == 17


def test_p3_fact_matrix_all_domains_green():
    fm, unavail = assemble_fact_matrix(_full_t0_raw(), {}, [])
    assert fm["global_and_meso"]["market_temperature"]["tag"] == "情绪回暖"
    assert fm["global_and_meso"]["sector_momentum"]["tag"] == "板块领涨"
    assert fm["ecosystem"]["company_profile"]["tag"] == "电子制造龙头"
    assert fm["ecosystem"]["peer_rank"]["tag"] == "赛道龙一"
    assert fm["microstructure"]["price_action"]["tag"] == "多头排列"
    assert fm["microstructure"]["northbound_flow"]["tag"] == "外资持续加仓"
    assert fm["consensus"]["eps_growth_forecast"]["tag"] == "高成长预期"
    assert fm["risks_red_flags"]["equity_pledge"]["tag"] == "质押可控"
    assert fm["risks_red_flags"]["regulatory"]["tag"] == "监管常规"
    assert "龙虎榜" in " ".join(unavail)


def test_p3_regulatory_requires_llm_tag():
    raw = _full_t0_raw()
    raw["risk"]["regulatory_events"] = {"status": "ok", "raw_text": "立案调查"}
    fm, unavail = assemble_fact_matrix(raw, {}, [])
    assert "DeepSeek" in " ".join(unavail)
    assert "regulatory" not in fm["risks_red_flags"] or fm["risks_red_flags"].get("regulatory") is None
