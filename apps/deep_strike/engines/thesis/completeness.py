"""thesis 卡片完整性校验器。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_05 §B.C]
"""
from __future__ import annotations

from typing import Any

from apps.deep_strike.engines.thesis.schema import ThesisCardSchema


class CompletenessError(Exception):
    """卡片完整性不通过。"""


def check_one(card: ThesisCardSchema) -> list[str]:
    """检查单张卡片，返回失败原因列表（空=通过）。"""
    errors: list[str] = []

    if len(card.thesis_summary) < 50:
        errors.append(f"thesis_summary 长度 {len(card.thesis_summary)} < 50")

    if len(card.evidence_chain) < 3:
        errors.append(f"evidence_chain 数量 {len(card.evidence_chain)} < 3")

    if not card.risks:
        errors.append("risks 不得为空数组")
    else:
        short = [r for r in card.risks if len(r) < 20]
        if short:
            errors.append(f"risks 中 {len(short)} 条 < 20字")

    if card.valuation_anchor.method != "watch_only" and card.valuation_anchor.target_price is None:
        errors.append("valuation_anchor.target_price 不得为 null（非 watch_only 时）")

    if card.action not in ("buy", "add", "watch"):
        errors.append(f"action={card.action!r} 不在枚举 {{buy,add,watch}}")

    return errors


def batch_check(cards: list[ThesisCardSchema]) -> dict[str, Any]:
    """批量校验，返回汇总结果。"""
    results = []
    all_pass = True
    for card in cards:
        errs = check_one(card)
        ok = len(errs) == 0
        if not ok:
            all_pass = False
        results.append({"thesis_id": card.thesis_id, "pass": ok, "errors": errs})
    return {"all_pass": all_pass, "total": len(cards), "results": results}
