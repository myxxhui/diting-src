"""维度一 step_02 数据流水线与 Holdout（mock/Schema/脚本）。 [Ref: step_02]"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from apps.cryo_guard.db import models  # noqa: F401
from apps.cryo_guard.db.models import FinancialReport, RelatedPartyRaw
from apps.cryo_guard.db.session import Base
from apps.cryo_guard.holdout.schema import HoldoutCaseFile

_REPO = Path(__file__).resolve().parents[2]


def _crawl_financial_reports_mod():
    p = _REPO / "training/data/scripts/crawl_financial_reports.py"
    spec = importlib.util.spec_from_file_location("crawl_financial_reports_step02", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _valid_case(**overrides) -> dict:
    base = {
        "case_id": "H001",
        "symbol": "600519",
        "company_name": "样例",
        "fraud_type": "测谎",
        "target_engine": "financial_fraud",
        "fraud_start_year": 2020,
        "exposure_date": "2024-06-15",
        "ground_truth_decision": "reject",
        "ground_truth_score": 0.88,
        "evidence": ["审计意见异常"],
    }
    base.update(overrides)
    return base


def test_holdout_reject_requires_high_score():
    with pytest.raises(Exception):
        HoldoutCaseFile.model_validate(_valid_case(ground_truth_score=0.5))


def test_holdout_pass_requires_low_score():
    with pytest.raises(Exception):
        HoldoutCaseFile.model_validate(
            _valid_case(ground_truth_decision="pass", ground_truth_score=0.9)
        )


def test_holdout_valid_roundtrip():
    o = HoldoutCaseFile.model_validate(_valid_case())
    assert o.case_id == "H001"


def test_holdout_evidence_nonempty():
    bad = _valid_case()
    bad["evidence"] = []
    with pytest.raises(Exception):
        HoldoutCaseFile.model_validate(bad)


def test_financial_report_persists_on_memory_sqlite():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    s.add(
        FinancialReport(
            symbol="600519",
            company_name="茅台",
            report_date=date(2023, 12, 31),
            report_type="annual",
            raw_balance_sheet={},
            raw_income_statement={},
            raw_cash_flow={},
        )
    )
    s.commit()
    n = s.scalar(select(func.count()).select_from(FinancialReport))
    assert n == 1


def test_related_party_raw_orm():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    s.add(
        RelatedPartyRaw(
            symbol="600519",
            company_name="茅台",
            report_year=2023,
            party_name="关联方A",
            raw_text="采购 100 万元",
        )
    )
    s.commit()
    n = s.scalar(select(func.count()).select_from(RelatedPartyRaw))
    assert n == 1


def test_holdout_generate_validate_cli(tmp_path, monkeypatch):
    h = tmp_path / "holdout"
    monkeypatch.setenv("CRYO_HOLDOUT_DIR", str(h))
    env = dict(os.environ)
    env["CRYO_HOLDOUT_DIR"] = str(h)
    for script in (
        "training/scripts/generate_holdout_fixtures.py",
        "training/scripts/build_holdout_manifest.py",
        "training/scripts/validate_holdout.py",
    ):
        r = subprocess.run(
            [sys.executable, str(_REPO / script)],
            cwd=str(_REPO),
            env=env,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr + r.stdout


def test_holdout_guard_flags_training_overlap(tmp_path):
    h = tmp_path / "holdout"
    h.mkdir()
    raw = _valid_case(case_id="H001", symbol="600000")
    text = json.dumps(raw, ensure_ascii=False)
    hpath = h / "H001.json"
    hpath.write_text(text + "\n")
    digest = hashlib.sha256(hpath.read_bytes()).hexdigest()
    (h / "manifest.json").write_text(
        json.dumps({"version": 1, "cases": [{"case_id": "H001", "filename": "H001.json", "sha256": digest}]})
        + "\n"
    )
    bad = tmp_path / "train.jsonl"
    bad.write_text(json.dumps({"symbol": "600000"}) + "\n")
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


def test_parse_symbol_list_file_allows_multi_space(tmp_path):
    m = _crawl_financial_reports_mod()
    f = tmp_path / "sym.txt"
    f.write_text("601088  中国神华\n601138 \t 工业富联\n", encoding="utf-8")
    assert m.parse_symbol_list_file(f) == [
        ("601088", "中国神华"),
        ("601138", "工业富联"),
    ]


def test_parse_symbol_list_file(tmp_path):
    m = _crawl_financial_reports_mod()
    f = tmp_path / "sym.txt"
    f.write_text("# 头\n600519\t贵州茅台\n000001\n600000,浦发银行\n", encoding="utf-8")
    assert m.parse_symbol_list_file(f) == [
        ("600519", "贵州茅台"),
        ("000001", "000001"),
        ("600000", "浦发银行"),
    ]


def test_env_crawl_years(monkeypatch):
    m = _crawl_financial_reports_mod()
    monkeypatch.delenv("CRYO_YEARS", raising=False)
    monkeypatch.delenv("CRYO_YEAR_START", raising=False)
    monkeypatch.delenv("CRYO_YEAR_END", raising=False)
    assert m.env_crawl_years() == [2020, 2021, 2022, 2023, 2024]
    monkeypatch.setenv("CRYO_YEARS", "2024,2022,2022")
    assert m.env_crawl_years() == [2022, 2024]
    monkeypatch.delenv("CRYO_YEARS", raising=False)
    monkeypatch.setenv("CRYO_YEAR_START", "2021")
    monkeypatch.setenv("CRYO_YEAR_END", "2020")
    assert m.env_crawl_years() == [2020, 2021]


def test_env_crawl_years_rejects_incomplete_range(monkeypatch):
    m = _crawl_financial_reports_mod()
    monkeypatch.delenv("CRYO_YEARS", raising=False)
    monkeypatch.setenv("CRYO_YEAR_START", "2020")
    monkeypatch.delenv("CRYO_YEAR_END", raising=False)
    with pytest.raises(ValueError, match="CRYO_YEAR_START"):
        m.env_crawl_years()


def test_bootstrap_yaml_sets_env(tmp_path, monkeypatch):
    yaml_path = tmp_path / "crawl.yaml"
    yaml_path.write_text(
        "symbol_list: symbols.txt\nyears: [2021]\nthrottle_sec: 0.1\n",
        encoding="utf-8",
    )
    (tmp_path / "symbols.txt").write_text("600519\t茅\n", encoding="utf-8")
    monkeypatch.delenv("CRYO_SYMBOL_LIST", raising=False)
    monkeypatch.delenv("CRYO_YEARS", raising=False)
    monkeypatch.delenv("CRYO_THROTTLE_SEC", raising=False)
    monkeypatch.setenv("CRYO_CRAWL_CONFIG", str(yaml_path))
    from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

    bootstrap_crawl_env(tmp_path)
    sym_path = Path(os.environ["CRYO_SYMBOL_LIST"])
    assert sym_path.name == "symbols.txt"
    assert "600519" in sym_path.read_text(encoding="utf-8")
    assert os.environ.get("CRYO_YEARS") == "2021"
    assert os.environ.get("CRYO_THROTTLE_SEC") == "0.1"


def test_eastmoney_symbol_normalization():
    m = _crawl_financial_reports_mod()
    assert m._eastmoney_symbol("600519") == "sh600519"
    assert m._eastmoney_symbol("000001") == "sz000001"
    assert m._eastmoney_symbol("sh600519") == "sh600519"


def _crawl_announcements_mod():
    p = _REPO / "training/data/scripts/crawl_announcements.py"
    spec = importlib.util.spec_from_file_location("crawl_announcements_step02", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_announcement_symbol_to_stock_list_param():
    m = _crawl_announcements_mod()
    assert m._symbol_to_stock_list_param("600519") == "600519"
    assert m._symbol_to_stock_list_param("sh600519") == "600519"
    assert m._symbol_to_stock_list_param("sz000001") == "000001"


def test_classify_ann_type_eastmoney():
    m = _crawl_announcements_mod()
    assert m._classify_ann_type("关于控股股东增持股份的公告", "持股变动") == "增持"
    assert m._classify_ann_type("关于减持计划届满的公告", "持股变动") == "减持"
    assert m._classify_ann_type("2024年三季报", "定期报告") == "业绩"
    assert m._classify_ann_type("股权质押补充公告", "股权质押") == "质押"
    assert m._classify_ann_type("重大资产重组预案", "并购重组") == "战略"
    assert m._classify_ann_type("董事会会议决议", "公司治理") is None


def test_titles_match_cninfo_enrich():
    m = _crawl_announcements_mod()
    assert m._titles_match("贵州茅台:2025年年度报告", "贵州茅台2025年年度报告")
    assert m._titles_match("关于回购的公告", "XX公司关于回购的公告")
    assert not m._titles_match("完全不同的标题A", "完全不同的标题B")


def test_env_crawl_interval_dates(monkeypatch):
    m = _crawl_financial_reports_mod()
    monkeypatch.delenv("CRYO_YEARS", raising=False)
    monkeypatch.setenv("CRYO_YEAR_START", "2022")
    monkeypatch.setenv("CRYO_YEAR_END", "2024")
    b, e = m.env_crawl_interval_dates()
    assert b == date(2022, 1, 1)
    assert e == date(2024, 12, 31)


def test_env_crawl_interval_dates_sparse_years(monkeypatch):
    m = _crawl_financial_reports_mod()
    monkeypatch.delenv("CRYO_YEAR_START", raising=False)
    monkeypatch.delenv("CRYO_YEAR_END", raising=False)
    monkeypatch.setenv("CRYO_YEARS", "2020,2023")
    b, e = m.env_crawl_interval_dates()
    assert b == date(2020, 1, 1)
    assert e == date(2023, 12, 31)


def test_build_record_maps_eastmoney_english_keys():
    m = _crawl_financial_reports_mod()
    fr = m._build_record(
        "600519",
        "贵州茅台",
        2023,
        "annual",
        {"MONETARYFUNDS": 1e10, "TOTAL_ASSETS": 2e11, "TOTAL_LIABILITIES": 3e10},
        {"TOTAL_OPERATE_INCOME": 1e12, "TOTAL_OPERATE_COST": 4e11, "NETPROFIT": 1e11, "OPERATE_PROFIT": 1.1e11},
        {"NETCASH_OPERATE": 5e10, "NETCASH_INVEST": -1e9, "NETCASH_FINANCE": -2e10},
    )
    assert fr.revenue == 1e12
    assert fr.cash_and_equivalents == 1e10
    assert fr.net_profit == 1e11
    assert fr.operating_cash_flow == 5e10


def test_get_all_a_respects_symbol_list_file(tmp_path, monkeypatch):
    m = _crawl_financial_reports_mod()
    monkeypatch.delenv("CRYO_MOCK", raising=False)
    f = tmp_path / "syms.txt"
    f.write_text("000001\t平安\n", encoding="utf-8")
    monkeypatch.setenv("CRYO_SYMBOL_LIST", str(f))
    assert m.get_all_a_stock_symbols() == [("000001", "平安")]
