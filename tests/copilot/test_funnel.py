"""标的级漏斗（四区联动）不变量 pytest。

[Ref: 25_四区漏斗_三段流水线_架构脊柱_设计.md · 标的级漏斗重构]

锁定核心不变量：
- 一个标的 = 一条 funnel 记录（symbol 全局唯一，重复导入/晋级不翻倍）
- funnel_stage 前向单向推进
- 四区视图按 funnel_stage 过滤，标的只出现在其当前所属区
"""
from __future__ import annotations

import pytest

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.modules.planning.funnel import (
    FUNNEL_STAGES,
    get_funnel_symbol,
    list_funnel_symbols,
    set_stage,
    touch_last_analyzed,
    upsert_funnel_symbol,
)


@pytest.fixture(autouse=True)
def _fake_redis(monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        for mod in (
            "apps.copilot.routers.planning_routes",
            "apps.copilot.services.redis_wait",
            "apps.copilot.modules.planning.service",
        ):
            monkeypatch.setattr(f"{mod}.wait_for_sync_redis", _fake_wait)
        yield fake
    except ImportError:
        yield None


def test_funnel_stages_order():
    assert FUNNEL_STAGES == [
        "radar_intake",
        "roadmap",
        "planning",
        "executing",
        "archived",
    ]


@pytest.mark.asyncio
async def test_symbol_global_unique_no_duplicate():
    """重复 upsert 同一 symbol 不新建第二条（标的全局唯一）。"""
    await init_db()
    async with AsyncSessionLocal() as session:
        await upsert_funnel_symbol(session, "601138", "工业富联", stage="planning")
        await upsert_funnel_symbol(session, "601138", "工业富联", stage="planning")
        await upsert_funnel_symbol(session, "0601138", "工业富联", stage="roadmap")
        await session.commit()
        rows = [r for r in await list_funnel_symbols(session) if r.symbol == "601138"]
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_stage_forward_only():
    """stage 只前进不回退（除非 allow_backward）。"""
    await init_db()
    async with AsyncSessionLocal() as session:
        await upsert_funnel_symbol(session, "300866", "安克创新", stage="executing")
        # 尝试用更低 stage upsert → 不应回退
        await upsert_funnel_symbol(session, "300866", "安克创新", stage="planning")
        await session.commit()
        row = await get_funnel_symbol(session, "300866")
        assert row.funnel_stage == "executing"
        # allow_backward 显式回退（归档回流路线图场景）
        await set_stage(session, "300866", "roadmap", allow_backward=True)
        await session.commit()
        row = await get_funnel_symbol(session, "300866")
        assert row.funnel_stage == "roadmap"


@pytest.mark.asyncio
async def test_view_filter_no_overlap():
    """同一标的只出现在其当前 stage 对应的区，不跨区重复。"""
    from apps.copilot.modules.planning.service import list_workspace_symbols

    await init_db()
    async with AsyncSessionLocal() as session:
        await upsert_funnel_symbol(session, "601899", "紫金矿业", stage="planning")
        await upsert_funnel_symbol(session, "601088", "中国神华", stage="executing")
        await session.commit()

        planning = await list_workspace_symbols(session, view="planning")
        executing = await list_workspace_symbols(session, view="executing")
        plan_syms = {p["symbol"] for p in planning}
        exec_syms = {e["symbol"] for e in executing}
        assert "601899" in plan_syms and "601899" not in exec_syms
        assert "601088" in exec_syms and "601088" not in plan_syms
        # 四区互斥：交集为空
        assert plan_syms.isdisjoint(exec_syms)


@pytest.mark.asyncio
async def test_touch_last_analyzed_naive_utc():
    """PostgreSQL TIMESTAMP WITHOUT TIME ZONE 须写入 naive UTC（asyncpg 兼容）。"""
    await init_db()
    async with AsyncSessionLocal() as session:
        await upsert_funnel_symbol(session, "601138", "工业富联", stage="radar_intake")
        await session.commit()
        await touch_last_analyzed(session, "601138")
        await session.commit()
        row = await get_funnel_symbol(session, "601138")
        assert row.last_analyzed_at is not None
        assert row.last_analyzed_at.tzinfo is None


@pytest.mark.asyncio
async def test_executing_workspace_renders_all_symbol_loaders():
    """执行区列表须为每只标的注册 hx-load 详情拉取（非失效的 revealed）。"""
    from apps.copilot.routers.planning_routes import _render_workspace_symbols_html

    items = [
        {"symbol": "601138", "name": "工业富联", "position_pct": 10.0, "quantity": 100, "cost_price": 50},
        {"symbol": "002837", "name": "英维克", "position_pct": 20.0, "quantity": 200, "cost_price": 60},
    ]
    resp = _render_workspace_symbols_html(items, view="executing", container_id=1)
    body = resp.body.decode()
    assert body.count("executing-symbol-card") == 2
    assert "hx-trigger='load once'" in body
    assert "revealed once" not in body
    assert "/api/executing/601138/detail" in body
    assert "/api/executing/002837/detail" in body
    assert " open" in body.split("executing-symbol-card")[1]


@pytest.mark.asyncio
async def test_no_auto_execute_funnel():
    """漏斗中枢不含任何自动下单/交易指令。"""
    import re
    from pathlib import Path

    forbidden = re.compile(r"auto_trade|order_id|qmt|webhook_target|下单|一键", re.I)
    f = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "copilot"
        / "modules"
        / "planning"
        / "funnel.py"
    )
    assert not forbidden.search(f.read_text(encoding="utf-8"))
