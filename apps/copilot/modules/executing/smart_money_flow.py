"""L2 主力大单资金流向 · Tushare moneyflow 管道。

T0：拉取 moneyflow 原始行 + daily_basic 自由流通股本。
T1：阶级隔离（特大单+大单）→ 3 日累计 → 流通盘归一化。

[Ref: 28_ §3.2 #17 · smart_money_flow]
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

_LOT_SIZE = 100  # Tushare moneyflow 成交量单位为「手」，1 手 = 100 股
_WAN_SHARES = 10_000  # daily_basic 股本字段单位为「万股」


def tushare_token() -> str | None:
    tok = (os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_PRO_TOKEN") or "").strip()
    return tok or None


def symbol_to_ts_code(symbol: str) -> str:
    sym = symbol.zfill(6)[-6:]
    suffix = "SH" if sym.startswith(("5", "6", "9")) else "SZ"
    return f"{sym}.{suffix}"


def _pro_api():
    import tushare as ts  # type: ignore

    token = tushare_token()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    return ts.pro_api()


def fetch_moneyflow_raw(symbol: str, *, lookback_days: int = 10) -> dict[str, Any]:
    """T0 采集：近 N 自然日的 moneyflow 行 + 最新自由流通股本。"""
    ts_code = symbol_to_ts_code(symbol)
    end = date.today()
    start = end - timedelta(days=lookback_days)
    pro = _pro_api()
    df = pro.moneyflow(
        ts_code=ts_code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    if df is None or df.empty:
        raise ValueError(f"moneyflow 无数据 ts_code={ts_code}")

    basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=(end - timedelta(days=5)).strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        fields="ts_code,trade_date,free_share,float_share",
    )
    free_float_shares: float | None = None
    if basic is not None and not basic.empty:
        basic = basic.sort_values("trade_date", ascending=False)
        row = basic.iloc[0]
        raw_ff = row.get("free_share")
        if raw_ff is not None and float(raw_ff) > 0:
            free_float_shares = float(raw_ff) * _WAN_SHARES
        else:
            raw_fl = row.get("float_share")
            if raw_fl is not None and float(raw_fl) > 0:
                free_float_shares = float(raw_fl) * _WAN_SHARES

    rows: list[dict[str, Any]] = []
    sorted_df = df.sort_values("trade_date", ascending=True)
    for _, r in sorted_df.iterrows():
        rows.append(
            {
                "trade_date": str(r.get("trade_date", "")),
                "buy_elg_vol": float(r.get("buy_elg_vol") or 0),
                "sell_elg_vol": float(r.get("sell_elg_vol") or 0),
                "buy_lg_vol": float(r.get("buy_lg_vol") or 0),
                "sell_lg_vol": float(r.get("sell_lg_vol") or 0),
                "buy_md_vol": float(r.get("buy_md_vol") or 0),
                "sell_md_vol": float(r.get("sell_md_vol") or 0),
                "buy_sm_vol": float(r.get("buy_sm_vol") or 0),
                "sell_sm_vol": float(r.get("sell_sm_vol") or 0),
                "net_mf_vol": float(r.get("net_mf_vol") or 0),
            }
        )

    last_date = str(sorted_df.iloc[-1].get("trade_date", ""))
    return {
        "moneyflow_rows": rows,
        "free_float_shares": free_float_shares,
        "last_update_date": last_date,
        "ts_code": ts_code,
    }


def _smart_net_lots(row: dict[str, Any]) -> float:
    buy = float(row.get("buy_elg_vol") or 0) + float(row.get("buy_lg_vol") or 0)
    sell = float(row.get("sell_elg_vol") or 0) + float(row.get("sell_lg_vol") or 0)
    return buy - sell


def _retail_net_lots(row: dict[str, Any]) -> float:
    buy = float(row.get("buy_md_vol") or 0) + float(row.get("buy_sm_vol") or 0)
    sell = float(row.get("sell_md_vol") or 0) + float(row.get("sell_sm_vol") or 0)
    return buy - sell


def compute_smart_money_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    """T1 Smart Money Delta：近 3 交易日主力净量 / 自由流通股本。"""
    rows = list(payload.get("moneyflow_rows") or [])
    if len(rows) < 3:
        raise ValueError(f"moneyflow 行数不足 3（实际 {len(rows)}）")

    tail = rows[-3:]
    smart_net_lots = sum(_smart_net_lots(r) for r in tail)
    retail_net_lots = sum(_retail_net_lots(r) for r in tail)
    smart_net_shares = smart_net_lots * _LOT_SIZE
    retail_net_shares = retail_net_lots * _LOT_SIZE

    free_float = payload.get("free_float_shares")
    if free_float is None or float(free_float) <= 0:
        raise ValueError("自由流通股本缺失或无效")

    free_float_f = float(free_float)
    value_pct = round(smart_net_shares / free_float_f * 100, 4)
    direction = "净流入" if value_pct >= 0 else "净流出"
    abs_pct = abs(value_pct)
    last_date = payload.get("last_update_date") or tail[-1].get("trade_date", "")

    return {
        "indicator_name": "L2主力大单资金流向",
        "value_pct": value_pct,
        "calculation_logic": "Sum(近3日大单+特大单净买入量) / 自由流通股本",
        "fact_statement": (
            f"近 3 个交易日内，大单与特大单（主力资金）累计{direction}"
            f"占自由流通盘的 {abs_pct:.2f}%。"
        ),
        "raw_metrics": {
            "3d_smart_money_net_vol": smart_net_shares,
            "3d_retail_net_vol": retail_net_shares,
            "free_float_shares": free_float_f,
            "last_update_date": last_date,
        },
    }
