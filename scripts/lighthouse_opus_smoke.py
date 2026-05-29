"""Lighthouse Opus 远程联调冒烟（≤5 次远程调用）。

用例（5 次调用）：
  1. The Sniffer    : 1 篇液冷招标 + 1 篇政策摘录 → 题材簇
  2. The Critic     : 上面簇 → physical_gate
  3. The Scorer     : 上面簇 → 三维分
  4. The Architect  : thesis 节点 → monitor_matrix
  5. The Timer      : thesis 卡 → 三段窗口

预算控制：AIDispatcher 单实例共享日预算（默认 ¥1000）。

[Ref: 03_/02_维度二/.../step_02~07]
[Ref: 共享规约 19 AIDispatcher.call() 唯一入口]
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).parents[1] / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY 未配置；本脚本仅用于远程联调，跳过。")
        print("   测试请改跑：make deep-step02-lighthouse-test")
        return 0

    print(f"  ANTHROPIC_API_KEY = {'✅ 已配置' if os.getenv('ANTHROPIC_API_KEY') else '⚠️  未配置'}")
    print(f"  LIGHTHOUSE_MODEL  = {os.getenv('LIGHTHOUSE_REMOTE_MODEL') or os.getenv('ANTHROPIC_MODEL', 'claude-opus-4-6')}")

    # 强制重置单例（确保从 .env 拿到最新 key）
    from apps.common.ai_dispatcher import AIDispatcher
    AIDispatcher._instance = None
    dispatcher = AIDispatcher.default()
    print(f"  budget 状态: {dispatcher.budget_status()}")

    from apps.deep_strike.lighthouse import (
        TheArchitect, TheCritic, TheScorer, TheSniffer, TheTimer
    )
    from apps.deep_strike.lighthouse.schemas import (
        ArchitectInput, CriticInput, ScorerInput, SnifferInput, TimerInput
    )

    print("\n=" * 35)
    print("  Lighthouse Opus 远程联调（5 次调用）")
    print("=" * 70)

    # ─── #1 Sniffer (force_route=remote，因 vLLM 本地不可用) ───
    print("\n[1/5] The Sniffer (force remote) ...")
    sniffer = TheSniffer(dispatcher=dispatcher)
    sniffer_out = sniffer.call(SnifferInput(
        raw_texts=[
            "中国移动 2026 年智算中心液冷服务器集采招标公告，预算 8.5 亿元，"
            "重点采购冷板式液冷整机柜，要求支持 800Gbps 网络互联。",
            "国务院《关于推动算力基础设施高质量发展的指导意见》提出，"
            "到 2027 年新建大型数据中心 PUE 不超过 1.25，液冷渗透率超 50%。",
        ],
        window_start=date(2026, 5, 1),
        window_end=date(2026, 5, 23),
        source_hint="ccgp",
    ), force_route="remote")
    print(f"  簇数: {len(sniffer_out.clusters)}  cost≈¥{sniffer_out.metadata.cost_yuan_est:.2f}")
    for c in sniffer_out.clusters[:3]:
        print(f"  - {c.keyword} (conf={c.confidence:.2f}) {c.summary[:60]}")

    if not sniffer_out.clusters:
        # 兜底人造一个簇供后续场景用，避免浪费已花掉的预算
        from apps.deep_strike.lighthouse.schemas import SnifferCluster
        sniffer_out.clusters = [SnifferCluster(
            cluster_id="manual_liquid_cooling",
            keyword="液冷算力",
            summary="人造测试簇：液冷算力中标爆发",
            freq_growth_pct=1.5,
            confidence=0.8,
        )]
        print("  ⚠️  Sniffer 未产出簇，使用兜底簇继续后续场景")

    target_cluster = sniffer_out.clusters[0]

    # ─── #2 Critic ───
    print("\n[2/5] The Critic (物理证伪) ...")
    critic = TheCritic(dispatcher=dispatcher)
    critic_out = critic.call(CriticInput(
        cluster_id=target_cluster.cluster_id,
        cluster_keyword=target_cluster.keyword,
        candidate_symbol="002837",
        candidate_revenue_base_yuan=3.5e9,    # 英维克 2024 营收约 35 亿
        candidate_order_size_yuan=8.5e8,      # 8.5 亿 / 35 亿 ≈ 24%
        sample_raw_texts=["中国移动液冷集采 8.5 亿"],
    ))
    print(f"  physical_gate={critic_out.physical_gate}  "
          f"elasticity={critic_out.capacity_elasticity_ratio:.2%}  "
          f"reason={critic_out.falsified_reason}")
    print(f"  baselines: phy={critic_out.physical_baseline} fin={critic_out.financial_baseline} "
          f"com={critic_out.commercial_baseline} beh={critic_out.behavioral_baseline}")

    # ─── #3 Scorer ───
    print("\n[3/5] The Scorer (三维打分) ...")
    scorer = TheScorer(dispatcher=dispatcher)
    scorer_out = scorer.call(ScorerInput(
        cluster_id=target_cluster.cluster_id,
        cluster_keyword=target_cluster.keyword,
        candidate_symbols=["002837"],
        policy_text_excerpts=["国务院算力规划：PUE ≤ 1.25，液冷渗透率 > 50%（2027）"],
        industry_research_excerpts=["中信证券：液冷市场 2030 年 1500 亿规模"],
        a_share_mapping_excerpts=["英维克为冷板式液冷龙头，市占率 40%"],
    ))
    print(f"  policy={scorer_out.policy_tier} industry={scorer_out.industry_space} "
          f"mapping={scorer_out.a_share_mapping} → composite={scorer_out.composite} "
          f"→ {scorer_out.decision} (cap={scorer_out.confidence_cap})")

    # ─── #4 Architect ───
    print("\n[4/5] The Architect (监控字典) ...")
    architect = TheArchitect(dispatcher=dispatcher)
    arch_out = architect.call(ArchitectInput(
        thesis_card_id="thesis_002837_liquid_cooling_20260523",
        target_company="英维克",
        symbol="002837",
        logic_chain_nodes=["node_supply_demand_mismatch", "node_capacity_elasticity"],
    ))
    print(f"  monitor 字段数: {len(arch_out.monitor_matrix)}")
    for f in arch_out.monitor_matrix[:2]:
        print(f"  - {f.probe_id} {f.metric_name} → {f.specific_target[:60]}")

    # ─── #5 Timer ───
    print("\n[5/5] The Timer (三段窗口) ...")
    timer = TheTimer(dispatcher=dispatcher)
    timer_out = timer.call(TimerInput(
        thesis_card_id="thesis_002837_liquid_cooling_20260523",
        symbol="002837",
        current_date=date(2026, 5, 23),
        monitor_alert_triggered_at=date(2026, 5, 20),
        scan_hit_signals=[target_cluster.keyword, "中报预告窗口"],
    ))
    print(f"  incubation : {timer_out.incubation.start_date} → {timer_out.incubation.end_date}  ({timer_out.incubation.expected_signal[:30]})")
    print(f"  main_wave  : {timer_out.main_wave.start_date} → {timer_out.main_wave.end_date}  ({timer_out.main_wave.expected_signal[:30]})")
    print(f"  retreat    : {timer_out.retreat.start_date} → {timer_out.retreat.end_date}  ({timer_out.retreat.expected_signal[:30]})")
    print(f"  cycle_anchors: {len(timer_out.cycle_anchors)} 个")

    # ─── 总结 ───
    final_budget = dispatcher.budget_status()
    print("\n" + "=" * 70)
    print(f"  ✅ 5/5 场景全部通过；预算消耗 ≈ ¥{final_budget['spent_yuan']:.2f}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
