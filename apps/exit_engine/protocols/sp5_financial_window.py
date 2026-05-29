"""SP5 财报披露窗口协议（消费 D2 timer_signal）。

[Ref: 03_/04_维度四/.../step_05_SP3_Thesis失效协议.md §3.5.4]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apps.exit_engine.config import settings
from apps.exit_engine.models.position import Position
from apps.exit_engine.models.sell_signal import SellSignal, SellSignalEvent, SignalSeverity, SignalType
from apps.exit_engine.protocols.base import BaseProtocol, CheckResult

_TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "configs" / "sp5_advice_templates.yaml"

_STAGE_ALIASES = {
    "left_accumulate": "left_accumulate",
    "incubation": "left_accumulate",
    "main_wave": "main_wave",
    "main_surge": "main_wave",
    "retreat": "retreat",
}


def load_sp5_templates() -> dict[str, Any]:
    with open(_TEMPLATES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_stage(raw: str | None) -> str | None:
    if not raw:
        return None
    return _STAGE_ALIASES.get(raw.strip().lower())


def stage_advice(stage: str, templates: dict[str, Any] | None = None) -> dict[str, str]:
    tpl = templates or load_sp5_templates()
    entry = tpl.get("stages", {}).get(stage, {})
    emoji = entry.get("emoji", "")
    advice = entry.get("advice", f"SP5 {stage} 建议")
    return {"emoji": emoji, "advice": advice, "action_hint": entry.get("action_hint", "watch")}


class Sp5FinancialWindowProtocol(BaseProtocol):
    """SP5：priority=3，buffer_days=0，仅产 advice。"""

    protocol_name = SignalType.FINANCIAL_WINDOW
    priority = settings.sp5_financial_window_priority
    buffer_days = settings.sp5_financial_window_buffer_days

    def check(self, position: Position, context: dict) -> CheckResult:
        stage = normalize_stage(context.get("stage"))
        if stage is None:
            return CheckResult(triggered=False, context={"reason": "缺少或无效 stage"})
        templates = load_sp5_templates()
        if stage not in templates.get("stages", {}):
            return CheckResult(triggered=False, context={"reason": f"未知 stage: {stage}"})
        meta = stage_advice(stage, templates)
        return CheckResult(
            triggered=True,
            context={
                "stage": stage,
                "advice": meta["advice"],
                "emoji": meta["emoji"],
                "evidence_ref": context.get("timer_signal_event_id", context.get("event_id", "")),
                "evidence_url": context.get("evidence_url", ""),
                "financial_report_date": context.get("financial_report_date", ""),
                "execute_mode": templates.get("execute_mode", "advisory"),
            },
        )

    def trigger(self, position: Position, check_result: CheckResult) -> SellSignal:
        ctx = check_result.context
        stage = ctx.get("stage", "?")
        advice = ctx.get("advice", "")
        emoji = ctx.get("emoji", "")
        evidence_url = ctx.get("evidence_url", "")
        full_advice = f"{emoji} {advice}".strip()
        if evidence_url:
            full_advice = f"{full_advice}（证据：{evidence_url}）"
        reason = (
            f"SP5 财报窗口 stage={stage}；"
            f"financial_report_date={ctx.get('financial_report_date', '-')}"
        )
        return SellSignal(
            protocol_name=self.protocol_name,
            priority=self.priority,
            symbol=position.symbol,
            position_id=position.id,
            trigger_price=getattr(position, "cost_price", 0.0) or 0.0,
            current_price=getattr(position, "current_price", None) or 0.0,
            sell_ratio=0.0,
            reason=reason,
            advice=full_advice,
            buffer_days=self.buffer_days,
            is_revocable=False,
            extra={
                "protocol": "SP5",
                "stage": stage,
                "evidence_ref": ctx.get("evidence_ref", ""),
                "evidence_url": evidence_url,
                "financial_report_date": ctx.get("financial_report_date", ""),
                "execute_mode": ctx.get("execute_mode", "advisory"),
            },
        )

    def output_event(self, signal: SellSignal) -> SellSignalEvent:
        return SellSignalEvent(
            symbol=signal.symbol,
            signal_type=signal.protocol_name,
            trigger_price=signal.trigger_price,
            current_price=signal.current_price,
            protocol="SP5",
            advice=signal.advice,
            severity=SignalSeverity.NORMAL,
            sell_ratio=signal.sell_ratio,
            reason=signal.reason,
            position_id=signal.position_id,
            triggered_at=signal.triggered_at,
            is_revocable=False,
        )
