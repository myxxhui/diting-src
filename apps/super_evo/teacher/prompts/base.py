"""Prompt 模板基类。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/05_维度五/03_数据采集与预处理.md#6.1]
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


SYSTEM_PROMPT = """你是一位资深的投资分析专家。请根据提供的数据进行分析，并以 JSON 格式输出结果。

## 输出格式要求
你的输出必须是有效的 JSON，包含以下字段：
- risk_score: 风险分数 (0-1 浮点)
- decision: 决策（"pass" / "degrade" / "reject" 三选一）
- evidence: 关键证据列表（字符串数组，每条 ≤ 100 字）
- reasoning: 推理过程（字符串，≤ 300 字）
- confidence: 置信度 (0-1 浮点)

## 严格要求
1. 只输出 JSON，不要任何 markdown 包装、不要解释、不要前后空行
2. 字段名小写下划线，值用中文
3. 若数据不足以下决策，risk_score=0.5、decision="degrade"、confidence ≤ 0.5
"""


class BasePrompt(ABC):
    """Prompt 模板基类。

    子类必须重写 `instruction`（固定一句话指令）与 `format_user`（拼装用户消息）。
    """

    instruction: str = "请分析以下数据并输出 JSON 风控结论。"

    def system(self) -> str:
        return SYSTEM_PROMPT

    @abstractmethod
    def format_user(self, raw_data: dict[str, Any], context: dict[str, Any] | None) -> str:
        ...

    def format_input_summary(self, raw_data: dict[str, Any]) -> str:
        """用于落 input 字段的人类可读输入摘要（精简版 raw_data）。"""
        return self.format_user(raw_data, None)

    def to_messages(
        self, raw_data: dict[str, Any], context: dict[str, Any] | None
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system()},
            {"role": "user", "content": self.format_user(raw_data, context)},
        ]
