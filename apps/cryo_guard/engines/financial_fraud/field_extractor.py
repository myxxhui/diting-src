"""N1 field_extractor — 按 symbol + report_period 从 financial_reports 抽 11 字段。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2·N1]
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "cash", "total_assets", "total_debt", "accounts_receivable",
    "inventory", "rd_capitalized", "gross_margin",
    "operating_cash_flow", "net_profit", "revenue", "industry",
]


def extract_fields(
    symbol: str,
    report_period: str,
    db_session=None,
) -> dict:
    """从 financial_reports 表提取 11 个字段。

    缺失字段标记为 None 并加入 missing_fields 列表。
    [Ref: step_04 §3.5.2·N1]
    """
    result: dict = {"symbol": symbol, "report_period": report_period, "missing_fields": []}

    if db_session is None:
        logger.warning("[N1] db_session 未注入，返回空字段（tier-1 骨架）")
        for field in REQUIRED_FIELDS:
            result[field] = None
            result["missing_fields"].append(field)
        return result

    try:
        row = db_session.execute(
            "SELECT * FROM financial_reports WHERE symbol = ? AND report_period = ?",
            (symbol, report_period),
        ).fetchone()
    except Exception as e:
        logger.error("[N1] 查询失败 symbol=%s period=%s err=%s", symbol, report_period, e)
        for field in REQUIRED_FIELDS:
            result[field] = None
            result["missing_fields"].append(field)
        return result

    if row is None:
        logger.warning("[N1] 无记录 symbol=%s period=%s", symbol, report_period)
        for field in REQUIRED_FIELDS:
            result[field] = None
            result["missing_fields"].append(field)
        return result

    for field in REQUIRED_FIELDS:
        val = row[field] if hasattr(row, "__getitem__") else getattr(row, field, None)
        result[field] = val
        if val is None:
            result["missing_fields"].append(field)

    logger.info("[N1] symbol=%s period=%s missing=%s", symbol, report_period, result["missing_fields"])
    return result
