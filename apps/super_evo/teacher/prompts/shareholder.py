"""大股东诚信 Prompt 模板。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
"""

from __future__ import annotations

from typing import Any

from apps.super_evo.teacher.prompts.base import BasePrompt


class ShareholderPrompt(BasePrompt):
    instruction = "请分析以下大股东行为，判断是否存在诚信瑕疵或违规嫌疑。"

    def format_user(self, raw_data: dict[str, Any], context: dict[str, Any] | None) -> str:
        return (
            "## 分析任务：大股东诚信扫描\n"
            "请检查：减持、股权质押、被列为失信被执行人、占用上市公司资金等。\n"
            f"\n## 数据\n{raw_data}\n"
        )
