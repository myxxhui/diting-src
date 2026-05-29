"""cryo_guard step_03 蒸馏阶段 A：Mock Teacher + 小批量 + 导出 + 守门。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import apps.cryo_guard.db.models  # noqa: F401 注册表
import apps.cryo_guard.db.sync_session as sync_sm
from apps.cryo_guard.db.models import Announcement, FinancialReport, RelatedPartyRaw, TeacherDistill
from apps.cryo_guard.db.session import Base
from apps.cryo_guard.distillation.distill_runner import run as distill_run
from apps.cryo_guard.distillation.exporter import export_engine_to_llama_factory
from apps.cryo_guard.distillation.prompts import build_prompt
from apps.cryo_guard.distillation.teacher_client import parse_teacher_output
from apps.cryo_guard.distillation.verifier import auto_accept_if_safe

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def cg_sqlite(tmp_path, monkeypatch):
    """将 cryo_guard 同步库指向临时 SQLite。"""
    db_path = tmp_path / "cryo.db"
    url = f"sqlite:///{db_path}"
    eng = create_engine(url, future=True)
    monkeypatch.setattr(sync_sm, "engine_sync", eng)
    monkeypatch.setattr(
        sync_sm,
        "SessionLocalSync",
        sessionmaker(bind=eng, expire_on_commit=False, class_=Session),
    )
    Base.metadata.create_all(eng)
    yield tmp_path, eng


def _seed_financial(eng) -> None:
    with Session(eng) as s:
        s.add(
            FinancialReport(
                symbol="000001",
                company_name="测试公司",
                report_date=date(2022, 12, 31),
                report_type="annual",
                raw_balance_sheet={},
                raw_income_statement={},
                raw_cash_flow={},
                revenue=1e9,
                net_profit=1e8,
                gross_profit=3e8,
                cash_and_equivalents=2e8,
                cost_of_revenue=7e8,
                accounts_receivable=1e8,
                inventory=5e7,
                operating_cash_flow=9e7,
            )
        )
        s.add(
            FinancialReport(
                symbol="000001",
                company_name="测试公司",
                report_date=date(2023, 12, 31),
                report_type="annual",
                raw_balance_sheet={},
                raw_income_statement={},
                raw_cash_flow={},
                revenue=1.2e9,
                net_profit=1.1e8,
                gross_profit=3.6e8,
                cash_and_equivalents=2.2e8,
                cost_of_revenue=8.4e8,
                short_term_debt=5e7,
                long_term_debt=1e8,
                accounts_receivable=1.1e8,
                inventory=5.5e7,
                operating_cash_flow=1e8,
                rd_expense=2e7,
                rd_capitalized=1e6,
            )
        )
        s.commit()


def _seed_shareholder(eng) -> None:
    with Session(eng) as s:
        for i, t in enumerate(("增持", "业绩", "战略")):
            s.add(
                Announcement(
                    symbol="000002",
                    company_name="股东测",
                    ann_type=t,
                    title=f"公告{i}",
                    ann_date=date(2023, 1, 10 + i),
                )
            )
        s.commit()


def _seed_related_party(eng) -> None:
    with Session(eng) as s:
        s.add(
            RelatedPartyRaw(
                symbol="000003",
                company_name="关联测",
                report_year=2023,
                party_name="关联方A",
                relationship="子公司",
                transaction_type="采购",
                amount=1e6,
                pricing_method="市场价",
                raw_text="stub",
            )
        )
        s.commit()


def test_prompt_renders_financial_fraud():
    ctx = {
        "company_name": "测试公司",
        "symbol": "000001",
        "report_date": "2023-12-31",
        "cash_cur": 1e9,
        "cash_prev": 8e8,
        "cash_yoy": 0.25,
        "short_debt_cur": 5e8,
        "short_debt_prev": 4e8,
        "long_debt_cur": 1e9,
        "long_debt_prev": 9e8,
        "ar_cur": 3e8,
        "ar_prev": 2.5e8,
        "ar_yoy": 0.20,
        "inv_cur": 4e8,
        "inv_prev": 3.8e8,
        "inv_yoy": 0.05,
        "rev_cur": 2e9,
        "rev_prev": 1.8e9,
        "rev_yoy": 0.11,
        "cost_cur": 1.4e9,
        "cost_prev": 1.2e9,
        "gm_cur": 0.3,
        "gm_prev": 0.33,
        "np_cur": 2e8,
        "np_prev": 1.8e8,
        "ocf_cur": 1.5e8,
        "ocf_prev": 1.4e8,
        "rd_cur": 5e7,
        "rd_prev": 4e7,
        "rdcap_cur": 1e7,
        "rdcap_prev": 5e6,
        "peer_gm": 0.35,
        "peer_ar_turn": 4.5,
        "peer_inv_turn": 6.0,
    }
    instr, prompt = build_prompt("financial_fraud", ctx)
    assert "财务造假" in instr
    assert "测试公司" in prompt
    assert "存贷双高" in prompt


def test_prompt_renders_shareholder_integrity():
    ctx = {
        "company_name": "X",
        "symbol": "000002",
        "window_start": "2022-01-01",
        "window_end": "2024-12-31",
        "commitments_block": "- 增持承诺",
        "actual_holdings_changes": "...",
        "actual_vs_promised_perf": "...",
        "pledge_changes": "...",
        "strategy_progress": "...",
    }
    instr, prompt = build_prompt("shareholder_integrity", ctx)
    assert "言行不一" in instr
    assert "增持承诺失信" in prompt


def test_prompt_renders_related_party():
    ctx = {
        "company_name": "Y",
        "symbol": "000003",
        "report_period": "2023-12-31",
        "equity_block": "(...)",
        "rp_table": "| ... |",
        "anomaly_signals": "(...)",
    }
    instr, prompt = build_prompt("related_party", ctx)
    assert "关联交易" in instr
    assert "明股实债" in prompt


def test_parse_teacher_output_ok_and_fence():
    parsed, status = parse_teacher_output('{"risk_score": 0.9, "decision": "reject", "summary": "x"}')
    assert status == "ok"
    assert parsed["risk_score"] == 0.9

    raw = '```json\n{"risk_score": 0.1, "decision": "pass"}\n```'
    parsed, status = parse_teacher_output(raw)
    assert status == "ok"
    assert parsed["decision"] == "pass"


def test_parse_teacher_output_fail():
    parsed, status = parse_teacher_output("not json")
    assert parsed is None
    assert status == "json_error"


def test_mock_teacher_financial(cg_sqlite, monkeypatch):
    monkeypatch.setenv("CRYO_GUARD_DISTILL_MOCK", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _seed_financial(cg_sqlite[1])
    n = distill_run("financial_fraud", 1500, limit=1, dry_run=False)
    assert n == 1
    with Session(cg_sqlite[1]) as s:
        row = s.scalar(select(TeacherDistill).where(TeacherDistill.engine_name == "financial_fraud"))
        assert row is not None
        assert row.parse_status == "ok"
        assert json.loads(row.output)["decision"] == "pass"


def test_shareholder_and_related_mock_pipeline(cg_sqlite, monkeypatch):
    monkeypatch.setenv("CRYO_GUARD_DISTILL_MOCK", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _seed_shareholder(cg_sqlite[1])
    _seed_related_party(cg_sqlite[1])
    assert distill_run("shareholder_integrity", 1000, limit=1, dry_run=False) == 1
    assert distill_run("related_party", 1000, limit=1, dry_run=False) == 1


def test_export_split_and_holdout_guard_array(cg_sqlite, monkeypatch, tmp_path):
    monkeypatch.setenv("CRYO_GUARD_DISTILL_MOCK", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _seed_financial(cg_sqlite[1])
    distill_run("financial_fraud", 1500, limit=1, dry_run=False)
    assert auto_accept_if_safe("financial_fraud") >= 1
    # export 排除 cryo_mock_teacher；pytest 内将 model 标为真实 Teacher 以验 export 路径
    with Session(cg_sqlite[1]) as s:
        row = s.scalar(select(TeacherDistill).where(TeacherDistill.engine_name == "financial_fraud"))
        assert row is not None
        row.teacher_model = "pytest-claude-sonnet"
        s.commit()

    lf = tmp_path / "lf"
    monkeypatch.setenv("CRYO_LLAMA_FACTORY_OUT", str(lf))
    stats = export_engine_to_llama_factory("financial_fraud", out_dir=lf)
    assert stats["total"] == 1
    merged = json.loads((lf / "financial_fraud.json").read_text())
    assert len(merged) == 1
    train = json.loads((lf / "financial_fraud_train.json").read_text())
    val = json.loads((lf / "financial_fraud_val.json").read_text())
    test = json.loads((lf / "financial_fraud_test.json").read_text())
    assert len(train) + len(val) + len(test) == 1

    hold = tmp_path / "holdout"
    hold.mkdir()
    case = {"symbol": "600000", "case_id": "H001"}
    hp = hold / "H001.json"
    hp.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    digest = hashlib.sha256(hp.read_bytes()).hexdigest()
    (hold / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "cases": [{"case_id": "H001", "filename": "H001.json", "sha256": digest}]}
        ),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["CRYO_HOLDOUT_DIR"] = str(hold)
    r = subprocess.run(
        [
            sys.executable,
            str(_REPO / "training/scripts/holdout_guard.py"),
            "--check-training-data",
            str(lf / "financial_fraud.json"),
        ],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    bad = json.loads((lf / "financial_fraud.json").read_text())
    bad.append(
        {
            "instruction": "x",
            "input": "y",
            "output": "{}",
            "metadata": {"symbol": "600000"},
        }
    )
    (lf / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    r2 = subprocess.run(
        [
            sys.executable,
            str(_REPO / "training/scripts/holdout_guard.py"),
            "--check-training-data",
            str(lf / "bad.json"),
        ],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 1


def test_holdout_guard_jsonl_still_works(tmp_path):
    """回归：JSONL 逐行。"""
    h = tmp_path / "holdout"
    h.mkdir()
    case = {"symbol": "600000", "case_id": "H001"}
    hpath = h / "H001.json"
    hpath.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
    digest = hashlib.sha256(hpath.read_bytes()).hexdigest()
    (h / "manifest.json").write_text(
        json.dumps({"version": 1, "cases": [{"case_id": "H001", "filename": "H001.json", "sha256": digest}]}),
        encoding="utf-8",
    )
    bad = tmp_path / "train.jsonl"
    bad.write_text(json.dumps({"symbol": "600000"}) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["CRYO_HOLDOUT_DIR"] = str(h)
    r = subprocess.run(
        [
            sys.executable,
            str(_REPO / "training/scripts/holdout_guard.py"),
            "--check-training-data",
            str(bad),
        ],
        cwd=str(_REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1


def test_run_cryo_phase_b_help():
    r = subprocess.run(
        [sys.executable, str(_REPO / "training/scripts/run_cryo_phase_b.py"), "--help"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "cryo_guard" in r.stdout or "阶段" in r.stdout
