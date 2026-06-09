"""执行区探针中文简写 · 前端与 T2 展示共用。

[Ref: 28_ §2.0]
"""
from __future__ import annotations

# key → 中文简写（§2.0 JL4 + §2.2～§2.4 Profile JL3）
PROBE_LABELS: dict[str, str] = {
    # --- 601138 工业富联 JL3 ---
    "fii_twse_cloud": "母公司云端营收",
    "fii_odm_direct_ratio": "ODM直供占比",
    "fii_gb200_milestone": "GB200量产节点",
    "fii_gb200_yield": "GB200良率",
    "fii_copper_shfe": "沪铜成本",
    "fii_quanta_share": "广达增速差",
    "fii_raw_inventory": "原材料备料",
    "fii_inventory_turnover": "存货周转",
    "fii_contract_liab": "合同负债",
    "fii_gross_margin": "整体毛利率",
    "fii_ai_margin": "AI服务器毛利",
    "fii_ar_turnover": "应收周转",
    "fii_cfo_health": "经营现金流",
    "fii_labor_auto_capex": "自动化降本",
    "fii_related_pty": "鸿海关联交易",
    "fii_overseas_fdi": "海外建厂投资",
    "fii_apple_base": "消费电子拖累",
    "fii_network_switch": "800G交换机",
    "fii_exchange_rate": "汇率影响",
    "fii_mgmt_stability": "董监高稳定",
    # --- 300502 新易盛 JL3 ---
    "eop_16t_qual": "1.6T送样",
    "eop_dsp_lead": "DSP交期",
    "eop_eml_laser": "激光器供给",
    "eop_client_top2": "前二客户集中度",
    "eop_800g_yield": "800G良率折损",
    "eop_inno_delta": "中际增速差",
    "eop_800g_margin": "800G净利率",
    "eop_siph_ratio": "硅光出货占比",
    "eop_finished_gd": "产成品库存",
    "eop_usd_cny": "汇兑损益",
    "eop_domestic_bid": "国内集采份额",
    "eop_32t_rd": "3.2T研发强度",
    "eop_intangible": "商誉占比",
    "eop_thai_util": "泰国工厂达产",
    # --- 002837 英维克 JL3 ---
    "env_liquid_win_rate": "液冷中标率",
    "env_oem_certs": "原厂认证数",
    "env_al_cu_idx": "铝铜成本指数",
    "env_coolant_ratio": "冷却液耗材",
    "env_margin_pass": "成本转嫁能力",
    "env_cdu_share": "CDU市占率",
    "env_ess_growth": "储能温控",
    "env_b2b_aging": "长账龄应收",
    "env_cfo_to_net": "经营现金流",
    "env_warranty": "售后准备金",
    "env_inv_structure": "存货结构",
    "env_immersion_rd": "浸没式液冷",
    "env_client_top5": "前五大客户",
    "env_goodwill_imp": "商誉占比",
    # --- 共享 JL4 ---
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
    "tech_beta_correlation": "板块Beta共振度与解释系数",
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
