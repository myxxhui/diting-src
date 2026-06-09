"""T2 预执行 envelope 构建器单测。

[Ref: 28_ §5]
"""
from __future__ import annotations

import json
from pathlib import Path

from apps.copilot.modules.executing.probe_keys import PROBE_KEYS
from apps.copilot.modules.executing.t2_preexec_envelope import (
    ENVELOPE_VERSION,
    build_executing_opus_messages,
    build_t2_preexec_envelope,
    envelope_from_v1_file,
)


def _minimal_t1() -> dict:
    return {
        "batch_meta": {
            "execution_id": "batch_task_test",
            "timestamp": "2026-06-09T06:20:09Z",
            "total_stocks_checked": 1,
            "system_status": "Nominal",
            "account_available_cash": 100000.0,
            "money_unit": "人民币",
        },
        "portfolio_signals": {
            "601138.SH": {
                "stock_name": "工业富联",
                "position_context": {
                    "entry_date": "2026-04-10",
                    "cost_basis": 53.66,
                    "current_price": 74.18,
                    "unrealized_profit_pct": "38.01%",
                    "position_pct": "29.7%",
                    "holding_volume": 20000,
                },
                "indicators": {
                    "qmt_atr_trailing": {
                        "indicator_name": "动态ATR追踪止盈",
                        "value": 2.24,
                        "fact_statement": "test",
                    }
                },
            }
        },
    }


def test_build_envelope_v2_structure():
    env = build_t2_preexec_envelope(_minimal_t1())
    assert env["envelope_version"] == ENVELOPE_VERSION
    assert env["qa_index"]
    up = env["user_payload"]
    checklist = up["checklist"]["601138.SH"]
    assert checklist["jl1"][0]["reply"]["path"] == "symbol_audits.{symbol}.jl1"
    assert len(checklist["jl3"]) == 20
    cat = up["jl4_catalog"]["per_symbol"]["601138.SH"]
    assert len(cat) == len(PROBE_KEYS)
    assert cat[0]["question"]
    ex = env["output_contract"]["example"]
    assert "601138.SH" in ex["symbol_audits"]
    assert len(ex["symbol_audits"]["601138.SH"]["jl2"]) == 3
    assert len(ex["symbol_audits"]["601138.SH"]["jl3"]) == 20
    assert ex["Execution_Command"]["targets"][0]["symbol"] == "601138.SH"
    assert ex["probe_coverage"]["expected"] == 11


def test_opus_messages_split():
    env = build_t2_preexec_envelope(_minimal_t1())
    msgs = build_executing_opus_messages(env)
    user = json.loads(msgs[1]["content"])
    assert "qa_index" in user
    assert "jl4_catalog" in user


def test_envelope_from_v1_file(tmp_path: Path):
    v1 = tmp_path / "v1.json"
    t1 = _minimal_t1()
    v1.write_text(
        json.dumps({"envelope_version": "executing_t2_preexec_v1", "t1_payload": t1}, ensure_ascii=False),
        encoding="utf-8",
    )
    env = envelope_from_v1_file(str(v1))
    assert "601138.SH" in env["output_contract"]["example"]["symbol_audits"]
