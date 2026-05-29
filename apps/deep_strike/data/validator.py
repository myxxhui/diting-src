"""入库前轻量校验。"""

from __future__ import annotations

from typing import Any


def validate_financial_report(row: dict[str, Any]) -> bool:
    return bool(row.get("period")) and row.get("period_end") is not None


def validate_financial_indicator(row: dict[str, Any]) -> bool:
    return bool(row.get("period")) and row.get("period_end") is not None


def validate_announcement(row: dict[str, Any]) -> bool:
    return bool(row.get("title")) and bool(row.get("announcement_id"))
