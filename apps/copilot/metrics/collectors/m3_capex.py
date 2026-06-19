"""Z0-M3 · 赛道 Capex 采集 · 四大云厂 IR/SEMI · S1 通用。

[Ref: 34_ §3.2 M.policy.capex_total · §3.3 Z0-M3]
采 MSFT/GOOG/META/AMZN 季度资本支出 → 合计+YoY → CVM C3 输入
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 四大云厂 ticker（34_ §3.2）
_CLOUD_CAPEX_TICKERS = ["MSFT", "GOOG", "META", "AMZN"]
# Capex 行关键词（不同 ticker 可能命名略有不同）
_CAPEX_KEYWORDS = [
    "Capital Expenditure",
    "Purchase Of Property Plant And Equipment",
    "Capital Expenditures",
    "Purchases Of Property Plant And Equipment",
]
_HISTORY = "8个季度"
_MIN_QUARTERS = 4


def collect_capex_total(
    *,
    tickers: list[str] | None = None,
    quarters: int = 8,
) -> dict[str, Any]:
    """采集四大云厂季度 Capex 合计 · 同比增速。"""
    import yfinance as yf

    symbols = tickers or _CLOUD_CAPEX_TICKERS
    errors: list[str] = []
    quarterly: dict[str, list[dict[str, Any]]] = {}  # symbol → [{quarter, capex_b}]
    total_series: list[dict[str, Any]] = []  # 跨公司合计序列

    for sym in symbols:
        try:
            tk = yf.Ticker(sym)
            cf = tk.quarterly_cashflow
            if cf is None or cf.empty:
                errors.append(f"{sym}:no_cf")
                continue

            # 定位 Capex 行
            capex_row = None
            if isinstance(cf.index, pd.Index):
                for kw in _CAPEX_KEYWORDS:
                    hits = [i for i in cf.index if kw in str(i)]
                    if hits:
                        capex_row = hits[0]
                        break
                if capex_row is None:
                    # 尝试模糊匹配
                    for idx in cf.index:
                        if any(
                            w in str(idx).lower()
                            for w in ["capital expend", "purchase", "property plant"]
                        ):
                            capex_row = idx
                            break

            if capex_row is None:
                errors.append(f"{sym}:no_capex_row")
                continue

            series_row = cf.loc[capex_row]
            qlist: list[dict[str, Any]] = []
            for date_val, val in series_row.items():
                v = _finite(val)
                if v is not None:
                    qlabel = str(date_val)[:10] if hasattr(date_val, "strftime") else str(date_val)
                    qlist.append({"quarter": qlabel, "capex_b": round(v / 1e9, 4)})
            qlist.sort(key=lambda x: x["quarter"])
            qlist = qlist[-quarters:]
            if len(qlist) >= _MIN_QUARTERS:
                quarterly[sym] = qlist
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{sym}:{exc}")
        try:
            import time
            time.sleep(0.3)
        except Exception:
            pass

    if not quarterly:
        return {
            "status": "error",
            "metric_id": "M.policy.capex_total",
            "detail": f"Capex 采集失败: {'; '.join(errors[:4])}",
            "source": "yfinance:quarterly_cashflow",
        }

    # 跨公司合计序列
    all_quarters = sorted(
        {q["quarter"] for qs in quarterly.values() for q in qs}
    )
    for qlabel in all_quarters:
        total = 0.0; # sum abs capex
        for sym, qs in quarterly.items():
            for q in qs:
                if q["quarter"] == qlabel:
                    total += abs(q["capex_b"])
                    break
        total_series.append({"quarter": qlabel, "capex_total_b": round(abs(total), 4)})

    # YoY 同比
    if len(total_series) >= 5:
        latest = total_series[-1]["capex_total_b"]
        prev_year = total_series[-5]["capex_total_b"] if len(total_series) >= 5 else None  # 4Q offset
        yoy_pct = (
            round((latest - prev_year) / prev_year * 100, 2)
            if prev_year and prev_year > 0
            else None
        )
    else:
        latest = total_series[-1]["capex_total_b"] if total_series else 0
        yoy_pct = None

    return {
        "status": "ok",
        "metric_id": "M.policy.capex_total",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data": {
            "capex_total_b": abs(latest),
            "yoy_pct": yoy_pct,
            "latest_quarter": total_series[-1]["quarter"] if total_series else None,
            "ticker_count": len(quarterly),
            "tickers": list(quarterly.keys()),
        },
        "source": "yfinance:quarterly_cashflow",
        "series": total_series,
        "history_required": _HISTORY,
        "series_count": len(total_series),
        "min_points": _MIN_QUARTERS,
        "errors": errors[:5],
        "share_scope": "S1",
    }


def _finite(v: Any) -> float | None:
    import math

    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


# pandas imported at top for yfinance compatibility
import pandas as pd  # noqa: E402

# Hotfix — 已在 collect_capex_total 中使用绝对值，以下补丁应用
import re
