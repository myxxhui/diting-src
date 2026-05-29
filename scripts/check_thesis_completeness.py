"""thesis 卡片 completeness check 示例脚本。[Ref: deep-step05]"""
from __future__ import annotations

from apps.deep_strike.engines.thesis.schema import EvidenceItem, ThesisCardSchema, ValuationAnchor
from apps.deep_strike.engines.thesis.completeness import batch_check

card = ThesisCardSchema(
    symbol="002837",
    name="英维克",
    playbook_id="profit_capture",
    confidence=0.72,
    thesis_summary=(
        "【002837·英维克】profit_capture 剧本命中（置信度 72%）。"
        "核心逻辑：数据中心温控设备订单同比增长 68%。"
        "综合基本面证据链与行业对比，建议买入，需跟踪后续财报与行业政策动态。"
    ),
    evidence_chain=[
        EvidenceItem(evidence_type="financial", content="毛利率 36.2%，同比提升 1.1pp，行业领先。"),
        EvidenceItem(evidence_type="announcement", content="新签数据中心温控订单同比增长 68%，超市场预期。"),
        EvidenceItem(evidence_type="industry", content="液冷市场 CAGR 36%，公司市占率 29%，行业地位稳固。"),
    ],
    risks=[
        "监管政策收紧风险：行业政策存在不确定性，可能对公司主营业务产生负面影响。",
        "市场系统性风险：宏观经济下行或市场整体调整可能导致股价短期承压。",
        "业绩低于预期风险：实际财报数据或营收增速若低于市场预期，可能引发估值回调。",
    ],
    valuation_anchor=ValuationAnchor(method="PE", target_price=52.8, basis="PE 法"),
    action="buy",
)

r = batch_check([card])
print("batch_check:", r["all_pass"], "|", r)
assert r["all_pass"], f"❌ completeness check 失败: {r}"
print("✅ completeness check 通过")
