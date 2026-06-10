"""fii_twse_cloud 常量 · 词表/板块白名单/基准权重。

[Ref: 28_ §2.2 fii_twse_cloud · T0/T1 强依赖拆解]
"""
from __future__ import annotations

from typing import Any

# 官方四大产品线（禁止代词置换）
OFFICIAL_SEGMENTS: tuple[dict[str, str], ...] = (
    {
        "key": "cloud",
        "zh": "云端网路产品",
        "en": "Cloud and Networking",
        "aliases": ("云端网路", "云端网络", "雲端網路", "云端网络", "Cloud and Networking"),
    },
    {
        "key": "consumer",
        "zh": "消费智能产品",
        "en": "Smart Consumer Electronics",
        "aliases": ("消费智能", "消費智能", "Smart Consumer", "消费电子", "消費性電子"),
    },
    {
        "key": "computing",
        "zh": "电脑终端产品",
        "en": "Computing Products",
        "aliases": ("电脑终端", "電腦終端", "Computing Products"),
    },
    {
        "key": "components",
        "zh": "元件及其他产品",
        "en": "Components and Others",
        "aliases": ("元件及其他", "元件及其他产品", "Components and Others"),
    },
)

# 鸿海历史公关词汇 → MoM/YoY 边界（回测校准 · 2023–2025 样本）
HISTORICAL_TERM_DICTIONARY: dict[str, dict[str, Any]] = {
    "持平": {"mom_pct": [-3.0, 3.0], "yoy_pct": [-3.0, 3.0]},
    "略增": {"mom_pct": [0.0, 5.0], "yoy_pct": [0.0, 5.0]},
    "略减": {"mom_pct": [-5.0, 0.0], "yoy_pct": [-5.0, 0.0]},
    "显著成长": {"mom_pct": [5.0, 15.0], "yoy_pct": [5.0, 15.0]},
    "显著衰退": {"mom_pct": [-15.0, -5.0], "yoy_pct": [-15.0, -5.0]},
    "强劲成长": {"mom_pct": [10.0, 100.0], "yoy_pct": [10.0, 100.0]},
    "双位数成长": {"mom_pct": [10.0, 100.0], "yoy_pct": [10.0, 100.0]},
    "双位数": {"mom_pct": [10.0, 100.0], "yoy_pct": [10.0, 100.0]},
    "年对年则达到强劲成长": {"yoy_pct": [10.0, 100.0]},
    "季对季将显著成长": {"mom_pct": [5.0, 15.0]},
    # 繁体 OCR 同义词
    "強勁成長": {"mom_pct": [10.0, 100.0], "yoy_pct": [10.0, 100.0]},
    "顯著成長": {"mom_pct": [5.0, 15.0], "yoy_pct": [5.0, 15.0]},
    "略為衰退": {"mom_pct": [-5.0, 0.0], "yoy_pct": [-5.0, 0.0]},
    "略为衰退": {"mom_pct": [-5.0, 0.0], "yoy_pct": [-5.0, 0.0]},
}

# Q1 2025 财报披露四大板块占比（% · 最近一次详细分部 · 公开 IR）
SEGMENT_BASELINE_WEIGHTS_LAST_Q: dict[str, float] = {
    "cloud": 22.0,
    "consumer": 47.0,
    "computing": 8.0,
    "components": 23.0,
}

TWSE_OPENAPI_MONTHLY = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
FINMIND_MONTHLY = "https://api.finmindtrade.com/api/v4/data"
HONHAI_MONTHLY_CATEGORY_PATH = "/zh-tw/press-center/press-releases/latest-news/2693"

PROBE_KEY = "fii_twse_cloud"
DEFAULT_TWSE_CODE = "2317"
