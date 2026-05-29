"""关联交易 Prompt 模板。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

from typing import Any

from apps.super_evo.teacher.prompts.base import BasePrompt


class RelatedPartyPrompt(BasePrompt):
    instruction = "请分析以下关联交易，判断是否存在利益输送或不公允定价。"

    def format_user(self, raw_data: dict[str, Any], context: dict[str, Any] | None) -> str:
        return (
            "## 分析任务：关联交易扫描\n"
            "请检查：关联方占款、关联销售/采购定价公允性、关联担保等。\n"
            f"\n## 数据\n{raw_data}\n"
        )
