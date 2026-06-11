"""fii_odm_direct_ratio 常量 · 客户形态字典 / 模糊词边界。

[Ref: 28_ §2.2 fii_odm_direct_ratio]
"""
from __future__ import annotations

PROBE_KEY = "fii_odm_direct_ratio"

# 启动期默认基数（无上一季 T1 快照时 · 2023 产业突变前 OEM 通道仍占主导）
DEFAULT_HISTORICAL_RATIO_BASELINE_PCT = 50.0

# 传统 OEM 通道宏观衰退上限（Dell/HPE 等非 AI 服务器 · P0 可 env 覆盖）
DEFAULT_TRADITIONAL_OEM_CAPEX_PROXY_PCT = -15.0

# 「其他及边缘」占云业务比例上限
DEFAULT_OTHER_SEGMENT_MAX_PCT = 15.0

OFFICIAL_SEGMENTS: tuple[dict[str, str], ...] = (
    {"key": "odm_direct", "zh": "ODM直供业务", "en": "CSP Direct"},
    {"key": "traditional_oem", "zh": "传统OEM业务", "en": "Brand Servers"},
    {"key": "other", "zh": "其他及边缘网络产品", "en": "Other"},
)

CUSTOMER_ARCHETYPE_DICTIONARY: dict[str, dict[str, str]] = {
    "csp_direct": {
        "zh": "直供 CSP 客户",
        "examples": "北美云巨头、Tier1 互联网厂",
    },
    "traditional_oem": {
        "zh": "传统 OEM 客户",
        "examples": "戴尔、惠普等品牌服务器厂",
    },
}

# 业绩会 QA 模糊词 → 数学边界提示（T1 solver 消费）
FUZZY_TERM_CONSTRAINTS: dict[str, dict[str, float | str]] = {
    "占比显著提升": {"delta_baseline_ppt": 5.0},
    "进一步提升": {"delta_baseline_ppt": 5.0},
    "绝对主导": {"min_ratio_pct": 50.0, "ranking": "odm_gt_oem"},
    "主导地位": {"min_ratio_pct": 50.0, "ranking": "odm_gt_oem"},
    "占据云业务的绝对主导地位": {"min_ratio_pct": 50.0, "ranking": "odm_gt_oem"},
}
