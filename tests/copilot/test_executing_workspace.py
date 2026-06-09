"""执行中工作区（28_）单测。

[Ref: 28_ §9]
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import ExecutingCollectSymbol, UserPosition
from apps.copilot.main import app
from apps.copilot.modules.executing.profile import PROBE_KEYS
from apps.copilot.modules.executing.t1_build import build_telemetry


@pytest.fixture
async def db_ready():
    await init_db()
    yield


@pytest.mark.asyncio
async def test_probe_keys_count():
    assert PROBE_KEYS == (
        "qmt_atr_trailing",
        "volume_price_div",
        "smart_money_flow",
        "level2_super_order",
        "margin_short_skew",
        "turnover_acceleration",
        "block_trade_discount",
        "retail_concentration",
        "insider_sell_actual",
        "etf_redemption_impact",
        "tech_beta_correlation",
    )


def test_probe_registry_covers_all_keys():
    from apps.copilot.modules.executing.probe_registry import (
        OPTIONAL_SILENT_PROBE_KEYS,
        PROBE_REGISTRY,
        REGISTERED_PROBE_KEYS,
    )

    assert REGISTERED_PROBE_KEYS == PROBE_KEYS
    assert set(PROBE_REGISTRY) == set(PROBE_KEYS)
    assert OPTIONAL_SILENT_PROBE_KEYS == frozenset(
        {"block_trade_discount", "etf_redemption_impact"}
    )
    for key in PROBE_KEYS:
        assert PROBE_REGISTRY[key].spec.key == key


def test_render_volume_price_div_card():
    from apps.copilot.modules.executing.executing_render import render_volume_price_div_card
    from apps.copilot.modules.executing.indicator_nodes import build_volume_price_div_node

    node = build_volume_price_div_node(
        {
            "value": 0.66,
            "source": "tencent_mkline_m15_qfq (200 bars)",
            "calculation_logic": "高位区阴线总成交量 / 高位区阳线总成交量",
            "fact_statement": "近期高位区间内，15分钟级阴线成交总量为阳线成交总量的 0.66 倍。",
            "high_zone_down_vol": 2578456.07,
            "high_zone_up_vol": 3903306.96,
            "high_zone_threshold_price": 78.84,
            "period_max": 84.68,
            "period_min": 65.2,
            "global_vol_ratio": 0.9654,
            "last_bar_datetime": "2026-06-08 15:00:00",
        }
    )
    html = render_volume_price_div_card(node)
    assert "15分钟级高位量价背离" in html
    assert "0.66" in html
    assert "高位阴线量" in html
    assert "volume_price_div" in html


def test_probe_labels_chinese_short():
    from apps.copilot.modules.executing.probe_labels import PROBE_LABELS, probe_label

    assert probe_label("qmt_atr_trailing") == "ATR止盈"
    assert len(PROBE_LABELS) == 25


def test_layer_b_prerequisite_banner_no_mock():
    from apps.copilot.modules.executing.executing_render import render_layer_b_prerequisite_banner

    html = render_layer_b_prerequisite_banner()
    assert "建仓时间" in html
    assert "不展示" in html


def test_render_qmt_atr_trailing_shows_audit_fields():
    from apps.copilot.modules.executing.executing_render import (
        render_hot_data_timeline,
        render_qmt_atr_trailing_card,
    )
    from apps.copilot.modules.executing.indicator_nodes import build_qmt_atr_trailing_node

    node = build_qmt_atr_trailing_node(
        {
            "value": 3.06,
            "source": "PG test",
            "atr20": 4.73,
            "peak_price": 84.95,
            "current": 70.48,
            "as_of": "2026-06-08",
        }
    )
    html = render_qmt_atr_trailing_card(node)
    assert "动态ATR追踪止盈" in html
    assert "3.06" in html
    assert "ATR₂₀" in html
    assert "峰值价" in html
    assert "击穿" not in html
    assert "K线交易日" in html
    assert "raw_metrics" not in html
    timeline = render_hot_data_timeline(node, quote_job_at="2026-06-08T07:55:04.270822")
    assert "热数据时间线" in timeline
    assert "盘后 PG 日K" in timeline
    assert "2026-06-08 15:55:04" in timeline
    assert "北京时间" in timeline

    intraday = build_qmt_atr_trailing_node(
        {
            "value": 3.00,
            "intraday": True,
            "atr20": 5.00,
            "peak_price": 85.00,
            "current": 70.00,
            "last_tick_time": "2026-06-08 14:00:00",
        }
    )
    intraday_html = render_qmt_atr_trailing_card(intraday)
    assert "快照时间" in intraday_html
    assert "2026-06-08 14:00:00" in intraday_html
    assert "盘中快照现价" in intraday_html
    assert "热数据快照" in intraday_html
    hot_tl = render_hot_data_timeline(intraday)
    assert "盘中热数据" in hot_tl
    assert "2026-06-08 14:00:00" in hot_tl


@pytest.mark.asyncio
async def test_symbol_base_sync_and_settings(db_ready):
    from apps.copilot.modules.executing.symbol_base import load_symbol_base, save_symbol_base_data
    from apps.copilot.modules.executing.universe import load_executing_collect_symbols
    from apps.copilot.modules.executing.workspace_settings import (
        get_workspace_settings,
        save_workspace_settings,
    )

    async with AsyncSessionLocal() as session:
        await save_workspace_settings(session, available_cash=500000.0)
        await save_symbol_base_data(
            session,
            {
                "symbol": "601138",
                "name": "工业富联",
                "quantity": 1500,
                "cost_price": 56.82,
                "position_pct": 29.7,
                "opened_at": "2026-04-10",
                "source": "ui",
            },
        )
        await session.commit()
        base = await load_symbol_base(session, "601138")
        settings = await get_workspace_settings(session)
        syms = await load_executing_collect_symbols(session)
    assert base["position_pct"] == 29.7
    assert base["opened_at"] == "2026-04-10"
    assert settings["available_cash"] == 500000.0
    assert "601138" in syms


@pytest.mark.asyncio
async def test_position_crud(db_ready):
    async with AsyncSessionLocal() as session:
        from apps.copilot.modules.executing.positions import (
            delete_position,
            upsert_position,
        )

        await upsert_position(
            session,
            {
                "symbol": "601138",
                "name": "工业富联",
                "quantity": 100,
                "cost_price": 50.0,
                "position_pct": 10.0,
                "opened_at": "2026-04-10",
                "source": "ui",
            },
        )
        await session.commit()
        row = await session.get(UserPosition, "601138")
        assert row is not None
        assert row.quantity == 100
        await delete_position(session, "601138")
        await session.commit()


@pytest.mark.asyncio
async def test_t1_build_structure():
    raw = {
        "qmt_atr_trailing": {
            "ok": True,
            "payload": {
                "value": 1.2,
                "atr_multiple": 1.2,
                "peak_price": 80.0,
                "current": 74.0,
                "calculation_logic": "(80-74)/5=1.2",
                "fact_statement": "测试",
            },
            "source": "test",
        }
    }
    tel = build_telemetry(
        "601138",
        as_of=__import__("datetime").date.today(),
        raw_by_key=raw,
        profit_context={
            "has_position": True,
            "name": "工业富联",
            "cost_price": 53.66,
            "mark_price": 74.06,
            "unrealized_pnl_pct": 38.01,
            "opened_at": "2026-04-10",
            "position_pct": 20.0,
            "quantity": 20000,
        },
        execution_id="batch_task_test_001",
    )
    assert "batch_meta" in tel
    assert "portfolio_signals" in tel
    sig = tel["portfolio_signals"]["601138.SH"]
    assert sig["stock_name"] == "工业富联"
    pos = sig["position_context"]
    assert pos["holding_volume"] == 20000
    assert pos["unrealized_profit_pct"] == "38.01%"
    assert pos["position_pct"] == "20%"
    assert pos["current_price"] == 74.06
    assert pos["cost_basis"] == 53.66
    assert tel["batch_meta"]["money_unit"] == "人民币"
    assert "qmt_atr_trailing" in sig["indicators"]
    assert "volume_price_div" not in sig["indicators"]
    assert any("volume_price_div" in d for d in (sig.get("degraded_probes") or []))


@pytest.mark.asyncio
async def test_daily_bars_pg_roundtrip(db_ready):
    from datetime import date

    from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow
    from apps.copilot.modules.executing.storage import load_daily_bars, replace_daily_bars
    from apps.copilot.modules.executing.t1_operators.qmt_atr_trailing import (
        AtrTrailingError,
        process_qmt_atr_trailing_from_rows,
    )

    rows = [
        DailyBarRow(
            trade_date=date(2026, 1, 1 + i),
            open=10.0 + i * 0.1,
            high=11.0 + i * 0.1,
            low=9.5 + i * 0.1,
            close=10.5 + i * 0.1,
            volume=1_000_000.0 + i,
        )
        for i in range(25)
    ]
    async with AsyncSessionLocal() as session:
        n = await replace_daily_bars(session, "601138", rows, source="tencent_fqkline")
        await session.commit()
        loaded = await load_daily_bars(session, "601138", limit=250)
    assert n == 25
    assert len(loaded) == 25
    entry = date(2026, 1, 5)
    payload = process_qmt_atr_trailing_from_rows(loaded, entry, source="test")
    assert payload["indicator_key"] == "qmt_atr_trailing"
    assert payload["value"] == round(payload["atr_multiple"], 2)
    assert "calculation_logic" in payload
    assert "fact_statement" in payload
    assert payload["bars_count"] == 25
    with pytest.raises(AtrTrailingError):
        process_qmt_atr_trailing_from_rows(loaded, date(2020, 1, 1), source="test")


@pytest.mark.asyncio
async def test_intraday_draft_merge_overwrite():
    from datetime import date

    from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow
    from apps.copilot.modules.executing.collectors.intraday_draft import (
        merge_pg_rows_with_draft,
    )

    hist = [
        DailyBarRow(
            trade_date=date(2026, 6, 6),
            open=70.0,
            high=72.0,
            low=69.0,
            close=71.0,
            volume=1e6,
        )
    ]
    draft = DailyBarRow(
        trade_date=date(2026, 6, 8),
        open=74.0,
        high=76.0,
        low=73.5,
        close=75.5,
        volume=2e6,
    )
    merged = merge_pg_rows_with_draft(hist, draft)
    assert len(merged) == 2
    assert merged[-1].high == 76.0

    draft2 = DailyBarRow(
        trade_date=date(2026, 6, 8),
        open=74.0,
        high=77.0,
        low=73.5,
        close=75.0,
        volume=2.5e6,
    )
    merged2 = merge_pg_rows_with_draft(merged, draft2)
    assert len(merged2) == 2
    assert merged2[-1].high == 77.0


@pytest.mark.asyncio
async def test_daily_bars_upsert_incremental(db_ready):
    from datetime import date

    from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow
    from apps.copilot.modules.executing.storage import load_daily_bars, upsert_daily_bars

    base = [
        DailyBarRow(
            trade_date=date(2026, 1, 1 + i),
            open=10.0,
            high=11.0,
            low=9.0,
            close=10.5,
            volume=1000.0,
        )
        for i in range(5)
    ]
    async with AsyncSessionLocal() as session:
        await upsert_daily_bars(session, "601138", base, source="tencent_fqkline")
        await session.commit()
        updated = [
            DailyBarRow(
                trade_date=date(2026, 1, 5),
                open=10.0,
                high=12.0,
                low=9.0,
                close=11.0,
                volume=2000.0,
            )
        ]
        await upsert_daily_bars(session, "601138", updated, source="tencent_fqkline")
        await session.commit()
        loaded = await load_daily_bars(session, "601138", limit=10)
    assert len(loaded) == 5
    assert loaded[-1].high == 12.0


@pytest.mark.asyncio
async def test_no_auto_execute_rg():
    import shutil
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if not shutil.which("rg"):
        pytest.skip("rg 未安装")
    r = subprocess.run(
        [
            "rg",
            "-i",
            "auto_trade|order_id|webhook_target|立即下单|一键下单",
            "apps/copilot/modules/executing/",
            "apps/copilot/routers/executing_routes.py",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 or not (r.stdout or "").strip()


@pytest.mark.asyncio
async def test_sync_status_api(db_ready):
    async with AsyncSessionLocal() as session:
        from apps.copilot.modules.executing.universe import upsert_executing_collect

        await upsert_executing_collect(session, "601138")
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/executing/sync-status")
        assert r.status_code == 200
        assert "601138" in r.json().get("collect_symbols", [])


@pytest.mark.asyncio
async def test_load_cached_stock_signal(db_ready):
    from apps.copilot.modules.executing.storage import upsert_t1_snapshot
    from apps.copilot.modules.executing.t1_assembler import load_cached_stock_signal
    from apps.copilot.modules.executing.universe import upsert_executing_collect

    async with AsyncSessionLocal() as session:
        await upsert_executing_collect(session, "601138")
        await upsert_t1_snapshot(
            session,
            "601138",
            "qmt_atr_trailing",
            {"value": 1.2, "fact_statement": "test", "source": "unit"},
        )
        await session.commit()
        async with AsyncSessionLocal() as s2:
            sig = await load_cached_stock_signal(s2, "601138", redis_client=None)
    assert "qmt_atr_trailing" in (sig.get("indicators") or {})
    assert sig.get("cache_only") is True


@pytest.mark.asyncio
async def test_executing_detail_uses_snapshot_cache(db_ready):
    from apps.copilot.modules.executing.storage import upsert_t1_snapshot
    from apps.copilot.modules.executing.universe import upsert_executing_collect

    from apps.copilot.modules.executing.positions import upsert_position

    async with AsyncSessionLocal() as session:
        await upsert_executing_collect(session, "601138")
        await upsert_position(
            session,
            {
                "symbol": "601138",
                "name": "工业富联",
                "quantity": 1500,
                "cost_price": 56.82,
                "position_pct": 29.7,
                "opened_at": "2024-04-14",
            },
        )
        await upsert_t1_snapshot(
            session,
            "601138",
            "smart_money_flow",
            {"value": 0.5, "fact_statement": "主力净流入", "source": "unit"},
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/executing/601138/detail")
    assert r.status_code == 200
    assert "executing-detail-601138" in r.text
    assert "PG 快照缓存" in r.text
    assert "smart_money_flow" in r.text or "主力净流入" in r.text
