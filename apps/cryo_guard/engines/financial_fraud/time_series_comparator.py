"""N3 time_series_comparator — 同 symbol 至少 4 期历史趋势分析。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2·N3]
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MIN_PERIODS = 4


def compare_time_series(
    symbol: str,
    current_period: str,
    db_session=None,
) -> dict:
    """拉取同 symbol 历史数据计算 yoy 趋势。

    不足 4 期时返回 insufficient=True，允许下游继续工作。
    [Ref: step_04 §3.5.2·N3]
    """
    result = {
        "symbol": symbol,
        "current_period": current_period,
        "insufficient": False,
        "periods": [],
        "trends": {},
    }

    if db_session is None:
        logger.warning("[N3] db_session 未注入，返回 insufficient=True（tier-1 骨架）")
        result["insufficient"] = True
        return result

    try:
        rows = db_session.execute(
            "SELECT * FROM financial_reports WHERE symbol = ? ORDER BY report_period DESC LIMIT 8",
            (symbol,),
        ).fetchall()
    except Exception as e:
        logger.error("[N3] 查询失败 symbol=%s err=%s", symbol, e)
        result["insufficient"] = True
        return result

    result["periods"] = [r["report_period"] for r in rows] if rows else []

    if len(rows) < MIN_PERIODS:
        logger.warning("[N3] symbol=%s 历史期数=%d < %d，标 insufficient", symbol, len(rows), MIN_PERIODS)
        result["insufficient"] = True
        return result

    # 简单计算最新一期 vs 上一期 yoy
    fields_to_trend = ["revenue", "gross_margin", "operating_cash_flow", "accounts_receivable"]
    curr = {k: rows[0][k] for k in fields_to_trend if k in (rows[0].keys() if hasattr(rows[0], "keys") else [])}
    prev = {k: rows[1][k] for k in fields_to_trend if k in (rows[1].keys() if hasattr(rows[1], "keys") else [])}

    for f in fields_to_trend:
        c, p = curr.get(f), prev.get(f)
        if c is not None and p is not None and p != 0:
            result["trends"][f] = (c - p) / p
        else:
            result["trends"][f] = None

    logger.info("[N3] symbol=%s periods=%d trends=%s", symbol, len(rows), result["trends"])
    return result
