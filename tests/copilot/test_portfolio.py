"""持仓维护页 pytest。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
"""
import io

import pandas as pd
from fastapi.testclient import TestClient

from apps.copilot.main import app
from apps.copilot.services.excel_importer import ExcelImportError, parse_excel


def test_holdings_page_empty():
    with TestClient(app) as client:
        r = client.get("/holdings")
        assert r.status_code == 200
        assert "持仓管理" in r.text
        assert "0 只" in r.text or "还没有持仓" in r.text


def test_create_holding_and_list():
    with TestClient(app) as client:
        r = client.post(
            "/holdings",
            data={
                "symbol": "600519",
                "name": "贵州茅台",
                "shares": 100,
                "cost_price": 1800,
            },
        )
        assert r.status_code == 200
        assert "贵州茅台" in r.text

        r2 = client.get("/holdings")
        assert "贵州茅台" in r2.text
        assert "600519" in r2.text


def test_excel_import_missing_columns():
    bad_df = pd.DataFrame({"代码": ["600519"], "名称": ["贵州茅台"]})
    buf = io.BytesIO()
    bad_df.to_excel(buf, index=False)
    buf.seek(0)

    with TestClient(app) as client:
        r = client.post(
            "/holdings/import",
            files={
                "file": (
                    "bad.xlsx",
                    buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r.status_code == 400


def test_parse_excel_pad_symbol():
    df = pd.DataFrame(
        {
            "股票代码": [1, "600519"],
            "股票名称": ["平安银行", "贵州茅台"],
            "持仓数量": [100, 100],
            "成本价": [12.0, 1800.0],
        }
    )
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    rows = parse_excel(buf.getvalue())
    assert rows[0]["symbol"] == "000001"
    assert rows[1]["symbol"] == "600519"


def test_parse_excel_empty_raises():
    df = pd.DataFrame({"foo": []})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    try:
        parse_excel(buf.getvalue())
    except ExcelImportError as exc:
        assert "缺少必填列" in str(exc)
    else:
        raise AssertionError("应抛 ExcelImportError")
