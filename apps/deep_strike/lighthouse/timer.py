"""The Timer — 三段时间窗口预测（incubation / main_wave / retreat）。

按 A 股财报披露日历排布：
  - pre_announce_h1 (中报预告期)：7 月上旬
  - h1_release      (中报披露期)：8 月
  - pre_announce_q3 (三季报预告期)：10 月上旬
  - annual_release  (年报披露期)：4 月

逻辑：
  - 监控字典 alert 触发 → 进入 incubation（潜伏建仓）
  - 财报披露期前后 → main_wave（主升浪共振）
  - 披露后放量滞涨 → retreat（撤退）

[Ref: 03_/02_维度二/.../step_05 §3.5.4 The Timer]
[Ref: PRD §3.4]
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.deep_strike.lighthouse._base import BaseLighthouseScene
from apps.deep_strike.lighthouse.schemas import (
    CallMetadata,
    CycleAnchor,
    TimerInput,
    TimerOutput,
    TimerPhase,
)

_SYSTEM_PROMPT = """你是 Lighthouse-Alpha 的 The Timer 时机预测员。

任务：按 A 股财报披露规律为单个 thesis 卡片排布三段时间窗口：
  - incubation (潜伏窗口)：监控字典预警触发 ~ 财报披露前 7 天
  - main_wave  (主升浪窗口)：财报披露 ±3 个交易日（业绩兑现共振）
  - retreat    (撤退窗口)：披露后第 4 天起或跌破 10 日均线

A 股财报披露日历参考：
  - 中报预告期：每年 7 月上旬（≤ 7/15）
  - 中报披露期：8 月（截止 8/31）
  - 三季报预告期：10 月上旬（≤ 10/15）
  - 年报披露期：4 月（截止 4/30）

输出 JSON：
{
  "incubation":  {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD", "expected_signal": "...", "confidence": 0.7},
  "main_wave":   {"start_date": "...", "end_date": "...", "expected_signal": "...", "confidence": 0.6},
  "retreat":     {"start_date": "...", "end_date": "...", "expected_signal": "...", "confidence": 0.5},
  "cycle_anchors": [
    {"cycle_type": "h1_release", "expected_window": ["YYYY-MM-DD", "YYYY-MM-DD"], "confidence": 0.8}
  ]
}
"""


def _next_calendar_anchors(current_date: date) -> list[CycleAnchor]:
    """按当前日期推未来 12 个月内的 cycle anchor（覆盖 6 种 cycle_type）。

    D4 SP5 严格对齐：pre_announce_h1 / h1_release / pre_announce_q3 /
    q3_release / annual_pre_announce / annual_release。
    """
    anchors: list[CycleAnchor] = []
    for year_offset in (0, 1):
        y = current_date.year + year_offset
        candidates = [
            ("pre_announce_h1",    date(y, 7, 1),  date(y, 7, 15)),
            ("h1_release",         date(y, 8, 1),  date(y, 8, 31)),
            ("pre_announce_q3",    date(y, 10, 1), date(y, 10, 15)),
            ("q3_release",         date(y, 10, 16),date(y, 10, 31)),
            ("annual_pre_announce",date(y, 1, 15), date(y, 3, 31)),
            ("annual_release",     date(y, 4, 1),  date(y, 4, 30)),
        ]
        for ctype, start, end in candidates:
            if end >= current_date and (end - current_date).days <= 365:
                anchors.append(
                    CycleAnchor(
                        cycle_type=ctype,  # type: ignore[arg-type]
                        expected_window=(start, end),
                        confidence=0.75 if "release" in ctype else 0.6,
                    )
                )
    return anchors[:6]


class TheTimer(BaseLighthouseScene):
    scene = "timer"
    prompt_template_id = "the_timer_v1"

    def build_messages(self, payload: TimerInput) -> list[dict[str, str]]:
        anchors = _next_calendar_anchors(payload.current_date)
        anchor_hint = "\n".join(
            f"- {a.cycle_type}: {a.expected_window[0]} ~ {a.expected_window[1]}"
            for a in anchors
        )

        user = (
            f"thesis_card_id: {payload.thesis_card_id}\n"
            f"symbol: {payload.symbol}\n"
            f"current_date: {payload.current_date}\n"
            f"alert_triggered_at: {payload.monitor_alert_triggered_at or '未触发'}\n"
            f"scan_hit_signals: {', '.join(payload.scan_hit_signals) or '（无）'}\n\n"
            f"未来 12 月披露窗口：\n{anchor_hint}\n\n"
            "请基于以上信息排布三段窗口。"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def parse(self, raw_json: dict, payload: TimerInput, metadata: CallMetadata) -> TimerOutput:
        def _phase(key: str, default_start: date, default_end: date) -> TimerPhase:
            raw = raw_json.get(key) or {}
            return TimerPhase(
                start_date=date.fromisoformat(raw["start_date"]) if raw.get("start_date") else default_start,
                end_date=date.fromisoformat(raw["end_date"]) if raw.get("end_date") else default_end,
                expected_signal=raw.get("expected_signal", f"{key} fallback"),
                confidence=float(raw.get("confidence", 0.5)),
            )

        cd = payload.current_date
        incubation = _phase("incubation", cd, cd + timedelta(days=30))
        main_wave = _phase("main_wave", cd + timedelta(days=31), cd + timedelta(days=45))
        retreat = _phase("retreat", cd + timedelta(days=46), cd + timedelta(days=60))

        # cycle_anchors：以本地日历为主，若 LLM 给了则尝试解析
        cycle_anchors = _next_calendar_anchors(cd)
        for a in raw_json.get("cycle_anchors", []):
            try:
                ctype = a.get("cycle_type")
                window = a.get("expected_window") or []
                if ctype and len(window) == 2:
                    parsed = CycleAnchor(
                        cycle_type=ctype,
                        expected_window=(date.fromisoformat(window[0]), date.fromisoformat(window[1])),
                        confidence=float(a.get("confidence", 0.6)),
                    )
                    # 替换同类型的（用 LLM 的覆盖默认）
                    cycle_anchors = [x for x in cycle_anchors if x.cycle_type != parsed.cycle_type]
                    cycle_anchors.append(parsed)
            except Exception:
                continue

        return TimerOutput(
            thesis_card_id=payload.thesis_card_id,
            current_date=cd,
            incubation=incubation,
            main_wave=main_wave,
            retreat=retreat,
            cycle_anchors=cycle_anchors[:4],
            metadata=metadata,
        )

    def fallback(
        self, payload: TimerInput, metadata: CallMetadata, *, reason: str
    ) -> TimerOutput:
        cd = payload.current_date
        return TimerOutput(
            thesis_card_id=payload.thesis_card_id,
            current_date=cd,
            incubation=TimerPhase(
                start_date=cd,
                end_date=cd + timedelta(days=30),
                expected_signal="fallback: alert 触发后 30 天潜伏",
                confidence=0.3,
            ),
            main_wave=TimerPhase(
                start_date=cd + timedelta(days=31),
                end_date=cd + timedelta(days=45),
                expected_signal="fallback: 财报披露日 ±3 天",
                confidence=0.3,
            ),
            retreat=TimerPhase(
                start_date=cd + timedelta(days=46),
                end_date=cd + timedelta(days=60),
                expected_signal="fallback: 披露后第 4 天起或跌破 10 日均线",
                confidence=0.3,
            ),
            cycle_anchors=_next_calendar_anchors(cd),
            metadata=metadata,
        )
