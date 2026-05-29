"""The Architect — 论据架构师。

任务：将 thesis 卡片的逻辑链节点翻译成结构化 `monitor_matrix`
     （HS Code / source_url / keywords + alert_threshold 双形式）。

输出供 D3 探针消费：
  - probe_id ∈ {P5 政府招标, P6 海关高频, P7 行业新闻}
  - data_source_type STRUCT_DATA_API or WEB_SCRAPING
  - alert_threshold_struct {operator, value, window_days}

[Ref: 03_/02_维度二/.../step_02 §3.5.5 The Architect Schema]
[Ref: 共享规约 20 监控字典]
"""
from __future__ import annotations

from typing import Any

from apps.deep_strike.lighthouse._base import BaseLighthouseScene
from apps.deep_strike.lighthouse.schemas import (
    AlertThresholdStruct,
    ArchitectInput,
    CallMetadata,
    MonitorField,
    MonitorMatrix,
)

_SYSTEM_PROMPT = """你是 Lighthouse-Alpha 的 The Architect 论据架构师。

任务：把 thesis 卡片逻辑链节点翻译成可被 D3 探针自动消费的结构化"监控字典"——
每个字段必须能 ① 指到具体数据源（API or 网址 or HS Code or 关键词），
② 给出可机读阈值（operator + value + window_days），③ 反映该字段命中后会触发哪个 thesis 逻辑节点。

硬约束：
1) 仅输出 JSON，不要解释；
2) data_source_type=STRUCT_DATA_API 时 source_api 必填，如 "akshare.macro_china_customs()"；
3) data_source_type=WEB_SCRAPING 时 source_url 必填，如 "https://www.ccgp.gov.cn"；
4) specific_target 必须具体到 HS Code / 目的地 / 关键词组合，不接受空泛描述；
5) mapped_logic_chain_nodes 不可为空，须对齐用户传入的 logic_chain_nodes；
6) probe_id 只能是 P5 / P6 / P7。

输出 schema：
{
  "monitor_matrix": [
    {
      "field_id": "field_xxx",
      "probe_id": "P6",
      "metric_name": "...",
      "data_source_type": "STRUCT_DATA_API",
      "source_api": "akshare.xxx()",
      "source_url": null,
      "specific_target": "HS Code: 85176239, 目的地: 美国",
      "keywords": [],
      "alert_threshold": "每月20日发布，环比 > 30%",
      "alert_threshold_struct": {"operator": "mom_pct", "value": 0.30, "window_days": 30},
      "polling_frequency": "monthly_after_release",
      "mapped_logic_chain_nodes": ["node_supply_demand_mismatch"]
    }
  ]
}
"""


class TheArchitect(BaseLighthouseScene):
    scene = "architect"
    prompt_template_id = "the_architect_v1"

    def __init__(self, *args, max_tokens: int = 4096, **kwargs) -> None:
        # Architect 单次输出 6 字段 ≈ 3-4k tokens，默认 2048 会被截断 → JSON 解析失败 → fallback
        super().__init__(*args, max_tokens=max_tokens, **kwargs)

    def build_messages(self, payload: ArchitectInput) -> list[dict[str, str]]:
        nodes = "\n".join(f"- {n}" for n in payload.logic_chain_nodes)
        user = (
            f"thesis_card_id: {payload.thesis_card_id}\n"
            f"target_company: {payload.target_company}\n"
            f"symbol: {payload.symbol}\n"
            f"logic_chain_nodes:\n{nodes}\n\n"
            "请为以上每个 logic_chain_node 生成 1~2 个可监控字段，"
            "确保覆盖 ① 高频结构化数据（海关/招标/财报）② 网页关键词触发（政策/研报）。"
        )
        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def _normalize_operator(raw: str) -> str:
        """把 LLM 自由风格 operator 归一化到 5 枚举。

        - 'mom_pct_or_yoy_pct' → 取**首个出现**的 'mom_pct'
        - 'count_gte' / 'amount_gte' / 'qoq_pct' / 'gte' → 'gt'
        - 'lt' / 'lte' → 'lt'
        - 大小写无关、下划线/连字符无关
        """
        if not raw:
            return "gt"
        token = raw.strip().lower().replace("-", "_")
        allowed = ("gt", "lt", "mom_pct", "yoy_pct", "sum_pct")
        if token in allowed:
            return token
        # 取在 token 中**最早出现**的合法 operator（防 set 迭代顺序不确定）
        best_op: str | None = None
        best_idx = len(token) + 1
        for op in allowed:
            idx = token.find(op)
            if idx >= 0 and idx < best_idx:
                best_idx = idx
                best_op = op
        if best_op:
            return best_op
        # 兜底：lt/gte 类
        if "lte" in token or token.startswith("lt"):
            return "lt"
        return "gt"

    @staticmethod
    def _normalize_polling_frequency(raw: str) -> str:
        """把 LLM 自由风格 polling_frequency 归一化到 schema 允许的 2 枚举。

        允许：daily / monthly_after_release
        映射：
          - 'daily' / 'hourly' / 'weekly' / 'realtime' → 'daily'
          - 'monthly' / 'monthly_after_release' / 'monthly_after_disclosure' → 'monthly_after_release'
          - 'quarterly_after_disclosure' / 'quarterly' / 'annual' → 'monthly_after_release'（按 D3 §6A 节奏，季度/年度按月轮询字典即可）
          - 空 / 未识别 → 'daily'（保守每日一次）
        """
        if not raw:
            return "daily"
        token = str(raw).strip().lower().replace("-", "_")
        if token in {"daily", "monthly_after_release"}:
            return token
        if "monthly" in token or "quarterly" in token or "annual" in token or "yearly" in token:
            return "monthly_after_release"
        # weekly/hourly/realtime/intraday/event_based 等高频 → daily
        return "daily"

    def parse(
        self, raw_json: dict, payload: ArchitectInput, metadata: CallMetadata
    ) -> MonitorMatrix:
        fields_raw = raw_json.get("monitor_matrix", [])
        fields: list[MonitorField] = []
        for i, f in enumerate(fields_raw):
            try:
                thr = f.get("alert_threshold_struct", {})
                f["alert_threshold_struct"] = AlertThresholdStruct(
                    operator=self._normalize_operator(thr.get("operator", "gt")),
                    value=float(thr.get("value", 0.0)),
                    window_days=int(thr.get("window_days", 30)),
                )
                f["polling_frequency"] = self._normalize_polling_frequency(
                    f.get("polling_frequency", "daily")
                )
                f.setdefault("field_id", f"field_auto_{i}")
                f.setdefault("keywords", [])
                f.setdefault("status", "active")
                fields.append(MonitorField.model_validate(f))
            except Exception as exc:  # 单字段失败不阻塞全表
                import logging
                logging.getLogger(__name__).warning(
                    "[architect] 跳过非法字段 %s: %s", i, exc
                )

        if not fields:
            raise ValueError("monitor_matrix 解析为空")

        return MonitorMatrix(
            thesis_card_id=payload.thesis_card_id,
            target_company=payload.target_company,
            symbol=payload.symbol,
            monitor_matrix=fields,
            metadata=metadata,
        )

    def fallback(
        self, payload: ArchitectInput, metadata: CallMetadata, *, reason: str
    ) -> MonitorMatrix:
        """fallback：基于 logic_chain_nodes 生成最低限度的 P7 关键词字段。"""
        first_node = payload.logic_chain_nodes[0]
        fields = [
            MonitorField(
                field_id="field_fallback_keyword",
                probe_id="P7",
                metric_name=f"{first_node} 行业新闻关键词监控",
                data_source_type="WEB_SCRAPING",
                source_api=None,
                source_url="https://www.eastmoney.com/news",
                specific_target=f"关键词组：{first_node}",
                keywords=[first_node],
                alert_threshold="每日新闻命中关键词 ≥ 3 条",
                alert_threshold_struct=AlertThresholdStruct(
                    operator="gt", value=3.0, window_days=1
                ),
                polling_frequency="daily",
                mapped_logic_chain_nodes=[first_node],
                status="active",
            )
        ]
        return MonitorMatrix(
            thesis_card_id=payload.thesis_card_id,
            target_company=payload.target_company,
            symbol=payload.symbol,
            monitor_matrix=fields,
            metadata=metadata,
        )
