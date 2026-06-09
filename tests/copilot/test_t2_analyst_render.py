"""T2 持仓分析 HTML 渲染单测。"""
from __future__ import annotations

from apps.copilot.modules.executing.t2_analyst_render import render_t2_assistant_card


def _sample_payload_ok() -> dict:
    return {
        "api_connected": True,
        "symbols": ["601138.SH", "002837.SZ", "300502.SZ"],
        "model_id": "claude-opus-4-6",
        "opus_meta": {"model": "claude-opus-4-6", "cost_yuan": 0.5, "tokens_in": 100, "tokens_out": 200},
        "envelope": {
            "user_payload": {
                "t1": {
                    "portfolio_signals": {
                        "601138.SH": {
                            "stock_name": "工业富联",
                            "position_context": {
                                "position_pct": 29.7,
                                "current_price": 24.74,
                                "holding_volume": 1500,
                                "unrealized_profit_pct": "+31.54%",
                            },
                        },
                        "002837.SZ": {
                            "stock_name": "英维克",
                            "position_context": {"unrealized_profit_pct": "-28.5%"},
                        },
                        "300502.SZ": {"stock_name": "新易盛", "position_context": {}},
                    }
                }
            }
        },
        "opus_audit": {
            "Execution_Command": {
                "action": "trim_30_pct",
                "one_sentence_summary": "英维克优先减仓",
                "stop_loss_line": "ATR 界碑 22.0",
                "targets": [
                    {"symbol": "601138.SH", "advice": "hold", "pct_change": "0%", "rationale": "逻辑完好"},
                    {"symbol": "002837.SZ", "advice": "trim", "pct_change": "-30%", "rationale": "JL4背离"},
                    {"symbol": "300502.SZ", "advice": "watch", "pct_change": "0%", "rationale": "观察"},
                ],
            },
            "Executing_Daily_Audit": {
                "L3_Fundamental_Verdict": "工业富联：逻辑完好。英维克：盘面承压。新易盛：观望。",
                "L4_Microstructure_Verdict": (
                    "英维克：多重红灯，持仓浮亏 -28.5%。"
                    "工业富联：黄灯偏中性，浮盈 +31.54% 仍有安全垫。"
                    "新易盛：绿灯。"
                ),
            },
            "Reasoning_Engine": {"cross_validation_logic": "英维克事出反常"},
            "symbol_audits": {
                "601138.SH": {
                    "near_term_advice": "hold",
                    "holding_honesty": "维持29.7%仓位；剩余资金观望；逻辑未断",
                    "jl1": [{"topic_id": "liquidity_regime", "status": "filled", "answer": "M2同比+8%"}],
                    "jl2": [{"topic_id": "ai_server_odm", "status": "partial", "answer": "GB200放量"}],
                    "jl3": [{"key": "fii_twse_cloud", "status": "empty", "answer": ""}],
                    "jl4_read": [{"key": "qmt_atr_trailing", "reading": "未破界碑"}],
                },
                "002837.SZ": {
                    "near_term_advice": "trim",
                    "holding_honesty": "减持至15%；剩余资金不买",
                    "jl1": [{"topic_id": "liquidity_regime", "status": "filled", "answer": "融资余额高位"}],
                    "jl2": [],
                    "jl3": [],
                    "jl4_read": [{"key": "smart_money_flow", "reading": "主力流出"}],
                },
                "300502.SZ": {
                    "near_term_advice": "watch",
                    "holding_honesty": "观望",
                    "jl4_read": [],
                },
            },
        },
        "request_id": "abc123",
    }


def test_render_success_three_symbols():
    html = render_t2_assistant_card(_sample_payload_ok(), {"status": "ok", "request_id": "abc123"})
    assert "组合结论" in html
    assert "逐标的建议" in html
    assert "601138.SH" in html
    assert "002837.SZ" in html
    assert "300502.SZ" in html
    assert "工业富联" in html
    assert "减持 30%" in html
    assert "英维克优先减仓" in html
    assert "按标的分段" in html
    assert "T1 浮盈" in html
    assert "T1 浮亏" in html
    assert "非组合加总" in html
    assert "JL1 宏观" in html
    assert "JL3 微观靶向" in html
    assert "持仓诚实（加仓/维持/减仓" in html
    assert "（无数据）" in html
    assert "<details" in html
    assert "点击展开" in html


def test_render_error():
    payload = {
        "preview_only": True,
        "opus_error": "Connection error",
        "symbols": ["601138.SH"],
        "jl4_indicator_counts": {"601138.SH": 11},
    }
    html = render_t2_assistant_card(payload, {"status": "error", "error": "Connection error"})
    assert "分析未完成" in html
    assert "Connection error" in html
