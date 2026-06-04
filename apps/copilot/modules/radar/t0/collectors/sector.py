"""T0-2/3 板块动能与资金。

[Ref: 27_ §2.2 · 28_ 完善期：禁止 proxy/当日冒充 N 日]
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call
from apps.copilot.modules.radar.t0.collectors._em_fetch import (
    fetch_sector_fund_flow,
    match_industry_row,
)


def _board_pct_change_3d(board_name: str, *, board_code: str | None = None) -> float | None:
    """板块近 3 交易日涨跌幅（push2his 优先 · akshare hist 回退）。"""
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_board_pct_3d

    if board_code:
        pct = fetch_board_pct_3d(board_code)
        if pct is not None:
            return pct
    try:
        import akshare as ak
    except ImportError:
        return None
    end = datetime.now(timezone(timedelta(hours=8)))
    start = end - timedelta(days=14)
    df = ak_call(
        ak.stock_board_industry_hist_em,
        symbol=board_name,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="",
    )
    if df is None or df.empty or "收盘" not in df.columns:
        return None
    closes = df["收盘"].astype(float).tolist()
    if len(closes) < 2:
        return None
    last = closes[-1]
    ref = closes[-4] if len(closes) >= 4 else closes[0]
    if ref in (0, None):
        return None
    return round((last - ref) / ref * 100, 2)


def collect_sector_context(sym: str, *, industry: str | None = None) -> dict[str, Any]:
    """按标的行业返回 sector_momentum + sector_flow 子块。"""
    from apps.copilot.modules.radar.scanner import _collect_profile
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_industry_boards

    _ = sym
    ind = industry
    if not ind:
        prof = _collect_profile(sym)
        ind = prof.get("industry") if prof.get("status") == "ok" else None
    if not ind:
        return {
            "sector_momentum": {"status": "error", "detail": "T0-2 无行业标签"},
            "sector_flow": {"status": "error", "detail": "T0-3 无行业标签"},
        }

    momentum: dict[str, Any] = {
        "status": "error",
        "detail": "T0-2 板块 3 日涨跌未获取",
    }
    flow: dict[str, Any] = {
        "status": "error",
        "detail": "T0-3 板块 5 日资金未获取",
    }

    boards = fetch_industry_boards()
    hit = match_industry_row(boards, ind)
    if hit is not None:
        board_name = str(hit.get("board_name") or ind)
        board_code = hit.get("board_code")
        pct_3d = _board_pct_change_3d(board_name, board_code=str(board_code) if board_code else None)
        if pct_3d is not None:
            momentum = {
                "status": "ok",
                "source": "eastmoney:push2his/board_kline_3d",
                "industry": ind,
                "board_name": board_name,
                "board_code": board_code,
                "pct_chg_3d": pct_3d,
            }

    flows = fetch_sector_fund_flow(indicator="5日")
    flow_hit = match_industry_row(flows, ind)
    if flow_hit is not None:
        try:
            net_yi = round(float(flow_hit.get("net_inflow") or 0) / 1e8, 2)
            flow = {
                "status": "ok",
                "source": "eastmoney:push2delay/sector_fund_flow_5d",
                "industry": ind,
                "board_name": flow_hit.get("board_name"),
                "net_inflow_5d_yi": net_yi,
            }
        except (TypeError, ValueError):
            pass

    return {"sector_momentum": momentum, "sector_flow": flow}
