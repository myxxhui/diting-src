"""Lighthouse-Alpha 五场景模块（D2 维度二）。

五场景：
  - The Sniffer    (主题嗅探：原文 → 候选题材簇)
  - The Architect  (论据架构师：thesis → 监控字典 monitor_matrix)
  - The Critic     (物理证伪：候选 → physical_gate 2x2 矩阵)
  - The Scorer     (三维打分：policy_tier / industry_space / a_share_mapping)
  - The Timer      (时机：incubation / main_wave / retreat 三段窗口)

统一调用 `apps.common.ai_dispatcher.AIDispatcher` 路由到远程 Opus / 本地 vLLM / mock。

[Ref: 03_/02_维度二_纵深进攻/stages/stage_1_启动期/steps/step_02~07]
[Ref: 共享规约 19 异构 AI 调度栈]
[Ref: L1 哲学基石⑥ 物理证伪 ≥ 财务证伪]
"""
from __future__ import annotations

__all__ = [
    "TheSniffer",
    "TheArchitect",
    "TheCritic",
    "TheScorer",
    "TheTimer",
    "LighthouseOrchestrator",
]

# 延迟导入避免循环
from apps.deep_strike.lighthouse.sniffer import TheSniffer  # noqa: E402
from apps.deep_strike.lighthouse.architect import TheArchitect  # noqa: E402
from apps.deep_strike.lighthouse.critic import TheCritic  # noqa: E402
from apps.deep_strike.lighthouse.scorer import TheScorer  # noqa: E402
from apps.deep_strike.lighthouse.timer import TheTimer  # noqa: E402
from apps.deep_strike.lighthouse.orchestrator import LighthouseOrchestrator  # noqa: E402
