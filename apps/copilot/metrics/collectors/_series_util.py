"""Z0 T0 历史序列工具 · 对齐 z0_history_contract.yaml。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


def metric_ok(
    metric_id: str,
    data: dict[str, Any],
    source: str,
    *,
    series: list[dict[str, Any]] | None = None,
    history_required: str | None = None,
    min_points: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "ok",
        "metric_id": metric_id,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "source": source,
    }
    if series is not None:
        payload["series"] = series
        payload["series_count"] = len(series)
    if history_required:
        payload["history_required"] = history_required
    if min_points is not None:
        payload["min_points"] = min_points
        if series is not None and len(series) < min_points:
            payload["history_gap"] = f"仅 {len(series)} 点，期望 ≥{min_points}"
    return payload


def metric_err(metric_id: str, detail: str) -> dict[str, Any]:
    return {"status": "error", "metric_id": metric_id, "detail": detail}


def df_to_series(
    df: pd.DataFrame,
    *,
    period_col: str,
    fields: dict[str, str],
    tail: int | None = None,
    ascending: bool = True,
) -> list[dict[str, Any]]:
    """将 DataFrame 转为 [{period, ...fields}]。"""
    if df is None or df.empty or period_col not in df.columns:
        return []
    work = df.copy()
    work = work.sort_values(period_col, ascending=ascending)
    if tail:
        work = work.tail(tail)
    out: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        item: dict[str, Any] = {"period": str(row.get(period_col, ""))}
        for out_key, col in fields.items():
            val = row.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            try:
                item[out_key] = float(val)
            except (TypeError, ValueError):
                item[out_key] = str(val)
        if item.get("period"):
            out.append(item)
    return out
