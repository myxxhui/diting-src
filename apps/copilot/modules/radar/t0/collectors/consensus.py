"""T0-12/13 一致预期与评级。

[Ref: 27_ §2.5]
"""
from __future__ import annotations

from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call


def collect_consensus(sym: str) -> dict[str, Any]:
    try:
        import akshare as ak
    except ImportError:
        return {
            "eps_forecast": {"status": "error", "detail": "akshare 不可用"},
            "rating_changes": {"status": "error", "detail": "akshare 不可用"},
        }

    df = ak_call(ak.stock_profit_forecast_em)
    eps_block: dict[str, Any] = {"status": "skip", "detail": "无一致预期"}
    rating_block: dict[str, Any] = {"status": "skip", "detail": "无评级变动"}

    if df is not None and not df.empty and "代码" in df.columns:
        sub = df[df["代码"].astype(str).str.zfill(6) == sym]
        if not sub.empty:
            row = sub.iloc[0]
            growth = row.get("2024预测每股收益") or row.get("2025预测每股收益")
            eps_block = {
                "status": "ok",
                "source": "akshare:stock_profit_forecast_em",
                "forecast_eps": growth,
                "report_count": int(row.get("研报数") or 0),
            }
            buy = int(row.get("机构投资评级(近六个月)-买入") or 0)
            add = int(row.get("机构投资评级(近六个月)-增持") or 0)
            rating_block = {
                "status": "ok",
                "source": "akshare:stock_profit_forecast_em",
                "buy_count": buy,
                "add_count": add,
                "upgrade_proxy": buy + add,
            }

    return {"eps_forecast": eps_block, "rating_changes": rating_block}
