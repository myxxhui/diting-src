"""Copilot PG 持久化 · 部署可恢复（雷达对话 / UI 设置 / 搜索历史）。"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.copilot.db.database import Base
from apps.copilot.modules.copilot_ui_settings import (
    SETTING_WORKBENCH_PREFS,
    load_query_history,
    remember_query,
    save_setting_row,
    warm_ui_settings_from_pg,
)
from apps.copilot.modules.radar.chat import (
    load_messages_async,
    persist_radar_session,
    save_messages_async,
    title_from_messages,
    warm_radar_chat_sessions_from_pg,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_radar_chat_pg_redis_roundtrip(db_session: AsyncSession):
    redis = _FakeRedis()
    sid = "abc123"
    msgs = [
        {"role": "user", "content": "测试问题"},
        {"role": "assistant", "content": "测试回答"},
    ]
    await save_messages_async(sid, msgs, redis_client=redis, db_session=db_session)
    await db_session.commit()

    redis.store.clear()
    from apps.copilot.modules.radar import chat as chat_mod

    chat_mod._memory_sessions.pop(sid, None)
    loaded = await load_messages_async(sid, redis_client=redis, db_session=db_session)
    assert len(loaded) == 2
    assert loaded[0]["content"] == "测试问题"
    assert redis.store


@pytest.mark.asyncio
async def test_warm_radar_chat_sessions(db_session: AsyncSession):
    redis = _FakeRedis()
    await persist_radar_session(
        db_session,
        "sess01",
        [{"role": "user", "content": "hello"}],
    )
    await db_session.commit()
    stats = await warm_radar_chat_sessions_from_pg(db_session, redis, limit=10)
    assert stats["warmed"] == 1
    assert redis.store


@pytest.mark.asyncio
async def test_query_history_pg(db_session: AsyncSession):
    result = await remember_query(db_session, "工业富联")
    await db_session.commit()
    assert result["queries"][0] == "工业富联"
    assert result["last"] == "工业富联"

    again = await load_query_history(db_session)
    assert again["queries"][0] == "工业富联"


@pytest.mark.asyncio
async def test_warm_ui_settings(db_session: AsyncSession):
    await save_setting_row(
        db_session, SETTING_WORKBENCH_PREFS, {"enable_t0_default": True, "version": 1}
    )
    await db_session.commit()
    stats = await warm_ui_settings_from_pg(db_session)
    assert stats["loaded"] >= 1


def test_title_from_messages():
    assert title_from_messages([{"role": "user", "content": "  长标题测试 "}], default="x") == "长标题测试"
