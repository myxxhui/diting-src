"""维度二 step_02 数据 ingest（mock）。 [Ref: step_02]"""

from __future__ import annotations

import importlib
import sqlite3
from unittest.mock import patch

import pytest

def test_mock_financial_report_shape(monkeypatch):
    monkeypatch.setenv("DEEP_STRIKE_MOCK", "1")
    import apps.deep_strike.data.sources.akshare_source as ak

    importlib.reload(ak)
    rows = ak.fetch_financial_report("600519")
    assert rows and rows[0]["period"] == "2024Q3"


def test_mock_announcement_validates(monkeypatch):
    monkeypatch.setenv("DEEP_STRIKE_MOCK", "1")
    from apps.deep_strike.data import validator
    import apps.deep_strike.data.sources.akshare_source as ak

    importlib.reload(ak)
    rows = ak.fetch_announcements("600519")
    assert validator.validate_announcement(rows[0])


def test_normalizer_financial_report():
    from datetime import datetime

    from apps.deep_strike.data import normalizer

    m = normalizer.to_financial_report(
        "600519",
        {
            "report_type": "income",
            "period": "2024Q3",
            "period_end": datetime(2024, 9, 30),
            "revenue": 1.0,
            "cost": 0.5,
            "gross_profit": 0.5,
            "operating_expense": 0.1,
            "net_profit": 0.2,
            "raw": {},
        },
    )
    assert m.symbol == "600519"
    assert m.period == "2024Q3"


def test_validate_financial_indicator_missing_period():
    from apps.deep_strike.data import validator

    assert not validator.validate_financial_indicator({"period_end": None})


def test_cninfo_uses_httpx_client():
    from unittest.mock import MagicMock

    from apps.deep_strike.data.sources import cninfo_source

    class Resp:
        text = "<html>ok</html>"

        def raise_for_status(self) -> None:
            return None

    mock_client = MagicMock()
    mock_client.get.return_value = Resp()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_client
    mock_cm.__exit__.return_value = False

    with patch("apps.deep_strike.data.sources.cninfo_source.httpx.Client", return_value=mock_cm):
        t = cninfo_source.fetch_full_announcement_text("x", base_url="http://test")
    assert "html" in t


@pytest.mark.asyncio
async def test_ingest_mock_writes_sqlite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEP_STRIKE_MOCK", "1")
    import apps.deep_strike.config as cfg
    import apps.deep_strike.db.database as db

    importlib.reload(cfg)
    importlib.reload(db)
    import apps.deep_strike.data.ingest as ingest_mod

    importlib.reload(ingest_mod)
    stats = await ingest_mod.ingest_symbol("600519")
    assert stats["financial_reports"] >= 1
    assert stats["financial_indicators"] >= 1
    db_path = tmp_path / "data" / "deep_strike.db"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    n = conn.execute("select count(*) from financial_reports").fetchone()[0]
    assert n >= 1


@pytest.mark.asyncio
async def test_ingest_idempotent_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEP_STRIKE_MOCK", "1")
    import apps.deep_strike.config as cfg
    import apps.deep_strike.db.database as db

    importlib.reload(cfg)
    importlib.reload(db)
    import apps.deep_strike.data.ingest as ingest_mod

    importlib.reload(ingest_mod)
    await ingest_mod.ingest_symbol("600519")
    s2 = await ingest_mod.ingest_symbol("600519")
    assert s2["financial_reports"] == 0
