"""初始化数据库(holdings + audit + pending_signals)。

[Ref: 03_/04_维度四_卖出决策/stages/stage_1_启动期/steps/step_04_SP2止盈协议.md]
"""
from __future__ import annotations

import os

from apps.exit_engine.db.session import get_engine
from apps.exit_engine.models.audit import ExitAuditORM  # noqa: F401
from apps.exit_engine.models.buffer import PendingSignalORM  # noqa: F401
from apps.exit_engine.models.event_log import EventLogORM  # noqa: F401
from apps.exit_engine.models.position import Base as PositionBase
from apps.exit_engine.models.position import HoldingORM  # noqa: F401
from apps.exit_engine.models.protocol_log import ProtocolLogORM  # noqa: F401


def init() -> None:
    os.makedirs("data", exist_ok=True)
    PositionBase.metadata.create_all(bind=get_engine())
    print("✅ exit_engine.db 初始化完成 (tables: holdings, exit_audit_logs, pending_signals, protocol_logs, event_logs)")


if __name__ == "__main__":
    init()
