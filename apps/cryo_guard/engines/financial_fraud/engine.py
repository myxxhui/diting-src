"""财务测谎引擎 — 5 节点 LangGraph 工作流。

节点顺序：
  N1 field_extractor → N2 feature_calculator → N3 time_series_comparator
  → N4 peer_comparator → N5 llm_interrogator → END

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §7.1·C]
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from apps.cryo_guard.engines.financial_fraud.field_extractor import extract_fields
from apps.cryo_guard.engines.financial_fraud.feature_calculator import compute_features
from apps.cryo_guard.engines.financial_fraud.time_series_comparator import compare_time_series
from apps.cryo_guard.engines.financial_fraud.peer_comparator import compare_with_peers
from apps.cryo_guard.engines.financial_fraud.llm_interrogator import interrogate
from apps.cryo_guard.engines.financial_fraud.schemas import (
    EvidenceItem,
    FraudLabel,
    FinancialFraudReport,
    RiskLevel,
)

logger = logging.getLogger(__name__)


class FinancialFraudEngine:
    """5 节点财务测谎引擎（无依赖 LangGraph 骨架版）。

    启动期使用纯函数串联（不依赖 langgraph 包，便于 tier-1 本地 pytest）。
    tier-2 可替换为 langgraph.graph.StateGraph 版本。

    [Ref: step_04 §7.1·C]
    """

    def __init__(
        self,
        db_session=None,
        vllm_url: Optional[str] = None,
        adapter_path: Optional[str] = None,
    ) -> None:
        self.db_session = db_session
        self.vllm_url = vllm_url
        self.adapter_path = adapter_path

    def analyze(self, symbol: str, report_period: str) -> FinancialFraudReport:
        """执行完整 5 节点分析流程。

        [Ref: step_04 §3.5.2 N1-N5]
        """
        logger.info("[engine] 开始分析 symbol=%s period=%s", symbol, report_period)

        # N1: 字段抽取
        fields = extract_fields(symbol, report_period, self.db_session)

        # N2: 特征计算（需前一期，这里简化为无前期数据）
        features = compute_features(fields)

        # N3: 时序对比
        ts_result = compare_time_series(symbol, report_period, self.db_session)

        # N4: 同行对比
        industry = fields.get("industry") or "unknown"
        peer_result = compare_with_peers(symbol, industry, fields, self.db_session)

        # N5: LLM 裁决
        llm_out = interrogate(
            symbol=symbol,
            report_period=report_period,
            features=features,
            time_series_result=ts_result,
            peer_result=peer_result,
            vllm_url=self.vllm_url,
            adapter_path=self.adapter_path,
        )

        report = FinancialFraudReport(
            symbol=symbol,
            report_period=report_period,
            label=llm_out.label,
            confidence=llm_out.confidence,
            risk_level=llm_out.risk_level,
            features=features,
            peer_fallback=peer_result.get("peer_fallback"),
            history_insufficient=ts_result.get("insufficient", False),
            evidence=llm_out.evidence,
            reason_zh=llm_out.reason_zh,
            lora_loaded=llm_out.lora_loaded,
            missing_fields=fields.get("missing_fields", []),
        )

        logger.info(
            "[engine] 完成 symbol=%s label=%s confidence=%.2f lora_loaded=%s",
            symbol, report.label.value, report.confidence, report.lora_loaded,
        )
        return report
