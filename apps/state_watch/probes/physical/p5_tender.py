"""P5 招标物理量探针.

数据源：cryo_guard.announcements（ann_type='ccgp' 或 title 含招标关键词）
启动期行为：
  - 若 ccgp 公告通道未就绪（announcements 中无 ccgp/招标 类型数据）
    → status='upstream_pending'，不写 metric，不阻塞
  - 若有数据则计算 近30天命中条数 / 累计金额(占位) / 月环比，输出三色信号

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §3.5.4.1]
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from apps.cryo_guard.db.sync_session import session_scope
from apps.state_watch.probes.base_probe import BaseProbe, ProbeError

logger = logging.getLogger(__name__)

# ccgp 默认匹配关键词（招标 / 中标 / 政采）
_TENDER_PATTERNS = re.compile(r"招标|中标|政府采购|采购公告|ccgp", re.IGNORECASE)
# 金额正则：匹配"X万元"/"X亿元"
_AMOUNT_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*(万元|亿元|元)", re.IGNORECASE)


def _build_tender_pattern(extra_keywords: tuple[str, ...] | None) -> re.Pattern[str]:
    """合并默认招标关键词 + 监控字典关键词（来自 Architect）。"""
    if not extra_keywords:
        return _TENDER_PATTERNS
    parts = ["招标", "中标", "政府采购", "采购公告", "ccgp"]
    for k in extra_keywords:
        k = (k or "").strip()
        if not k:
            continue
        parts.append(re.escape(k))
    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return re.compile("|".join(seen), re.IGNORECASE)


def _parse_amount_yuan(text: str) -> float | None:
    """从公告文本提取第一个金额（转为元），失败返回 None。"""
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return None
    num_str, unit = m.group(1).replace(",", ""), m.group(2)
    try:
        num = float(num_str)
    except ValueError:
        return None
    if unit == "亿元":
        return num * 1e8
    if unit == "万元":
        return num * 1e4
    return num


def _compute_signal(hit_30d: int, mom_pct: float | None) -> str:
    """三色信号计算（L3 §3.5.4.1 PT2/PT3）。

    green: hit≥3 且 mom≥0
    yellow: hit 1~2 或 mom<0
    red: hit=0（无招标命中）
    """
    if hit_30d == 0:
        return "red"
    if hit_30d >= 3 and (mom_pct is None or mom_pct >= 0):
        return "green"
    return "yellow"


class TenderProbe(BaseProbe):
    """P5 招标物理量探针（24h 节奏，启动期：cryo_guard.announcements 通道）。

    Args:
        monitor_keywords: 可选，来自 Lighthouse-Alpha 监控字典 (MonitorFieldView.keywords)
            的额外匹配关键词；与默认招标关键词 OR 合并。

    [Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_03 §7.1 H]
    [Ref: 03_/_共享规约/20_监控字典规约.md §5.2 消费端时序]
    """

    probe_type = "P5_tender"
    timeout_seconds = 15.0

    def __init__(self, monitor_keywords: tuple[str, ...] | None = None) -> None:
        self.monitor_keywords = monitor_keywords or ()
        self._pattern = _build_tender_pattern(self.monitor_keywords)

    async def _fetch_impl(self, symbol: str) -> dict[str, Any]:
        from apps.cryo_guard.db.models import Announcement
        from sqlalchemy import select

        today = date.today()
        window_start = today - timedelta(days=30)
        prev_window_start = today - timedelta(days=60)

        with session_scope() as session:
            # 查近 30 天公告（ann_type 含 ccgp 或 title 含招标关键词）
            recent_rows = session.scalars(
                select(Announcement).where(
                    Announcement.symbol == symbol,
                    Announcement.ann_date >= window_start,
                )
            ).all()

            prev_rows = session.scalars(
                select(Announcement).where(
                    Announcement.symbol == symbol,
                    Announcement.ann_date >= prev_window_start,
                    Announcement.ann_date < window_start,
                )
            ).all()

        def _is_tender(a: Announcement) -> bool:
            return (a.ann_type or "").lower() == "ccgp" or bool(
                self._pattern.search(a.title or "")
            )

        recent_tender = [a for a in recent_rows if _is_tender(a)]
        prev_tender = [a for a in prev_rows if _is_tender(a)]

        if not recent_rows and not prev_rows:
            # ccgp 通道未就绪，按 L3 §PT1 返回 upstream_pending
            logger.info("P5 symbol=%s ccgp 通道未就绪，标注 upstream_pending", symbol)
            return {"status": "upstream_pending", "probe_id": "P5", "symbol": symbol}

        hit_30d = len(recent_tender)
        hit_prev = len(prev_tender)
        total_amount = sum(
            _parse_amount_yuan(a.title) or 0.0 for a in recent_tender
        )
        evidence_urls = [a.url for a in recent_tender if a.url][:5]

        mom_pct: float | None = None
        if hit_prev > 0:
            mom_pct = round((hit_30d - hit_prev) / hit_prev * 100, 1)

        signal = _compute_signal(hit_30d, mom_pct)
        return {
            "probe_id": "P5",
            "symbol": symbol,
            "status": "ok",
            "physical_signal": signal,
            "tender_hit_count_30d": hit_30d,
            "tender_amount_total_30d": round(total_amount, 2),
            "tender_mom_change_pct": mom_pct,
            "evidence_urls": evidence_urls,
            "monitor_keywords_used": list(self.monitor_keywords),
        }
