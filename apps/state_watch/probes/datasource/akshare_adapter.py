"""AKShare 适配器（财务指标；无网络或解析失败时返回 unknown，禁止 stub 假数）。

主 API（2026-05）：``stock_financial_abstract(symbol)``
  → 东财财务摘要宽表；``stock_financial_analysis_indicator`` 在部分环境已失效
  → 启动期 10 只 active 标的实测 ≥4/6 metric

字段映射（P1 六 metric）：
  revenue_yoy     ← 营业总收入增长率(%) / 100
  net_profit_yoy  ← 归属母公司净利润增长率(%) / 100
  gross_margin    ← 毛利率(%) / 100
  operating_cf    ← 每股经营现金流(元)  # per-share，单位元/股
  debt_ratio      ← 资产负债率(%) / 100
  roe             ← 净资产收益率(ROE)(%)   # 季度 ROE 原值，非年化

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import akshare as ak  # type: ignore

    _AKSHARE_OK = True
except Exception as _e:
    logger.warning("akshare 不可用: %s", _e)
    ak = None  # type: ignore
    _AKSHARE_OK = False


@dataclass
class FinancialSnapshot:
    symbol: str
    report_date: str
    revenue: float            # 绝对值（stub 保留；akshare 指标表无绝对营收，置 0.0）
    revenue_yoy: float        # 主营收入同比增长率（小数，如 0.136 = 13.6%）
    net_profit: float         # 绝对值（stub 保留；置 0.0）
    net_profit_yoy: float     # 净利润增长率（小数）
    gross_margin: float       # 销售毛利率（小数）；NaN 时置 0.0
    operating_cf: float       # 每股经营性现金流（元/股）
    debt_ratio: float         # 资产负债率（小数）
    roe: float                # 净资产收益率（%，季度值，未年化）

    # 采集元数据
    coverage: float = 1.0    # 非 None metric 数 / 6
    source: str = "akshare"


def _nan_to_none(v: object) -> Optional[float]:
    """把 NaN / None 统一映射为 None，正常浮点数保留。"""
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _pct_to_ratio(v: object) -> Optional[float]:
    """百分比 → 小数（50.0 → 0.5），NaN → None。"""
    f = _nan_to_none(v)
    return None if f is None else f / 100.0


def _resolve_gross_margin(row) -> Optional[float]:
    """毛利率多列 fallback：销售毛利率 → 主营业务利润率 → 销售净利率。"""
    for col in ("销售毛利率(%)", "主营业务利润率(%)", "销售净利率(%)"):
        val = _pct_to_ratio(row.get(col))
        if val is not None:
            return val
    return None


# P1 摘要表指标名（按优先级）
_METRIC_REVENUE_YOY = ("营业总收入增长率",)
_METRIC_NET_PROFIT_YOY = ("归属母公司净利润增长率", "净利润增长率")
_METRIC_GROSS_MARGIN = ("毛利率",)
_METRIC_OPERATING_CF = ("每股经营现金流",)
_METRIC_DEBT_RATIO = ("资产负债率",)
_METRIC_ROE = ("净资产收益率(ROE)", "净资产收益率")


def _period_columns(df: pd.DataFrame) -> list[str]:
    """除 选项/指标 外的报告期列，按时间降序。"""
    cols = [c for c in df.columns if c not in ("选项", "指标")]
    return sorted(cols, reverse=True)


def _format_report_date(period: str) -> str:
    """20251231 → 2025-12-31。"""
    s = str(period).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _lookup_metric(df: pd.DataFrame, names: tuple[str, ...]) -> Optional[pd.Series]:
    for name in names:
        mask = df["指标"].astype(str).str.strip() == name
        rows = df.loc[mask]
        if not rows.empty:
            return rows.iloc[0]
    for name in names:
        mask = df["指标"].astype(str).str.contains(name, na=False, regex=False)
        rows = df.loc[mask]
        if not rows.empty:
            return rows.iloc[0]
    return None


def _cell_value(row: pd.Series, period: str) -> Optional[float]:
    if period not in row.index:
        return None
    return _nan_to_none(row.get(period))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def fetch_financial_snapshot(symbol: str) -> FinancialSnapshot:
    """获取标的最新财务快照；优先 akshare，失败时返回 source=unknown（coverage=0）。"""
    if _AKSHARE_OK:
        snap = _fetch_from_akshare(symbol)
        if snap is not None:
            return snap

    logger.warning("akshare 不可用或无数据: %s，返回 unknown（no-mock-policy）", symbol)
    return FinancialSnapshot(
        symbol=symbol, report_date="UNKNOWN",
        revenue=0.0, revenue_yoy=0.0, net_profit=0.0, net_profit_yoy=0.0,
        gross_margin=0.0, operating_cf=0.0, debt_ratio=0.0, roe=0.0,
        coverage=0.0, source="unknown",
    )


def _fetch_from_akshare(symbol: str) -> Optional[FinancialSnapshot]:
    """优先 ``stock_financial_abstract``；旧 indicator API 仍作次选。"""
    snap = _fetch_from_abstract(symbol)
    if snap is not None:
        return snap
    return _fetch_from_indicator_legacy(symbol)


def _fetch_from_abstract(symbol: str) -> Optional[FinancialSnapshot]:
    """东财财务摘要宽表（启动期主路径）。"""
    try:
        df = ak.stock_financial_abstract(symbol=symbol)
        if df is None or df.empty or "指标" not in df.columns:
            logger.warning("akshare abstract 返回空: %s", symbol)
            return None

        periods = _period_columns(df)
        if not periods:
            return None

        report_date = "UNKNOWN"
        revenue_yoy = net_profit_yoy = gross_margin = operating_cf = debt_ratio = roe = None

        for period in periods:
            ry = _lookup_metric(df, _METRIC_REVENUE_YOY)
            npy = _lookup_metric(df, _METRIC_NET_PROFIT_YOY)
            gm_row = _lookup_metric(df, _METRIC_GROSS_MARGIN)
            cf_row = _lookup_metric(df, _METRIC_OPERATING_CF)
            dr_row = _lookup_metric(df, _METRIC_DEBT_RATIO)
            roe_row = _lookup_metric(df, _METRIC_ROE)

            revenue_yoy = _pct_to_ratio(_cell_value(ry, period)) if ry is not None else None
            net_profit_yoy = _pct_to_ratio(_cell_value(npy, period)) if npy is not None else None
            gross_margin = _pct_to_ratio(_cell_value(gm_row, period)) if gm_row is not None else None
            operating_cf = _cell_value(cf_row, period) if cf_row is not None else None
            debt_ratio = _pct_to_ratio(_cell_value(dr_row, period)) if dr_row is not None else None
            roe = _cell_value(roe_row, period) if roe_row is not None else None

            fields = [revenue_yoy, net_profit_yoy, gross_margin, operating_cf, debt_ratio, roe]
            if sum(1 for v in fields if v is not None) >= 2:
                report_date = _format_report_date(period)
                break

        fields = [revenue_yoy, net_profit_yoy, gross_margin, operating_cf, debt_ratio, roe]
        non_null = sum(1 for v in fields if v is not None)
        if non_null < 2:
            logger.warning("abstract 数据过少（%d/6），降级: %s", non_null, symbol)
            return None

        return FinancialSnapshot(
            symbol=symbol,
            report_date=report_date,
            revenue=0.0,
            revenue_yoy=revenue_yoy or 0.0,
            net_profit=0.0,
            net_profit_yoy=net_profit_yoy or 0.0,
            gross_margin=gross_margin or 0.0,
            operating_cf=operating_cf or 0.0,
            debt_ratio=debt_ratio or 0.0,
            roe=roe or 0.0,
            coverage=non_null / 6,
            source="akshare_abstract",
        )
    except Exception as exc:
        logger.warning("akshare abstract 失败: symbol=%s err=%s", symbol, exc)
        return None


def _fetch_from_indicator_legacy(symbol: str) -> Optional[FinancialSnapshot]:
    """旧版 indicator API（部分环境已失效，保留作次选）。"""
    try:
        df = ak.stock_financial_analysis_indicator(symbol=symbol, start_year="2023")
        if df is None or df.empty:
            return None

        row = df.iloc[0]
        report_date = str(row.get("日期", "UNKNOWN"))
        revenue_yoy = _pct_to_ratio(row.get("主营业务收入增长率(%)"))
        net_profit_yoy = _pct_to_ratio(row.get("净利润增长率(%)"))
        gross_margin = _resolve_gross_margin(row)
        operating_cf = _nan_to_none(row.get("每股经营性现金流(元)"))
        debt_ratio = _pct_to_ratio(row.get("资产负债率(%)"))
        roe = _nan_to_none(row.get("净资产收益率(%)"))

        fields = [revenue_yoy, net_profit_yoy, gross_margin, operating_cf, debt_ratio, roe]
        non_null = sum(1 for v in fields if v is not None)
        if non_null < 2:
            return None

        return FinancialSnapshot(
            symbol=symbol,
            report_date=report_date,
            revenue=0.0,
            revenue_yoy=revenue_yoy or 0.0,
            net_profit=0.0,
            net_profit_yoy=net_profit_yoy or 0.0,
            gross_margin=gross_margin or 0.0,
            operating_cf=operating_cf or 0.0,
            debt_ratio=debt_ratio or 0.0,
            roe=roe or 0.0,
            coverage=non_null / 6,
            source="akshare_indicator",
        )
    except Exception as exc:
        logger.warning("akshare indicator 失败: symbol=%s err=%s", symbol, exc)
        return None
