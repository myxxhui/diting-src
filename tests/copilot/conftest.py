"""测试夹具。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/00_维度零/.../step_03 — dispose 异步引擎须 asyncio.run]
"""
import asyncio
import os
import pathlib

import pytest

_TEST_DB = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "test_copilot.db"
_TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["COPILOT_DB_URL"] = f"sqlite+aiosqlite:///{_TEST_DB.as_posix()}"
os.environ["COPILOT_ALERT_CONSUMER_ENABLED"] = "false"
os.environ["COPILOT_LEDGER_SCHEDULER_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _clean_db():
    from apps.copilot.db import database

    async def _dispose() -> None:
        await database.engine.dispose()

    if _TEST_DB.exists():
        _TEST_DB.unlink()
    asyncio.run(_dispose())
    yield
    asyncio.run(_dispose())
    if _TEST_DB.exists():
        _TEST_DB.unlink()
