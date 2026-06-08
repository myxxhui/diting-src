"""时间工具单测。"""
from __future__ import annotations

from apps.copilot.db.datetime_util import utc_naive_to_shanghai_display


def test_utc_naive_to_shanghai_display():
    assert utc_naive_to_shanghai_display("2026-06-08T07:55:04.270822") == "2026-06-08 15:55:04"
