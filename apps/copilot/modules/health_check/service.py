"""持仓体检报告服务(M1)。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_03]
[Ref: 03_/00_维度零/.../02_技术方案与代码架构.md#3.2-持仓体检服务]
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import HealthRecord, Holding, User

Color = Literal["red", "orange", "yellow", "green"]


def push_level_to_color(push_level: int) -> Color:
    """4 色映射纯函数(可直接 unit-test)。

    push_level >= 3 -> red
    push_level == 2 -> orange
    push_level == 1 -> yellow
    其它             -> green
    """
    if push_level >= 3:
        return "red"
    if push_level == 2:
        return "orange"
    if push_level == 1:
        return "yellow"
    return "green"


@dataclass
class HealthCardItem:
    symbol: str
    name: str
    color: Color
    push_level: int
    new_health: float
    health_delta: float
    change_reason: str | None
    occurred_at: str


async def _latest_health_map(
    session: AsyncSession, symbols: list[str]
) -> dict[str, HealthRecord]:
    """按 symbol 取最近一条 HealthRecord。"""
    if not symbols:
        return {}
    rows = await session.scalars(
        select(HealthRecord)
        .where(HealthRecord.symbol.in_(symbols))
        .order_by(HealthRecord.symbol, desc(HealthRecord.received_at))
    )
    latest: dict[str, HealthRecord] = {}
    for r in rows:
        if r.symbol not in latest:
            latest[r.symbol] = r
    return latest


async def get_dashboard(session: AsyncSession, user_id: str = "default") -> dict:
    """4 色卡片首屏数据。

    无 HealthRecord 的持仓默认 push_level=0(green)。
    """
    user = await session.scalar(select(User).where(User.user_id == user_id))
    if user is None:
        return {
            "cards": {"red": [], "orange": [], "yellow": [], "green": []},
            "summary": {"total": 0, "red": 0, "orange": 0, "yellow": 0, "green": 0},
        }

    holdings_rows = await session.scalars(
        select(Holding).where(Holding.user_pk == user.id).order_by(Holding.symbol)
    )
    holdings = list(holdings_rows.all())
    latest = await _latest_health_map(session, [h.symbol for h in holdings])

    cards: dict[Color, list[dict]] = defaultdict(list)
    for h in holdings:
        rec = latest.get(h.symbol)
        push_level = rec.push_level if rec else 0
        color = push_level_to_color(push_level)
        item = HealthCardItem(
            symbol=h.symbol,
            name=h.name,
            color=color,
            push_level=push_level,
            new_health=rec.new_health if rec else 100.0,
            health_delta=rec.health_delta if rec else 0.0,
            change_reason=rec.change_reason if rec else "尚无健康度事件",
            occurred_at=(rec.received_at if rec else datetime.utcnow()).isoformat(),
        )
        cards[color].append(asdict(item))

    summary = {c: len(cards[c]) for c in ("red", "orange", "yellow", "green")}
    summary["total"] = sum(summary.values())
    return {
        "cards": {c: cards[c] for c in ("red", "orange", "yellow", "green")},
        "summary": summary,
    }


async def get_detail(session: AsyncSession, symbol: str, days: int = 30) -> dict:
    """单持仓详情:节点 4 态 + N 天健康度趋势。"""
    rows = await session.scalars(
        select(HealthRecord)
        .where(HealthRecord.symbol == symbol)
        .where(HealthRecord.received_at >= datetime.utcnow() - timedelta(days=days))
        .order_by(HealthRecord.received_at.asc())
    )
    history = [
        {
            "date": r.received_at.strftime("%Y-%m-%d %H:%M"),
            "score": r.new_health,
            "delta": r.health_delta,
            "push_level": r.push_level,
            "reason": r.change_reason or "",
        }
        for r in rows
    ]
    latest = history[-1] if history else None
    state = "unknown"
    if latest:
        state = {3: "exit", 2: "warning", 1: "watch"}.get(latest["push_level"], "stable")
    return {
        "symbol": symbol,
        "state": state,
        "history": history,
        "color": push_level_to_color(latest["push_level"] if latest else 0),
    }
