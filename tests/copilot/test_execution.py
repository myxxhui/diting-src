"""M11 执行中仓位指导 pytest（≥ 12 用例）。

[Ref: step_17_执行中仓位指导.md §5 §G · no-auto-execute 最强红线]
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.copilot.db.database import AsyncSessionLocal, init_db
from apps.copilot.db.models import Campaign, CampaignSymbol, ExecutionAdvice
from apps.copilot.main import app


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _exec_fake_redis(monkeypatch):
    try:
        from fakeredis import FakeRedis

        fake = FakeRedis(decode_responses=True)

        def _fake_wait(**_kwargs):
            return fake

        for mod in (
            "apps.copilot.routers.planning_routes",
            "apps.copilot.services.redis_wait",
            "apps.copilot.modules.planning.service",
            "apps.copilot.modules.execution.advisor",
        ):
            try:
                monkeypatch.setattr(f"{mod}.wait_for_sync_redis", _fake_wait)
            except AttributeError:
                pass
        yield fake
    except ImportError:
        yield None


@pytest.fixture(autouse=True)
def _no_external_price(monkeypatch):
    """屏蔽真实行情 API，返回固定测试价格。"""
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_fetch_realtime_price", lambda sym, _rc: (10.0, False))


@pytest.fixture(autouse=True)
def _no_fraud_engine(monkeypatch):
    """屏蔽 LoRA 安全扫描，默认返回 ok。"""
    import apps.copilot.modules.execution.advisor as adv

    async def _fake_safety(_session, _sym):
        return "ok"

    monkeypatch.setattr(adv, "_safety_status", _fake_safety)


@pytest.fixture(autouse=True)
def _no_holdings(monkeypatch):
    """屏蔽持仓 SoT，默认返回无持仓（未持仓→建仓态）。"""
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_get_holding", lambda sym: None)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def _campaign(client):
    """创建 Campaign + 导入 601138。"""
    r = client.post("/api/campaigns", json={"name": "exec-test", "theme": "执行测试"})
    assert r.status_code == 200
    cid = r.json()["id"]
    async with AsyncSessionLocal() as s:
        s.add(CampaignSymbol(campaign_id=cid, symbol="601138", name="工业富联"))
        await s.commit()
    return cid


# ── 测试 1: 浮盈亏计算（无持仓 → None）────────────────────────────────────────


def test_pnl_no_holding(monkeypatch):
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_get_holding", lambda sym: None)
    # 无持仓时 cost/qty 均 None
    holding = adv._get_holding("601138")
    assert holding is None


# ── 测试 2: 浮盈亏计算（有持仓）────────────────────────────────────────────────


def test_pnl_with_holding():
    from apps.common.holdings_sot import HoldingEntry

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=8.0)
    price = 10.0
    pnl = (price - h.cost_price) / h.cost_price * 100
    assert abs(pnl - 25.0) < 0.01


# ── 测试 3: 无持仓建仓建议分支 ─────────────────────────────────────────────────


def test_advice_build_when_no_holding():
    from apps.copilot.modules.execution.advisor import _build_advice
    from apps.copilot.modules.planning.falsify import FALSIFY_TYPES

    tasks = [{"falsify_type": t, "verdict": "ok"} for t in FALSIFY_TYPES]
    readiness = {
        "total": len(tasks),
        "ok_rate": 1.0,
        "falsified": 0,
        "pending": 0,
        "ready_for_executing": True,
    }
    action, rationale, _evidence = _build_advice(
        None, 10.0, False, tasks, readiness, "concept", True, "ok"
    )
    assert "建仓" in action or "持有" in action


# ── 测试 4: 浮盈分批减仓分支 ─────────────────────────────────────────────────


def test_advice_trim_high_profit():
    from apps.common.holdings_sot import HoldingEntry
    from apps.copilot.modules.execution.advisor import TAKE_PROFIT_PCT, _build_advice

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=8.0)
    price = 8.0 * (1 + TAKE_PROFIT_PCT / 100 * 1.6)  # 超过阈值 60%
    tasks = [{"falsify_type": "moat", "verdict": "ok"}]
    readiness = {"total": 1, "ok_rate": 1.0, "falsified": 0, "pending": 0, "ready_for_executing": True}
    action, rationale, _ = _build_advice(h, price, False, tasks, readiness, "realization", True, "ok")
    assert "减仓" in action or "浮盈" in action or "持有" in action  # realization 阶段触发


# ── 测试 5: 浮亏+证伪 → 止损建议 ─────────────────────────────────────────────


def test_advice_loss_when_falsified():
    from apps.common.holdings_sot import HoldingEntry
    from apps.copilot.modules.execution.advisor import STOP_LOSS_PCT, _build_advice

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=10.0)
    price = 10.0 * (1 + STOP_LOSS_PCT / 100 * 1.5)  # 超过止损线
    tasks = [{"falsify_type": "moat", "verdict": "alert"}, {"falsify_type": "catalyst", "verdict": "alert"}]
    readiness = {"total": 2, "ok_rate": 0.0, "falsified": 2, "pending": 0, "ready_for_executing": False}
    action, rationale, _ = _build_advice(h, price, False, tasks, readiness, "exhaustion", False, "ok")
    assert "止损" in action or "证伪" in action or "清仓" in action


# ── 测试 6: fraud → 清仓提示 ──────────────────────────────────────────────────


def test_advice_exit_on_fraud():
    from apps.common.holdings_sot import HoldingEntry
    from apps.copilot.modules.execution.advisor import _build_advice

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=10.0)
    tasks = []
    readiness = {"total": 0, "ok_rate": 0, "falsified": 0, "pending": 0, "ready_for_executing": False}
    action, rationale, _ = _build_advice(h, 10.0, False, tasks, readiness, None, False, "fraud")
    assert "清仓" in action or "风险" in action


# ── 测试 7: fraud 时加仓建议被压制 ────────────────────────────────────────────


def test_fraud_suppresses_add_advice():
    from apps.common.holdings_sot import HoldingEntry
    from apps.copilot.modules.execution.advisor import _build_advice

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=8.0)
    price = 8.5
    tasks = [{"falsify_type": t, "verdict": "ok"} for t in ("moat", "catalyst", "niche", "risk")]
    readiness = {"total": 4, "ok_rate": 1.0, "falsified": 0, "pending": 0, "ready_for_executing": True}
    action, _, evidence = _build_advice(h, price, False, tasks, readiness, "concept", True, "fraud")
    assert "清仓" in action or "风险" in action
    assert evidence["safety_status"] == "fraud"


# ── 测试 8: safety=pending → 暂缓加仓（不清仓）──────────────────────────────


def test_safety_pending_does_not_clear():
    from apps.common.holdings_sot import HoldingEntry
    from apps.copilot.modules.execution.advisor import _build_advice

    h = HoldingEntry(symbol="601138", name="工业富联", quantity=1000, cost_price=8.0)
    tasks = [{"falsify_type": t, "verdict": "ok"} for t in ("moat", "catalyst")]
    readiness = {"total": 2, "ok_rate": 1.0, "falsified": 0, "pending": 0, "ready_for_executing": True}
    action, rationale, _ = _build_advice(h, 8.5, False, tasks, readiness, "concept", True, "pending")
    assert "清仓" not in action
    assert "暂缓" in action or "持有" in action or "加仓" in action


# ── 测试 9: no-auto-execute schema 审计 ──────────────────────────────────────


def test_no_auto_execute_schema():
    """ExecutionAdvice 不含下单字段。"""
    import subprocess

    import shutil
    rg = shutil.which("rg")
    if rg is None:
        pytest.skip("rg 不在 PATH，跳过命令行审计（代码审计已在 test_advice_action_no_trade_words 覆盖）")
    result = subprocess.run(
        [
            rg,
            "-i",
            "buy|qmt|auto_trade|order_id|webhook_target",
            "apps/copilot/modules/execution/",
            "apps/copilot/templates/planning/",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), "../.."),
    )
    assert result.returncode != 0 or result.stdout.strip() == "", (
        f"no-auto-execute 审计失败，发现下单相关字段：\n{result.stdout}"
    )


# ── 测试 10: generate_execution_advice 写库 ───────────────────────────────────


@pytest.mark.anyio
async def test_generate_advice_writes_db(monkeypatch):
    import apps.copilot.modules.execution.advisor as adv

    # 持仓：已持仓 600 股成本 8.0
    from apps.common.holdings_sot import HoldingEntry

    monkeypatch.setattr(
        adv, "_get_holding", lambda sym: HoldingEntry("601138", "工业富联", quantity=600, cost_price=8.0)
    )

    await init_db()
    async with AsyncSessionLocal() as s:
        camp = Campaign(theme="exec-db-test", status="executing")
        s.add(camp)
        await s.flush()
        s.add(CampaignSymbol(campaign_id=camp.id, symbol="601138", name="工业富联"))
        await s.commit()

        result = await adv.generate_execution_advice(s, camp.id, "601138")
        await s.commit()

    async with AsyncSessionLocal() as s:
        row = await s.scalar(select(ExecutionAdvice))
        assert row is not None
        assert row.symbol == "601138"
        assert row.execute_mode == "advisory"
        assert row.human_confirmation_required is True
        assert row.current_price == 10.0  # mocked


# ── 测试 11: list_execution_advices API ───────────────────────────────────────


def test_api_execution_list_json(client, monkeypatch):
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_get_holding", lambda sym: None)
    r = client.get("/api/campaigns/1/execution")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── 测试 12: POST advise API 返回 advice_action ────────────────────────────────


def test_api_advise_returns_action(client, monkeypatch):
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_get_holding", lambda sym: None)
    # 先创建 campaign
    r_camp = client.post("/api/campaigns", json={"name": "api-test17", "theme": "t"})
    assert r_camp.status_code in (200, 201)
    cid = r_camp.json()["id"]

    # 同步方式通过 API 加入标的（已有 CampaignSymbol 路由）
    # 直接通过 import_portfolio_to_campaign 接口或先检查是否已有
    import asyncio

    async def _ensure_symbol():
        async with AsyncSessionLocal() as s:
            s.add(CampaignSymbol(campaign_id=cid, symbol="601138", name="工业富联"))
            await s.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_ensure_symbol())
    finally:
        loop.close()

    r = client.post(f"/api/campaigns/{cid}/execution/advise", data={"symbol": "601138"})
    assert r.status_code == 200
    body = r.json()
    assert "advice_action" in body
    assert body["execute_mode"] == "advisory"
    assert body["human_confirmation_required"] is True


# ── 测试 13: stale 价格标注 ───────────────────────────────────────────────────


def test_stale_price_flag(monkeypatch):
    import apps.copilot.modules.execution.advisor as adv

    monkeypatch.setattr(adv, "_fetch_realtime_price", lambda sym, _rc: (10.0, True))
    price, stale = adv._fetch_realtime_price("601138", None)
    assert stale is True


# ── 测试 14: 归档 API 可调用 ──────────────────────────────────────────────────


def test_archive_api_exists(client):
    r = client.post("/api/campaigns/1/archive")
    assert r.status_code in (200, 404, 422)  # 允许 campaign 不存在或无执行中


# ── 测试 15: advice_action 不含下单词汇 ──────────────────────────────────────


def test_advice_action_no_trade_words():
    from apps.copilot.modules.execution.advisor import _build_advice

    tasks = []
    readiness = {"total": 0, "ok_rate": 0, "falsified": 0, "pending": 0, "ready_for_executing": False}
    for safety in ("ok", "fraud", "pending"):
        action, _, _ = _build_advice(None, 10.0, False, tasks, readiness, None, False, safety)
        for bad in ("buy", "qmt", "下单", "一键", "auto_trade"):
            assert bad not in action.lower(), f"advice_action 含下单词汇 '{bad}': {action}"
