"""P7 产能利用率探针.

数据源：cryo_guard.announcements（业绩说明会纪要 + 投资者关系 Q&A）
方法：正则规则抽取（启动期纯规则；扩展期可接小模型）
降级：
  - 抽取失败 → status='extraction_failed'，不写 metric，不告警
  - 公告为空 → status='no_data'

三色信号（L3 §PP3）：
  green:  capacity_utilization_pct > 90% 且无大扩产（capex 标志）
  yellow: 70% ~ 90%
  red:    < 70% 或 扩产幅度暗示 +50% 产能

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §3.5.4.3]
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from apps.cryo_guard.db.sync_session import session_scope
from apps.state_watch.probes.base_probe import BaseProbe, ProbeError

logger = logging.getLogger(__name__)

# 产能利用率 / 开工率正则（顺序：关键词在前）
# 覆盖：产能利用率/开工率/设备利用率/满产率/满开率/生产利用率/产线开工率
_UTIL_RE = re.compile(
    r"(?:产能利用率|产能利用水平|开工率|产能开工率|产线开工率|设备利用率|满产率|满开率|生产利用率)"
    r"[^0-9（(]*?(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
# 反向措辞：约 XX% 的产能利用 / 达到 XX% 满产
_UTIL_RE_REVERSE = re.compile(
    r"(?:约|达到|达|超过|接近|维持在|保持在)\s*(\d{1,3}(?:\.\d+)?)\s*%"
    r"[^，。\n]{0,20}(?:产能利用|开工|满产|满负荷)",
    re.IGNORECASE,
)
# 大幅扩产信号：新增产能/扩产 + 比例 > 50%
_CAPEX_RE = re.compile(r"(?:新增|扩建|扩产)[^0-9]*?(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)

# 适合 P7 分析的公告类型（可扩展）
_P7_ANN_TYPES = {"performance", "investor_qa", "announcement", "strategic", "earnings"}


def _extract_utilization(text: str) -> float | None:
    """从文本中提取第一个产能利用率数值（%）。

    先用关键词在前的正则，再用反向措辞正则兜底（覆盖"约XX%满产"等句式）。
    """
    for pattern in (_UTIL_RE, _UTIL_RE_REVERSE):
        m = pattern.search(text or "")
        if m:
            try:
                val = float(m.group(1))
                if 0 < val <= 100:
                    return val
            except ValueError:
                continue
    return None


def _has_large_capex(text: str, threshold_pct: float = 50.0) -> bool:
    """检测文本是否有大幅扩产信号（新增产能 > threshold_pct%）。"""
    for m in _CAPEX_RE.finditer(text or ""):
        try:
            if float(m.group(1)) >= threshold_pct:
                return True
        except ValueError:
            continue
    return False


def _compute_signal(util_pct: float | None, large_capex: bool) -> str:
    if util_pct is None:
        return "unknown"
    if util_pct < 70 or large_capex:
        return "red"
    if util_pct >= 90 and not large_capex:
        return "green"
    return "yellow"


class CapacityProbe(BaseProbe):
    """P7 产能利用率探针（季度节奏，启动期：cryo_guard 公告规则抽取）。

    Args:
        monitor_keywords: 可选，来自 Lighthouse-Alpha 监控字典的额外关键词；
            匹配公告标题/正文时与产能利用率正则形成 OR 增强（命中关键词的公告优先送入抽取）。

    [Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §7.1 J]
    [Ref: 03_/_共享规约/20_监控字典规约.md §5.2 消费端时序]
    """

    probe_type = "P7_capacity"
    timeout_seconds = 15.0

    def __init__(self, monitor_keywords: tuple[str, ...] | None = None) -> None:
        self.monitor_keywords = tuple(k for k in (monitor_keywords or ()) if k)

    def _matches_monitor_keywords(self, text: str) -> bool:
        if not self.monitor_keywords:
            return False
        lower = (text or "").lower()
        return any(k.lower() in lower for k in self.monitor_keywords)

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        from apps.cryo_guard.db.models import Announcement
        from sqlalchemy import select

        today = date.today()
        window_start = today - timedelta(days=365)

        with session_scope() as session:
            rows = session.scalars(
                select(Announcement).where(
                    Announcement.symbol == symbol,
                    Announcement.ann_date >= window_start,
                )
            ).all()

        if not rows:
            return {
                "probe_id": "P7",
                "symbol": symbol,
                "status": "no_data",
                "physical_signal": "unknown",
                "note": "近1年无公告数据，不告警",
            }

        # 优先用 P7 友好类型；fallback 用所有公告
        candidates = [r for r in rows if r.ann_type in _P7_ANN_TYPES]
        if not candidates:
            candidates = list(rows)

        # 监控字典关键词加权：命中关键词的公告优先送入抽取（不替换原 fallback）
        sorted_candidates = sorted(candidates, key=lambda a: a.ann_date, reverse=True)
        if self.monitor_keywords:
            keyword_hits = [
                a for a in sorted_candidates
                if self._matches_monitor_keywords((a.title or "") + " " + (a.content or ""))
            ]
            others = [a for a in sorted_candidates if a not in keyword_hits]
            sorted_candidates = keyword_hits + others

        # 逐条尝试抽取，取最近成功值
        util_pct: float | None = None
        large_capex = False
        hit_title = ""
        hit_via_monitor = False
        for ann in sorted_candidates:
            text = (ann.title or "") + " " + (ann.content or "")
            val = _extract_utilization(text)
            if val is not None:
                util_pct = val
                large_capex = _has_large_capex(text)
                hit_title = ann.title or ""
                hit_via_monitor = self._matches_monitor_keywords(text)
                break

        if util_pct is None:
            logger.info("P7 symbol=%s 规则抽取失败（公告 %d 条），标注 extraction_failed", symbol, len(candidates))
            return {
                "probe_id": "P7",
                "symbol": symbol,
                "status": "extraction_failed",
                "physical_signal": "unknown",
                "note": f"近1年 {len(candidates)} 条公告未命中产能利用率模式，不写metric",
                "monitor_keywords_used": list(self.monitor_keywords),
            }

        signal = _compute_signal(util_pct, large_capex)
        return {
            "probe_id": "P7",
            "symbol": symbol,
            "status": "ok",
            "physical_signal": signal,
            "capacity_utilization_pct": util_pct,
            "expansion_capex_announce": large_capex,
            "evidence_title": hit_title,
            "monitor_keywords_used": list(self.monitor_keywords),
            "hit_via_monitor_keyword": hit_via_monitor,
        }
