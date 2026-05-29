"""N4 peer_comparator — 按 industry 拉同行 ≥3 家算百分位。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2·N4]
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

MIN_PEERS = 3


def compare_with_peers(
    symbol: str,
    industry: str,
    fields: dict,
    db_session=None,
) -> dict:
    """与同行业公司对比 gross_margin / inventory_ratio 百分位。

    同行业不足 3 家时退回全市场，并标 peer_fallback=market_wide。
    [Ref: step_04 §3.5.2·N4]
    """
    result = {
        "symbol": symbol,
        "industry": industry,
        "peer_fallback": None,
        "peer_count": 0,
        "percentiles": {},
        "industry_medians": {},
    }

    if db_session is None:
        logger.warning("[N4] db_session 未注入，返回空百分位（tier-1 骨架）")
        result["peer_fallback"] = "no_db"
        return result

    try:
        peers = db_session.execute(
            "SELECT symbol, gross_margin, inventory, revenue FROM financial_reports "
            "WHERE industry = ? AND symbol != ? GROUP BY symbol",
            (industry, symbol),
        ).fetchall()
    except Exception as e:
        logger.error("[N4] 查询同行失败 err=%s", e)
        result["peer_fallback"] = "query_error"
        return result

    if len(peers) < MIN_PEERS:
        logger.warning("[N4] 同行 %d 家 < %d，退回全市场", len(peers), MIN_PEERS)
        result["peer_fallback"] = "market_wide"
        try:
            peers = db_session.execute(
                "SELECT symbol, gross_margin, inventory, revenue FROM financial_reports "
                "WHERE symbol != ? GROUP BY symbol",
                (symbol,),
            ).fetchall()
        except Exception:
            result["peer_fallback"] = "query_error"
            return result

    result["peer_count"] = len(peers)

    gm_vals = [p["gross_margin"] for p in peers if p.get("gross_margin") is not None]
    inv_ratios = [
        p["inventory"] / p["revenue"]
        for p in peers
        if p.get("inventory") and p.get("revenue")
    ]

    if gm_vals:
        gm_vals_sorted = sorted(gm_vals)
        result["industry_medians"]["gross_margin"] = gm_vals_sorted[len(gm_vals_sorted) // 2]
        my_gm = fields.get("gross_margin")
        if my_gm is not None:
            rank = sum(1 for v in gm_vals if v < my_gm) / len(gm_vals)
            result["percentiles"]["gross_margin"] = rank

    if inv_ratios:
        inv_sorted = sorted(inv_ratios)
        result["industry_medians"]["inventory_ratio"] = inv_sorted[len(inv_sorted) // 2]

    logger.info("[N4] peer_count=%d fallback=%s percentiles=%s", result["peer_count"], result["peer_fallback"], result["percentiles"])
    return result
