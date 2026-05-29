"""N2 feature_calculator — 6 类粉饰特征公式计算。

6 类特征：
  1. 存贷双高（double_high）
  2. 现金流-利润背离（cash_flow_divergence）
  3. 应收异常（ar_abnormal）
  4. 存货积压（inventory_bloat）
  5. 研发资本化突变（rd_cap_surge）
  6. 毛利率异常（gross_margin_anomaly）

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2·N2]
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 阈值配置（可由 configs/financial_fraud_thresholds.yaml 覆盖）
DOUBLE_HIGH_CASH_RATIO = 0.30       # cash / total_assets
DOUBLE_HIGH_DEBT_RATIO = 0.30       # debt / total_assets
CASH_FLOW_DIVERGENCE_RATIO = 0.50   # OCF / NetProfit
AR_ANOMALY_MULTIPLIER = 1.50        # AR_yoy > revenue_yoy × 1.5
INVENTORY_INDUSTRY_MULTIPLIER = 1.50
RD_CAP_SURGE_YOY = 0.30             # 30% 年增
GROSS_MARGIN_ANOMALY_DROP = -0.05   # -5% yoy


def _safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute_features(
    fields: dict,
    prev_fields: Optional[dict] = None,
    industry_median_inventory_ratio: Optional[float] = None,
) -> dict:
    """计算 6 类粉饰特征，返回 feature_dict。

    每类输出：{triggered: bool, value: float|None, note: str}
    [Ref: step_04 §3.5.2·N2]
    """
    features: dict = {}

    cash = fields.get("cash")
    total_assets = fields.get("total_assets")
    total_debt = fields.get("total_debt")
    ar = fields.get("accounts_receivable")
    inventory = fields.get("inventory")
    rd_cap = fields.get("rd_capitalized")
    gross_margin = fields.get("gross_margin")
    ocf = fields.get("operating_cash_flow")
    net_profit = fields.get("net_profit")
    revenue = fields.get("revenue")

    # 1. 存贷双高
    cash_ratio = _safe_div(cash, total_assets)
    debt_ratio = _safe_div(total_debt, total_assets)
    double_high = (
        cash_ratio is not None and cash_ratio > DOUBLE_HIGH_CASH_RATIO and
        debt_ratio is not None and debt_ratio > DOUBLE_HIGH_DEBT_RATIO
    )
    features["double_high"] = {
        "triggered": double_high,
        "value": {"cash_ratio": cash_ratio, "debt_ratio": debt_ratio},
        "note": f"cash/assets={cash_ratio:.2%} debt/assets={debt_ratio:.2%}" if cash_ratio and debt_ratio else "数据缺失",
    }

    # 2. 现金流-利润背离
    ocf_net_ratio = _safe_div(ocf, net_profit)
    cf_diverge = ocf_net_ratio is not None and ocf_net_ratio < CASH_FLOW_DIVERGENCE_RATIO
    features["cash_flow_divergence"] = {
        "triggered": cf_diverge,
        "value": ocf_net_ratio,
        "note": f"OCF/NetProfit={ocf_net_ratio:.2f}" if ocf_net_ratio is not None else "数据缺失",
    }

    # 3. 应收异常（需上期数据）
    ar_abnormal = False
    ar_note = "需上期数据"
    if prev_fields:
        prev_ar = prev_fields.get("accounts_receivable")
        prev_revenue = prev_fields.get("revenue")
        ar_yoy = _safe_div(ar - prev_ar, prev_ar) if ar and prev_ar else None
        revenue_yoy = _safe_div(revenue - prev_revenue, prev_revenue) if revenue and prev_revenue else None
        if ar_yoy is not None and revenue_yoy is not None:
            ar_abnormal = ar_yoy > revenue_yoy * AR_ANOMALY_MULTIPLIER
            ar_note = f"AR_yoy={ar_yoy:.2%} revenue_yoy={revenue_yoy:.2%}"
    features["ar_abnormal"] = {"triggered": ar_abnormal, "value": None, "note": ar_note}

    # 4. 存货积压（需行业中位）
    inventory_ratio = _safe_div(inventory, revenue)
    inv_bloat = False
    inv_note = "需行业中位"
    if inventory_ratio is not None and industry_median_inventory_ratio is not None:
        inv_bloat = inventory_ratio > industry_median_inventory_ratio * INVENTORY_INDUSTRY_MULTIPLIER
        inv_note = f"inv/rev={inventory_ratio:.2%} industry_median={industry_median_inventory_ratio:.2%}"
    features["inventory_bloat"] = {"triggered": inv_bloat, "value": inventory_ratio, "note": inv_note}

    # 5. 研发资本化突变（需上期数据）
    rd_surge = False
    rd_note = "需上期数据"
    if prev_fields and rd_cap is not None:
        prev_rd = prev_fields.get("rd_capitalized")
        if prev_rd and prev_rd > 0:
            rd_yoy = (rd_cap - prev_rd) / prev_rd
            rd_surge = rd_yoy > RD_CAP_SURGE_YOY
            rd_note = f"rd_cap_yoy={rd_yoy:.2%}"
    features["rd_cap_surge"] = {"triggered": rd_surge, "value": None, "note": rd_note}

    # 6. 毛利率异常（需上期数据）
    gm_anomaly = False
    gm_note = "需上期数据"
    if prev_fields and gross_margin is not None:
        prev_gm = prev_fields.get("gross_margin")
        if prev_gm is not None:
            gm_yoy = gross_margin - prev_gm
            gm_anomaly = gm_yoy < GROSS_MARGIN_ANOMALY_DROP
            gm_note = f"gm_yoy={gm_yoy:.2%}"
    features["gross_margin_anomaly"] = {"triggered": gm_anomaly, "value": gross_margin, "note": gm_note}

    triggered_count = sum(1 for v in features.values() if v.get("triggered"))
    logger.info("[N2] features computed: triggered=%d/%d", triggered_count, len(features))
    return features
