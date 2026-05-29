"""财务测谎 Prompt 模板。

[Ref: 03_/05_维度五/stages/stage_1_启动期/steps/step_02]
[Ref: 03_/05_维度五/03_数据采集与预处理.md#6.1]
"""

from __future__ import annotations

from typing import Any

from apps.super_evo.teacher.prompts.base import BasePrompt


class FinancialFraudPrompt(BasePrompt):
    instruction = (
        "请分析以下公司的财务数据，判断是否存在财务造假或粉饰迹象，"
        "并按系统要求输出 JSON 风控结论。"
    )

    CHECKLIST = (
        "1. 存贷双高：货币资金与有息负债是否同时处于高位？\n"
        "2. 现金流背离：经营现金流是否与净利润严重背离？\n"
        "3. 应收异常：应收账款增速是否显著高于收入增速？\n"
        "4. 存货积压：存货增速是否显著高于成本增速？\n"
        "5. 研发资本化突变：研发资本化率是否突然大幅变化？\n"
        "6. 毛利率异常：毛利率是否显著偏离行业均值？"
    )

    def format_user(self, raw_data: dict[str, Any], context: dict[str, Any] | None) -> str:
        company = raw_data.get("company_name", "未知")
        symbol = raw_data.get("symbol", "")
        report_date = raw_data.get("report_date", "")
        fin = raw_data.get("financial_data", {})

        ctx_block = ""
        if context:
            ctx_block = f"\n## 额外上下文\n{context}\n"

        return (
            f"## 分析任务：财务造假检测\n"
            f"\n请按以下清单检查并输出 JSON 风控结论：\n{self.CHECKLIST}\n"
            f"\n## 公司信息\n- 名称：{company}\n- 代码：{symbol}\n- 报告期：{report_date}\n"
            f"\n## 财务数据\n{fin}\n"
            f"{ctx_block}"
        )
