"""fii_gb200_milestone_v2 常量 · NPI 状态机 + 影子水位阈值。

[Ref: 28_ §2.2 fii_gb200_milestone · 物理状态机+供应链影子 v2]
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

PROBE_KEY = "fii_gb200_milestone"
CONTRACT_VERSION = "fii_gb200_milestone_deepsea_v1"
INDICATOR_ID = "fii_gb200_milestone_deepsea_v1"
CACHE_GROUP = "fii-cninfo-dynamic"

# 事件文本扫描窗口（日频 · 近 12 个月）
EVENT_LOOKBACK_MONTHS = 12
# Chroma 基准斜率回填（月频 · H100 爬坡对标）
BASELINE_LOOKBACK_MONTHS = 36
ANALYSIS_WINDOW_MONTHS = EVENT_LOOKBACK_MONTHS

# NPI 状态机 · RUMOR→EVT→DVT→PVT→MP（纯语义 · 无硬数字方程）
NPI_STATE_DICTIONARY: dict[str, dict[str, Any]] = {
    "RUMOR": {
        "rank": 0,
        "label_zh": "市场传闻(RUMOR)",
        "trade_posture": "observe_left",
        "terms": ("传闻", "据悉", "市场消息", "RUMOR", "据传"),
    },
    "EVT": {
        "rank": 1,
        "label_zh": "工程验证(EVT)",
        "trade_posture": "observe_left",
        "terms": ("打样", "送样", "小规模验证", "工程验证", "EVT", "样品", "试制", "NPI"),
    },
    "DVT": {
        "rank": 2,
        "label_zh": "设计验证(DVT)",
        "trade_posture": "observe_left",
        "terms": ("设计验证", "DVT", "工程样机", "设计定型", "验证样机"),
    },
    "PVT": {
        "rank": 3,
        "label_zh": "小批量试产(PVT)",
        "trade_posture": "build_base",
        "terms": ("小批量生产", "小批量", "试产", "准量产", "爬坡", "PVT", "试点", "小批", "小量生产"),
    },
    "MP": {
        "rank": 4,
        "label_zh": "大规模量产(MP)",
        "trade_posture": "right_side_full",
        "terms": (
            "规模交付",
            "批量出货",
            "量产",
            "批量交付",
            "正式交付",
            "Mass Production",
            "MP",
            "规模出货",
            "顺利开启规模交付",
            "顺利进入规模",
        ),
    },
}

PRODUCT_LIFECYCLE_DICTIONARY = NPI_STATE_DICTIONARY

LIFECYCLE_ORDER: tuple[str, ...] = ("RUMOR", "EVT", "DVT", "PVT", "MP")

EXPECTED_SEGMENTS: tuple[str, ...] = (
    "GB200 NVL72/36 整机柜",
    "GB200 NVL36 整机柜",
    "传统AI服务器 (H100/H200)",
)

ANNOUNCEMENT_KEYWORDS: tuple[str, ...] = (
    "GB200",
    "NVL72",
    "NVL36",
    "Blackwell",
    "智算机柜",
    "高密度机柜",
    "新一代",
    "AI服务器",
    "液冷",
    "规模交付",
    "量产",
    "批量交付",
    "批量出货",
)

PRODUCT_SEGMENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"GB200|NVL72|NVL36|Blackwell", re.I), "GB200 NVL72/36 整机柜"),
    (
        re.compile(r"最新一代.{0,12}(?:高密度)?智算机柜|高密度智算机柜|新一代.{0,8}机柜"),
        "GB200 NVL72/36 整机柜",
    ),
    (re.compile(r"H100|H200|Hopper", re.I), "传统AI服务器 (H100/H200)"),
)

FUZZY_PR_TERMS: tuple[str, ...] = (
    "顺利开启规模交付",
    "顺利进入规模",
    "最新一代",
    "高密度智算机柜",
    "规模交付",
    "显著增量",
    "顺利推进",
)

DEFAULT_UPSTREAM_BOTTLENECK_DATE = "2024-10-01"

CHROMA_TWSE_CODE = "2360"
CHROMA_MOM_SURGE_PCT = 20.0
RAW_MATERIALS_QOQ_SURGE_PCT = 30.0

PROXY_SPIKE_THRESHOLD: dict[str, Any] = {
    "chroma_mom_pct": CHROMA_MOM_SURGE_PCT,
    "raw_materials_qoq_pct": RAW_MATERIALS_QOQ_SURGE_PCT,
    "label_zh": f"Chroma MoM>{CHROMA_MOM_SURGE_PCT:.0f}% 或 原材料 QoQ>{RAW_MATERIALS_QOQ_SURGE_PCT:.0f}%",
}

MEXICO_FDI_KEYWORDS: tuple[str, ...] = (
    "墨西哥",
    "MEXICO",
    "FII AMC",
    "增资",
    "投资",
    "AI服务器",
    "扩产",
)


def upstream_bottleneck_date() -> str:
    return os.environ.get(
        "EXECUTING_GB200_UPSTREAM_BOTTLENECK_DATE",
        DEFAULT_UPSTREAM_BOTTLENECK_DATE,
    ).strip()[:10]


_CST = timezone(timedelta(hours=8))


def _lookback_days(months: int) -> int:
    return months * 31


def event_window_start(*, ref: datetime | None = None) -> datetime:
    end = ref or datetime.now(_CST)
    return end - timedelta(days=_lookback_days(EVENT_LOOKBACK_MONTHS))


def baseline_window_start(*, ref: datetime | None = None) -> datetime:
    end = ref or datetime.now(_CST)
    return end - timedelta(days=_lookback_days(BASELINE_LOOKBACK_MONTHS))


def analysis_window_start(*, ref: datetime | None = None) -> datetime:
    return event_window_start(ref=ref)


def analysis_window_end(*, ref: datetime | None = None) -> datetime:
    return ref or datetime.now(_CST)


def is_within_event_window(date_str: str | None, *, ref: datetime | None = None) -> bool:
    if not date_str or len(str(date_str).strip()) < 10:
        return True
    try:
        d = datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return d >= event_window_start(ref=ref).date()


is_within_analysis_window = is_within_event_window


def event_window_meta(*, ref: datetime | None = None) -> dict[str, Any]:
    start = event_window_start(ref=ref)
    end = analysis_window_end(ref=ref)
    return {
        "months": EVENT_LOOKBACK_MONTHS,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "label_zh": f"近{EVENT_LOOKBACK_MONTHS}个月",
        "cadence": "daily_event",
    }


def baseline_window_meta(*, ref: datetime | None = None) -> dict[str, Any]:
    start = baseline_window_start(ref=ref)
    end = analysis_window_end(ref=ref)
    return {
        "months": BASELINE_LOOKBACK_MONTHS,
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "label_zh": f"近{BASELINE_LOOKBACK_MONTHS}个月基准",
        "cadence": "monthly_chroma_baseline",
    }


def analysis_window_meta(*, ref: datetime | None = None) -> dict[str, Any]:
    return event_window_meta(ref=ref)
