"""27_ 架构优化 P0：collect symbols SoT · fact_matrix · 旁路落库。

[Ref: 27_行情雷达全链路架构设计优化]
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.copilot.db.database import Base
from apps.copilot.modules.radar.t0.symbol_list import (
    load_generic_t0_collect_symbols,
    load_t0_collect_symbols,
    row_to_dict,
    upsert_collect_symbol,
)
from apps.copilot.modules.executing.universe import upsert_executing_collect
from apps.copilot.modules.radar.t1.fact_matrix_builder import enrich_t1_payload
from apps.copilot.modules.radar.t1.operators.micro_ops import (
    op_t08_price_action,
    op_t11_dragon_tiger,
)
from apps.copilot.modules.radar.t1.radar_matrix_assembler import assemble_fact_matrix


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_load_generic_t0_collect_symbols_union(db_session: AsyncSession):
    await upsert_executing_collect(db_session, "300502", profile="601138", enabled=True)
    await upsert_collect_symbol(db_session, symbol="601138", name="工业富联")
    await db_session.commit()

    syms = await load_generic_t0_collect_symbols(db_session)
    assert syms == ["300502", "601138"]


@pytest.mark.asyncio
async def test_upsert_and_load_collect_symbols(db_session: AsyncSession):
    await upsert_collect_symbol(db_session, symbol="601138", name="工业富联")
    await upsert_collect_symbol(db_session, symbol="300308", name="中际旭创", enabled=False)
    await db_session.commit()

    enabled = await load_t0_collect_symbols(db_session, enabled_only=True)
    assert enabled == ["601138"]

    all_syms = await load_t0_collect_symbols(db_session, enabled_only=False)
    assert sorted(all_syms) == ["300308", "601138"]


@pytest.mark.asyncio
async def test_row_to_dict(db_session: AsyncSession):
    row = await upsert_collect_symbol(db_session, symbol="002837", name="英维克")
    await db_session.commit()
    await db_session.refresh(row)
    d = row_to_dict(row)
    assert d["symbol"] == "002837"
    assert d["name"] == "英维克"
    assert d["enabled"] is True


def test_enrich_t1_payload_fact_matrix():
    t0 = {
        "symbol": "601138",
        "quote": {"status": "ok", "pct_chg_20d": 5.0, "volume_ratio_5d": 1.2},
        "profile": {"status": "ok", "industry": "电子", "total_mv_yi": 4000},
        "financials": {"status": "ok", "roe": 12.0, "gross_margin": 7.5},
        "valuation": {"status": "ok", "pe_ttm": 22, "pe_percentile": 45},
    }
    base = {"matrix": {"行情": {"近20日": "5%"}}, "unavailable": []}
    out = enrich_t1_payload(t0, base)
    assert "fact_matrix" in out
    assert out["fact_matrix"]["microstructure"]["price_action"]["tag"] == "量价可用"
    assert isinstance(out["unavailable_data"], list)


def test_p1_micro_operators_bars250_and_dragon_tiger():
    t0 = {
        "symbol": "601138",
        "quote": {"status": "ok", "pct_chg_20d": 1.0},
    }
    micro = {
        "bars_250d": {
            "status": "ok",
            "bars_count": 251,
            "summary": {
                "above_ma20": True,
                "ma20": 10.0,
                "limit_up_count_20d": 3,
                "side_tag": "多头排列",
            },
        },
        "northbound": {"status": "ok", "net_buy_5d_yi": 3.5, "net_buy_30d_yi": 8.0},
        "margin": {"status": "ok", "roc_5d": 0.08, "latest_date": "20250603"},
        "dragon_tiger": {
            "status": "ok",
            "appearance_count": 2,
            "institution_net": 1_000_000.0,
            "hot_money_net": 500_000.0,
        },
    }
    t0["micro"] = micro
    fm, unavail = assemble_fact_matrix(t0, {}, [])
    ms = fm["microstructure"]
    assert ms["price_action"]["tag"] == "右侧极度活跃"
    assert ms["northbound_flow"]["tag"] == "外资持续加仓"
    assert ms["margin_leverage"]["tag"] == "杠杆做多高涨"
    assert ms["dragon_tiger"]["tag"] == "机构游资共振"

    r8 = op_t08_price_action(t0, micro)
    assert r8.node is not None
    assert r8.node["tag"] == "右侧极度活跃"

    dt = op_t11_dragon_tiger(t0, micro)
    assert dt.node is not None
    assert dt.node["value"] == 2


def test_fetch_bars_250d_length():
    from apps.state_watch.probes.datasource.quote_adapter import fetch_bars_250d

    bars = fetch_bars_250d("601138")
    if not bars:
        pytest.skip("行情源不可用，跳过 250 日 K 集成探针")
    assert len(bars) >= 200


@pytest.mark.asyncio
async def test_collect_once_empty_table(db_session: AsyncSession):
    from apps.copilot.modules.radar.t0.jobs.collect_once import collect_once

    out = await collect_once(db_session, symbols=None, job_id="test-empty")
    assert out == []
