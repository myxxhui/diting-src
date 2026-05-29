"""The Scorer — 三维打分（policy_tier / industry_space / a_share_mapping）。

PRD §2.3 严格对齐：
  composite = 0.35·policy_tier + 0.35·industry_space + 0.30·a_share_mapping
  ≥ 8.0  → propose（confidence_cap 0.85）
  7.0~7.9 → watch（0.70）
  < 7.0   → discard（当日不入推荐池）

成本控制：industry_space 走本地 vLLM（force_route="local"），
         policy_tier + a_share_mapping 走远程 Opus。
         单 cluster 总成本 ≤ ¥0.75；超额仅算 policy_tier，标 partial。

[Ref: 03_/02_维度二/.../step_07 §3.5.4 TS1~TS7]
[Ref: L2 §8A.4]
[Ref: 共享规约 19 异构 AI 调度]
"""
from __future__ import annotations

import logging

from apps.deep_strike.lighthouse._base import BaseLighthouseScene
from apps.deep_strike.lighthouse.schemas import CallMetadata, ScorerInput, ScorerOutput

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """你是 Lighthouse-Alpha 的 The Scorer 三维评分员。

按 PRD §2.3 对 A 股投资候选题材打分，三维独立打分（0~10 整数）：

1) policy_tier        — 政策级别
   10 = 顶层规划+国资委硬指标+财政补贴齐全；
    8 = 部委文件+地方落地；
    6 = 行业引导意见；
    4 = 行业自律倡议；
    2 = 媒体讨论；
    0 = 无政策

2) industry_space     — 产业空间
   10 = 万亿级新市场（>5000 亿）；
    8 = 千亿级；
    6 = 百亿级；
    4 = 十亿级；
    2 = 单位亿级；
    0 = 无清晰空间

3) a_share_mapping    — A 股映射度
   10 = 多家纯正受益龙头，业绩弹性 >30%；
    8 = 2~3 家纯正标的；
    6 = 单一龙头明确；
    4 = 多家间接受益；
    2 = 标的稀缺；
    0 = 无 A 股映射

输出 JSON：
{
  "policy_tier": 9,
  "industry_space": 8,
  "a_share_mapping": 7,
  "source_urls": ["https://...", "..."],
  "reasoning": "≤80 字简述"
}
"""


class TheScorer(BaseLighthouseScene):
    scene = "scorer_policy"
    prompt_template_id = "the_scorer_v1"

    MAX_COST_YUAN_PER_CLUSTER = 0.75

    def build_messages(self, payload: ScorerInput) -> list[dict[str, str]]:
        policy = "\n".join(f"- {p[:200]}" for p in payload.policy_text_excerpts[:5])
        industry = "\n".join(f"- {p[:200]}" for p in payload.industry_research_excerpts[:5])
        mapping = "\n".join(f"- {p[:200]}" for p in payload.a_share_mapping_excerpts[:5])
        symbols = ", ".join(payload.candidate_symbols) or "（无）"

        user = (
            f"cluster_id: {payload.cluster_id}\n"
            f"题材: {payload.cluster_keyword}\n"
            f"候选标的: {symbols}\n\n"
            f"【政策原文摘录】\n{policy or '（无）'}\n\n"
            f"【产业研报摘录】\n{industry or '（无）'}\n\n"
            f"【A 股映射依据】\n{mapping or '（无）'}\n\n"
            "请给出三维分（0~10 整数）。每个维度若无 source 引用应自动减 1 分。"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    def parse(self, raw_json: dict, payload: ScorerInput, metadata: CallMetadata) -> ScorerOutput:
        policy = int(raw_json.get("policy_tier", 0))
        industry = int(raw_json.get("industry_space", 0))
        mapping = int(raw_json.get("a_share_mapping", 0))

        # 缺 source 引用自动降一档
        if not payload.policy_text_excerpts:
            policy = max(0, policy - 1)
        if not payload.industry_research_excerpts:
            industry = max(0, industry - 1)
        if not payload.a_share_mapping_excerpts:
            mapping = max(0, mapping - 1)

        composite = ScorerOutput.compute_composite(policy, industry, mapping)
        decision, cap = ScorerOutput.derive_decision(composite)

        return ScorerOutput(
            cluster_id=payload.cluster_id,
            policy_tier=policy,
            industry_space=industry,
            a_share_mapping=mapping,
            composite=composite,
            decision=decision,
            confidence_cap=cap,
            source_urls=[str(u) for u in raw_json.get("source_urls", [])[:10]],
            partial=False,
            metadata=metadata,
        )

    def fallback(
        self, payload: ScorerInput, metadata: CallMetadata, *, reason: str
    ) -> ScorerOutput:
        """fallback：仅按 source 数量给基础分（保守）。"""
        policy = 2 if payload.policy_text_excerpts else 0
        industry = 2 if payload.industry_research_excerpts else 0
        mapping = 2 if payload.a_share_mapping_excerpts else 0
        composite = ScorerOutput.compute_composite(policy, industry, mapping)
        decision, cap = ScorerOutput.derive_decision(composite)

        return ScorerOutput(
            cluster_id=payload.cluster_id,
            policy_tier=policy,
            industry_space=industry,
            a_share_mapping=mapping,
            composite=composite,
            decision=decision,
            confidence_cap=cap,
            source_urls=[],
            partial=True,
            metadata=metadata,
        )
