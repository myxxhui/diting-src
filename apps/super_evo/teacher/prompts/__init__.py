"""Prompt 注册中心。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

from apps.super_evo.teacher.prompts.base import BasePrompt
from apps.super_evo.teacher.prompts.financial_fraud import FinancialFraudPrompt
from apps.super_evo.teacher.prompts.related_party import RelatedPartyPrompt
from apps.super_evo.teacher.prompts.shareholder import ShareholderPrompt

REGISTRY: dict[str, BasePrompt] = {
    "financial_fraud": FinancialFraudPrompt(),
    "shareholder": ShareholderPrompt(),
    "related_party": RelatedPartyPrompt(),
}


def get_prompt(task_type: str) -> BasePrompt:
    if task_type not in REGISTRY:
        raise KeyError(f"Unknown task_type={task_type}, available={list(REGISTRY)}")
    return REGISTRY[task_type]
