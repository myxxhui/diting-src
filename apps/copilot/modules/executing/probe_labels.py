"""执行区探针中文简写 · 前端与 T2 展示共用。

[Ref: 28_ §2.0]
"""
from __future__ import annotations

# key → 中文简写（§2.0 一句话压缩）
PROBE_LABELS: dict[str, str] = {
    "nvda_gpu_leadtime": "GPU交期",
    "tsmc_cowos_capacity": "封装产能",
    "parent_honhai_revenue": "母公司营收",
    "cloud_capex_consensus": "四云Capex",
    "smci_quanta_share": "同业份额",
    "gb200_iteration_node": "技术迭代",
    "inventory_turnover": "存货周转",
    "contract_liabilities": "合同负债",
    "copper_cost_pressure": "铜价压力",
    "cpi_ppi_spread": "通胀剪刀",
    "exchange_rate_impact": "汇率影响",
    "mgmt_and_core_team": "董监高",
    "related_party_trans": "关联交易",
    "gross_margin_trend": "毛利率",
    "qmt_atr_trailing": "ATR止盈",
    "volume_price_div": "量价背离",
    "smart_money_flow": "L2主力大单",
    "level2_super_order": "超大单",
    "margin_short_skew": "融资融券",
    "turnover_acceleration": "换手加速",
    "block_trade_discount": "大宗折价",
    "retail_concentration": "散户接盘",
    "insider_sell_actual": "减持实况",
    "etf_redemption_impact": "ETF申赎",
    "tech_beta_correlation": "板块β",
}

# key → Opus/名牌全称（portfolio_signals.indicator_name）
PROBE_INDICATOR_NAMES: dict[str, str] = {
    "qmt_atr_trailing": "动态ATR追踪止盈",
    "volume_price_div": "15分钟级高位量价背离",
    "smart_money_flow": "L2主力大单资金流向",
    "level2_super_order": "L2特大单净动能历史分位",
    "margin_short_skew": "两融杠杆倾斜度历史分位",
    "turnover_acceleration": "自由换手率异动倍数",
    "block_trade_discount": "大宗交易加权折价与盘口冲击",
    "retail_concentration": "户均持股集中度与筹码分散检测",
    "insider_sell_actual": "核心内部人90日实际净减持当量",
    "etf_redemption_impact": "核心ETF被动资金冲击当量",
}


def probe_indicator_name(key: str) -> str:
    k = (key or "").strip()
    return PROBE_INDICATOR_NAMES.get(k, probe_label(k))


def probe_label(key: str) -> str:
    k = (key or "").strip()
    return PROBE_LABELS.get(k, k)


def probe_title(key: str) -> str:
    """展示用：中文简写 + 技术键（小字）。"""
    k = (key or "").strip()
    zh = probe_label(k)
    if zh == k:
        return k
    return f"{zh}"
