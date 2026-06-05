"""T0-2/3 板块动能与资金（通用指标 · 按标的东财行业自动匹配板块）。

[Ref: 27_ §2.2 · 28_ §4.2 · 完善期：禁止 proxy/当日冒充 N 日]
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from apps.copilot.modules.radar.t0.collectors._ak_util import ak_call
from apps.copilot.modules.radar.t0.collectors._em_fetch import (
    fetch_board_daily_fund_flow,
    fetch_board_daily_momentum,
    fetch_industry_boards_pct_3d,
    fetch_sector_fund_flow,
    match_industry_row,
)

_SECTOR_DAILY_LOOKBACK = 10


def _board_pct_change_3d(board_name: str, *, board_code: str | None = None) -> float | None:
    """板块近 3 交易日涨跌幅（push2delay clist 优先 · push2his / akshare hist 回退）。"""
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
    """通用 T0-2/3：按该标的东财 f100 行业返回 sector_momentum + sector_flow。"""
    from apps.copilot.modules.radar.scanner import _collect_profile
    from apps.copilot.modules.radar.t0.collectors._em_fetch import fetch_industry_boards
    from apps.copilot.modules.radar.t0.jobs.cache_merge import read_global_spot_cache

    sym6 = str(sym).zfill(6)[-6:]
    prof = _collect_profile(sym)
    spot_ind = None
    for row in (read_global_spot_cache() or {}).get("rows") or []:
        if str(row.get("code") or "").zfill(6)[-6:] == sym6:
            spot_ind = row.get("industry")
            break
    ind = (industry or spot_ind or (prof.get("industry") if prof.get("status") == "ok" else None) or "").strip() or None
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

    boards_3d = fetch_industry_boards_pct_3d()
    hit_3d = match_industry_row(boards_3d, ind)
    if hit_3d is not None:
        board_name = str(hit_3d.get("board_name") or ind)
        board_code = hit_3d.get("board_code")
        pct_3d = hit_3d.get("pct_chg_3d")
        if pct_3d is None and board_code:
            pct_3d = _board_pct_change_3d(board_name, board_code=str(board_code))
        if pct_3d is not None:
            daily_mom = (
                fetch_board_daily_momentum(
                    str(board_code),
                    days=_SECTOR_DAILY_LOOKBACK,
                    board_name=board_name,
                )
                if board_code
                else []
            )
            momentum = {
                "status": "ok",
                "source": "eastmoney:push2delay/board_clist_3d",
                "symbol": sym6,
                "industry": ind,
                "board_name": board_name,
                "board_code": board_code,
                "pct_chg_3d": pct_3d,
                "daily_10d": daily_mom,
            }
    elif (boards := fetch_industry_boards()) and (hit := match_industry_row(boards, ind)):
        board_name = str(hit.get("board_name") or ind)
        board_code = hit.get("board_code")
        pct_3d = _board_pct_change_3d(board_name, board_code=str(board_code) if board_code else None)
        if pct_3d is not None:
            daily_mom = (
                fetch_board_daily_momentum(
                    str(board_code),
                    days=_SECTOR_DAILY_LOOKBACK,
                    board_name=board_name,
                )
                if board_code
                else []
            )
            momentum = {
                "status": "ok",
                "source": "eastmoney:push2delay/board_clist_3d",
                "symbol": sym6,
                "industry": ind,
                "board_name": board_name,
                "board_code": board_code,
                "pct_chg_3d": pct_3d,
                "daily_10d": daily_mom,
            }

    flows = fetch_sector_fund_flow(indicator="5日")
    flow_hit = match_industry_row(flows, ind)
    board_code_for_flow = (momentum.get("board_code") if momentum.get("status") == "ok" else None)
    if flow_hit is not None:
        try:
            net_yi = round(float(flow_hit.get("net_inflow") or 0) / 1e8, 2)
            daily_flow = (
                fetch_board_daily_fund_flow(
                    str(board_code_for_flow),
                    days=_SECTOR_DAILY_LOOKBACK,
                    board_name=str(flow_hit.get("board_name") or momentum.get("board_name") or ind),
                )
                if board_code_for_flow
                else []
            )
            flow = {
                "status": "ok",
                "source": "eastmoney:push2delay/sector_fund_flow_5d",
                "symbol": sym6,
                "industry": ind,
                "board_name": flow_hit.get("board_name"),
                "board_code": board_code_for_flow,
                "net_inflow_5d_yi": net_yi,
                "daily_10d": daily_flow,
            }
        except (TypeError, ValueError):
            pass
    elif board_code_for_flow:
        daily_flow = fetch_board_daily_fund_flow(
            str(board_code_for_flow),
            days=_SECTOR_DAILY_LOOKBACK,
            board_name=str(momentum.get("board_name") or ind),
        )
        if daily_flow:
            net_5d = round(sum(d.get("net_inflow_yi") or 0 for d in daily_flow[-5:]), 2)
            flow = {
                "status": "ok",
                "source": "eastmoney:push2delay/board_fflow_daykline",
                "symbol": sym6,
                "industry": ind,
                "board_code": board_code_for_flow,
                "net_inflow_5d_yi": net_5d,
                "daily_10d": daily_flow,
            }

    return {"sector_momentum": momentum, "sector_flow": flow}


def _today_cn() -> date:
    return datetime.now(timezone(timedelta(hours=8))).date()


async def upsert_sector_pg(session: Any, sym: str, sector_ctx: dict[str, Any]) -> bool:
    """UPSERT ``radar_sector_daily`` · 仅当 T0-2 sector_momentum=ok 时写入。"""
    from apps.copilot.db.datetime_util import utc_now_naive
    from apps.copilot.db.models import RadarSectorDaily

    momentum = sector_ctx.get("sector_momentum") or {}
    flow = sector_ctx.get("sector_flow") or {}
    if momentum.get("status") != "ok":
        return False

    sym6 = str(sym).zfill(6)[-6:]
    trade_date = _today_cn()
    row = await session.get(RadarSectorDaily, {"symbol": sym6, "trade_date": trade_date})
    if row is None:
        row = RadarSectorDaily(symbol=sym6, trade_date=trade_date)
        session.add(row)

    row.industry = momentum.get("industry")
    row.board_code = momentum.get("board_code")
    row.board_name = momentum.get("board_name")
    row.pct_chg_3d = momentum.get("pct_chg_3d")
    row.net_inflow_5d_yi = flow.get("net_inflow_5d_yi") if flow.get("status") == "ok" else None
    row.momentum_json = momentum
    row.flow_json = flow if flow.get("status") == "ok" else {}
    row.collected_at = utc_now_naive()
    row.source = momentum.get("source")
    return True
