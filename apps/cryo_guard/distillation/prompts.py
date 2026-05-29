"""Teacher 蒸馏 Prompt 模板（三引擎）。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

from textwrap import dedent

FINANCIAL_FRAUD_INSTRUCTION = "分析以下公司的财务报表，判断是否存在财务造假或粉饰迹象。"
SHAREHOLDER_INSTRUCTION = "对照大股东历史承诺与实际行为，判断是否存在'言行不一'风险。"
RELATED_PARTY_INSTRUCTION = (
    "分析公司的关联交易披露与股权结构，判断是否存在资金腾挪、明股实债或循环交易。"
)

FINANCIAL_FRAUD_PROMPT = dedent("""
你是一位资深的财务造假分析专家。请分析以下公司的财务报表，判断是否存在财务造假或粉饰迹象。

## 公司信息
- 名称：{company_name}
- 代码：{symbol}
- 报告期：{report_date}

## 核心财务数据（单位：元）
| 指标 | 本期 | 上期 | 同比 |
|---|---|---|---|
| 货币资金 | {cash_cur} | {cash_prev} | {cash_yoy} |
| 短期借款 | {short_debt_cur} | {short_debt_prev} | - |
| 长期借款 | {long_debt_cur} | {long_debt_prev} | - |
| 应收账款 | {ar_cur} | {ar_prev} | {ar_yoy} |
| 存货 | {inv_cur} | {inv_prev} | {inv_yoy} |
| 营业收入 | {rev_cur} | {rev_prev} | {rev_yoy} |
| 营业成本 | {cost_cur} | {cost_prev} | - |
| 毛利率 | {gm_cur} | {gm_prev} | - |
| 净利润 | {np_cur} | {np_prev} | - |
| 经营现金流 | {ocf_cur} | {ocf_prev} | - |
| 研发费用 | {rd_cur} | {rd_prev} | - |
| 研发资本化 | {rdcap_cur} | {rdcap_prev} | - |

## 行业均值（同行 P50）
- 毛利率：{peer_gm}
- 应收周转率：{peer_ar_turn}
- 存货周转率：{peer_inv_turn}

## 分析要求
请逐一检查以下 6 类粉饰特征，并给出 0-1 之间的 risk_score（越高越严重）：
1. **存贷双高**：货币资金与有息负债是否同时处于高位？
2. **现金流背离**：经营现金流是否与净利润严重背离？
3. **应收异常**：应收账款增速是否显著高于收入增速？
4. **存货积压**：存货增速是否显著高于成本增速？
5. **研发资本化突变**：研发资本化率是否突然大幅变化？
6. **毛利率异常**：毛利率是否显著偏离行业均值？

## 输出格式（严格 JSON，无 markdown，无前后文字）
{{
  "risk_score": 0.0,
  "decision": "pass",
  "features": {{
    "cash_debt_anomaly": {{"detected": false, "evidence": ""}},
    "cf_deviation": {{"detected": false, "evidence": ""}},
    "receivable_anomaly": {{"detected": false, "evidence": ""}},
    "inventory_anomaly": {{"detected": false, "evidence": ""}},
    "rd_capitalization_anomaly": {{"detected": false, "evidence": ""}},
    "gross_margin_anomaly": {{"detected": false, "evidence": ""}}
  }},
  "summary": "100 字以内总结"
}}

阈值约定：
- risk_score ≥ 0.85 → reject
- 0.60 ≤ risk_score < 0.85 → degrade
- risk_score < 0.60 → pass

只输出 JSON，不要任何其他文字。
""").strip()


SHAREHOLDER_PROMPT = dedent("""
你是资深公司治理研究员。请对照大股东的历史承诺与实际行为，判断是否存在"言行不一"风险。

## 公司信息
- 名称：{company_name}
- 代码：{symbol}
- 评估窗口：{window_start} ~ {window_end}

## 历史承诺（公告摘要）
{commitments_block}

## 实际行为
- 实际增减持：{actual_holdings_changes}
- 实际业绩 vs 承诺业绩：{actual_vs_promised_perf}
- 质押比例变化：{pledge_changes}
- 战略执行情况：{strategy_progress}

## 检测目标： 5 类言行不一
1. **增持承诺失信**
2. **减持违规**
3. **业绩对赌失败**
4. **质押风险隐瞒**
5. **战略承诺落空**

## 输出格式（严格 JSON）
{{
  "risk_score": 0.0,
  "decision": "pass",
  "categories": {{
    "increase_commitment_default": {{"detected": false, "evidence": ""}},
    "decrease_violation": {{"detected": false, "evidence": ""}},
    "performance_pledge_failed": {{"detected": false, "evidence": ""}},
    "pledge_concealment": {{"detected": false, "evidence": ""}},
    "strategy_default": {{"detected": false, "evidence": ""}}
  }},
  "summary": "100 字以内总结"
}}

阈值：score ≥ 0.80 → reject；0.55 ≤ score < 0.80 → degrade；< 0.55 → pass。
只输出 JSON。
""").strip()


RELATED_PARTY_PROMPT = dedent("""
你是关联交易合规审查专家。请分析以下公司的关联交易明细与股权穿透结构，识别资金腾挪、明股实债或循环交易风险。

## 公司信息
- 名称：{company_name}
- 代码：{symbol}
- 报告期：{report_period}

## 股权穿透（节选）
{equity_block}

## 关联交易明细（金额单位：元）
| 关联方 | 关系 | 类型 | 金额 | 占同类比 | 定价方式 |
|---|---|---|---|---|---|
{rp_table}

## 异常股权信号
{anomaly_signals}

## 检测目标：4 类典型特征
1. **循环交易**
2. **明股实债**
3. **资金占用**
4. **附注披露异常**

## 输出格式（严格 JSON）
{{
  "risk_score": 0.0,
  "decision": "pass",
  "features": {{
    "cycle_transaction": {{"detected": false, "evidence": ""}},
    "debt_equity": {{"detected": false, "evidence": ""}},
    "fund_occupation": {{"detected": false, "evidence": ""}},
    "disclosure_anomaly": {{"detected": false, "evidence": ""}}
  }},
  "summary": "100 字以内总结"
}}

阈值：score ≥ 0.80 → reject；0.55 ≤ score < 0.80 → degrade；< 0.55 → pass。
只输出 JSON。
""").strip()


def build_prompt(engine: str, context: dict) -> tuple[str, str]:
    """根据引擎名构造 (instruction, user_prompt)。"""
    if engine == "financial_fraud":
        return FINANCIAL_FRAUD_INSTRUCTION, FINANCIAL_FRAUD_PROMPT.format(**context)
    if engine == "shareholder_integrity":
        return SHAREHOLDER_INSTRUCTION, SHAREHOLDER_PROMPT.format(**context)
    if engine == "related_party":
        return RELATED_PARTY_INSTRUCTION, RELATED_PARTY_PROMPT.format(**context)
    raise ValueError(f"unknown engine {engine}")
