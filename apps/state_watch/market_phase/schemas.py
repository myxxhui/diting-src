"""市场阶段分类器 schema.

[Ref: 03_/03_维度三/.../step_09 §7.1-A]
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class MarketPhase(str, enum.Enum):
    CONCEPT = "concept"
    EXPECTATION = "expectation"
    REALIZATION = "realization"
    EXHAUSTION = "exhaustion"


@dataclass
class PhaseSignals:
    """分类器输入快照."""

    symbol: str
    name: str = ""
    pct_chg_1d: float | None = None
    pct_chg_3d: float | None = None
    pct_chg_5d: float | None = None
    pct_chg_30d: float | None = None
    pct_chg_60d: float | None = None
    volume_ratio_5d: float | None = None
    price_below_ma10: bool | None = None
    media_news_count_7d: int = 0
    phys_probe_alerts_active: int = 0
    has_q_report_released: bool = False
    has_pre_announce_released: bool = False
    has_major_contract: bool = False
    no_announcement_positive: bool = True
    post_realization_days: int | None = None
    insufficient_price: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class ClassificationResult:
    symbol: str
    market_phase: MarketPhase
    confidence: float
    reasoning_tags: list[str]
    rule_signals: dict[str, Any]
    classifier_version: str = "rule_v1"
    phase_unstable: bool = False
