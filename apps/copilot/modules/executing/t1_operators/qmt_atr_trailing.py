"""#15 qmt_atr_trailing · T1 五步法硬算算子。

[Ref: 28_ §2.2.3]
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from apps.copilot.modules.executing.collectors.daily_bars import DailyBarRow

ATR_WINDOW = 20
MIN_BARS_FOR_T1 = ATR_WINDOW + 1
SOURCE_PG = "PG executing_daily_bars · tencent_fqkline"
# 算子内部标记；portfolio 展示源见 indicator_nodes.SOURCE_INTRADAY_TICK
SOURCE_INTRADAY = "intraday_redis_draft"

logger = logging.getLogger(__name__)

INDICATOR_KEY = "qmt_atr_trailing"
ATR_FLOOR = 0.01


class AtrTrailingError(Exception):
    """防呆校验失败 · 禁止输出错误信号。"""


def rows_to_dataframe(rows: list[DailyBarRow]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    data = {
        "open": [r.open for r in rows],
        "high": [r.high for r in rows],
        "low": [r.low for r in rows],
        "close": [r.close for r in rows],
        "volume": [r.volume for r in rows],
    }
    idx = pd.DatetimeIndex([pd.Timestamp(r.trade_date) for r in rows])
    return pd.DataFrame(data, index=idx).sort_index()


def _normalize_entry_date(entry_date: date | str | None) -> date:
    if entry_date is None:
        raise AtrTrailingError("建仓日缺失 · 须在 user_positions.opened_at 配置")
    if isinstance(entry_date, str):
        return date.fromisoformat(entry_date[:10])
    return entry_date


def process_qmt_atr_trailing(
    df_250d: pd.DataFrame,
    entry_date: date | str,
    *,
    source: str,
    atr_window: int = ATR_WINDOW,
) -> dict[str, Any]:
    """
    T1 层 qmt_atr_trailing 核心算子（五步法）。

    1. 时间正序 + entry_date 窗内防呆
    2. True Range（含跳空）→ 末 atr_window 日均值 = ATR20
    3. 建仓日后峰值 peak_high
    4. (peak_high - current) / ATR20
    5. 标准 T1 JSON 契约
    """
    if df_250d.empty:
        raise AtrTrailingError("K 线 DataFrame 为空")

    entry = _normalize_entry_date(entry_date)
    df = df_250d.sort_index()
    if len(df) < atr_window:
        raise AtrTrailingError(
            f"K 线不足 {atr_window} 根（got {len(df)}）· 无法计算 ATR{atr_window}"
        )

    min_d = df.index.min().date()
    max_d = df.index.max().date()
    if entry < min_d or entry > max_d:
        raise AtrTrailingError(
            f"建仓日 {entry.isoformat()} 超出 K 线范围 [{min_d}, {max_d}]"
        )

    prev_close = df["close"].shift(1)
    tr = np.maximum.reduce(
        [
            df["high"].to_numpy() - df["low"].to_numpy(),
            np.abs(df["high"].to_numpy() - prev_close.to_numpy()),
            np.abs(df["low"].to_numpy() - prev_close.to_numpy()),
        ]
    )
    df = df.assign(tr=tr)
    tail_tr = df["tr"].iloc[-atr_window:]
    if tail_tr.isna().any():
        raise AtrTrailingError(f"末 {atr_window} 日 TR 含空值 · 检查序列连续性")
    atr_20 = float(tail_tr.mean())

    entry_ts = pd.Timestamp(entry)
    df_holding = df[df.index >= entry_ts]
    if df_holding.empty:
        raise AtrTrailingError(
            f"建仓日 {entry.isoformat()} 在持仓窗内无 K 线 · 请检查底库长度"
        )

    peak_high = float(df_holding["high"].max())
    current_price = float(df["close"].iloc[-1])
    as_of = df.index[-1].date().isoformat()

    if atr_20 < ATR_FLOOR:
        atr_multiple = 0.0
    else:
        atr_multiple = (peak_high - current_price) / atr_20

    value = round(atr_multiple, 2)
    logic = (
        f"(建仓后最高价 {peak_high:.2f} - 当前价 {current_price:.2f}) "
        f"/ 近{atr_window}日ATR {atr_20:.2f}"
    )
    fact = (
        f"当前价格距离建仓以来的绝对峰值，已回撤 {value} 倍 ATR。"
    )

    return {
        "indicator_key": INDICATOR_KEY,
        "value": value,
        "source": source,
        "calculation_logic": logic,
        "fact_statement": fact,
        "atr20": round(atr_20, 4),
        "peak_price": round(peak_high, 4),
        "current": round(current_price, 4),
        "atr_multiple": round(atr_multiple, 4),
        "bars_count": len(df),
        "as_of": as_of,
        "entry_date_used": entry.isoformat(),
    }


def process_qmt_atr_trailing_from_rows(
    rows: list[DailyBarRow],
    entry_date: date | str | None,
    *,
    source: str,
    atr_window: int = ATR_WINDOW,
) -> dict[str, Any]:
    if len(rows) < MIN_BARS_FOR_T1:
        raise AtrTrailingError(
            f"K 线不足 {MIN_BARS_FOR_T1} 根（got {len(rows)}）· 无法计算 ATR{ATR_WINDOW}"
        )
    df = rows_to_dataframe(rows)
    return process_qmt_atr_trailing(
        df,
        entry_date,  # type: ignore[arg-type]
        source=source,
        atr_window=atr_window,
    )


def compute_atr_trailing_payload(
    rows: list[DailyBarRow],
    *,
    entry_date: date | None = None,
    source: str = SOURCE_PG,
    atr_window: int = ATR_WINDOW,
) -> dict[str, Any] | None:
    """兼容旧调用方；失败返回 None 并打日志。"""
    try:
        return process_qmt_atr_trailing_from_rows(
            rows,
            entry_date,
            source=source,
            atr_window=atr_window,
        )
    except AtrTrailingError as exc:
        logger.warning("qmt_atr_trailing 防呆/算子失败: %s", exc)
        return None
