"""原始 dict → ORM 字段映射与类型清洗。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

from typing import Any

from apps.deep_strike.db.models import Announcement, FinancialIndicator, FinancialReport, IndustryPeer


def to_financial_report(symbol: str, row: dict[str, Any]) -> FinancialReport:
    pe = row.get("period_end")
    if hasattr(pe, "to_pydatetime"):
        pe = pe.to_pydatetime()
    if pe is not None:
        from datetime import date, datetime

        if isinstance(pe, date) and not isinstance(pe, datetime):
            pe = datetime(pe.year, pe.month, pe.day)
    return FinancialReport(
        symbol=symbol,
        report_type=str(row.get("report_type", "income")),
        period=str(row.get("period", "")),
        period_end=pe,
        revenue=_f(row.get("revenue")),
        cost=_f(row.get("cost")),
        gross_profit=_f(row.get("gross_profit")),
        operating_expense=_f(row.get("operating_expense")),
        net_profit=_f(row.get("net_profit")),
        raw=dict(row.get("raw") or {}),
    )


def to_financial_indicator(symbol: str, row: dict[str, Any]) -> FinancialIndicator:
    pe = row.get("period_end")
    if hasattr(pe, "to_pydatetime"):
        pe = pe.to_pydatetime()
    if pe is not None:
        from datetime import date, datetime

        if isinstance(pe, date) and not isinstance(pe, datetime):
            pe = datetime(pe.year, pe.month, pe.day)
    return FinancialIndicator(
        symbol=symbol,
        period=str(row.get("period", "")),
        period_end=pe,
        gross_margin=_f(row.get("gross_margin")),
        gross_margin_qoq=_f(row.get("gross_margin_qoq")),
        gross_margin_yoy=_f(row.get("gross_margin_yoy")),
        revenue_growth_yoy=_f(row.get("revenue_growth_yoy")),
        cost_growth_yoy=_f(row.get("cost_growth_yoy")),
        net_profit_growth_yoy=_f(row.get("net_profit_growth_yoy")),
        receivable_turnover=_f(row.get("receivable_turnover")),
        receivable_turnover_qoq=_f(row.get("receivable_turnover_qoq")),
        inventory_turnover=_f(row.get("inventory_turnover")),
        inventory_turnover_qoq=_f(row.get("inventory_turnover_qoq")),
        pe=_f(row.get("pe")),
        pb=_f(row.get("pb")),
        raw=dict(row.get("raw") or {}),
    )


def to_announcement(symbol: str, row: dict[str, Any]) -> Announcement:
    pub = row.get("published_at")
    if hasattr(pub, "to_pydatetime"):
        pub = pub.to_pydatetime()
    if pub is not None:
        from datetime import date, datetime

        if isinstance(pub, date) and not isinstance(pub, datetime):
            pub = datetime(pub.year, pub.month, pub.day)
    return Announcement(
        symbol=symbol,
        announcement_id=str(row.get("announcement_id", ""))[:64],
        title=str(row.get("title", ""))[:512],
        published_at=pub,
        url=str(row.get("url"))[:1024] if row.get("url") else None,
        summary=(str(row.get("summary"))[:4096] if row.get("summary") else None),
        full_text=(str(row.get("full_text"))[:65536] if row.get("full_text") else None),
        source=str(row.get("source", "cninfo"))[:32],
        raw=row.get("raw"),
    )


def to_industry_peer(symbol: str, row: dict[str, Any]) -> IndustryPeer:
    return IndustryPeer(
        symbol=symbol,
        industry_code=str(row.get("industry_code", ""))[:32],
        industry_name=str(row.get("industry_name", ""))[:64],
        peer_symbol=str(row.get("peer_symbol", ""))[:16],
        peer_name=str(row.get("peer_name", ""))[:64],
        peer_metric_snapshot=dict(row.get("peer_metric_snapshot") or {}),
    )


def _f(v):  # noqa: ANN001
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
