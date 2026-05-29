"""Teacher 客户端：Mock / Anthropic；可选调用维度五蒸馏 HTTP。

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import httpx

from apps.cryo_guard.config import settings
from apps.common.no_mock_policy import reject_business_mock

logger = logging.getLogger(__name__)

# 与 super_evo apps/super_evo/api/routes/distill.py 一致
DEFAULT_D5_DISTILL_URL = os.environ.get("CRYO_D5_DISTILL_URL", "http://127.0.0.1:9099/api/distill/single")
MAX_RETRY = 3


@dataclass
class TeacherResponse:
    raw_text: str
    model_id: str
    latency_ms: int
    tokens_in: int
    tokens_out: int


_MOCK_PAYLOADS: dict[str, str] = {
    "financial_fraud": json.dumps(
        {
            "risk_score": 0.25,
            "decision": "pass",
            "features": {
                "cash_debt_anomaly": {"detected": False, "evidence": "mock"},
                "cf_deviation": {"detected": False, "evidence": "mock"},
                "receivable_anomaly": {"detected": False, "evidence": "mock"},
                "inventory_anomaly": {"detected": False, "evidence": "mock"},
                "rd_capitalization_anomaly": {"detected": False, "evidence": "mock"},
                "gross_margin_anomaly": {"detected": False, "evidence": "mock"},
            },
            "summary": "mock 财务结论",
        },
        ensure_ascii=False,
    ),
    "shareholder_integrity": json.dumps(
        {
            "risk_score": 0.3,
            "decision": "pass",
            "categories": {
                "increase_commitment_default": {"detected": False, "evidence": "mock"},
                "decrease_violation": {"detected": False, "evidence": "mock"},
                "performance_pledge_failed": {"detected": False, "evidence": "mock"},
                "pledge_concealment": {"detected": False, "evidence": "mock"},
                "strategy_default": {"detected": False, "evidence": "mock"},
            },
            "summary": "mock 股东结论",
        },
        ensure_ascii=False,
    ),
    "related_party": json.dumps(
        {
            "risk_score": 0.28,
            "decision": "pass",
            "features": {
                "cycle_transaction": {"detected": False, "evidence": "mock"},
                "debt_equity": {"detected": False, "evidence": "mock"},
                "fund_occupation": {"detected": False, "evidence": "mock"},
                "disclosure_anomaly": {"detected": False, "evidence": "mock"},
            },
            "summary": "mock 关联交易结论",
        },
        ensure_ascii=False,
    ),
}


def parse_teacher_output(raw_text: str) -> tuple[dict | None, str]:
    """Teacher 输出严格 JSON；返回 (dict, parse_status)。"""
    txt = raw_text.strip()
    if txt.startswith("```"):
        lines = txt.split("\n")
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        txt = "\n".join(lines).strip()
    try:
        return json.loads(txt), "ok"
    except json.JSONDecodeError as exc:
        logger.warning("JSON 解析失败: %s; raw=%s", exc, txt[:200])
        return None, "json_error"


def _map_engine_to_task_type(engine: str) -> str:
    if engine == "shareholder_integrity":
        return "shareholder"
    return engine


class TeacherClient:
    """Anthropic 或维度五 HTTP；Mock 仅 pytest 内合法。"""

    def __init__(self) -> None:
        self._anthropic = None
        key = os.environ.get("ANTHROPIC_API_KEY") or settings.teacher_api_key
        if key:
            try:
                import anthropic

                self._anthropic = anthropic.Anthropic(api_key=key)
            except ImportError:
                logger.warning("anthropic 未安装，无法直连 Teacher")

    def call(self, engine: str, instruction: str, user_prompt: str) -> TeacherResponse:
        if os.environ.get("CRYO_GUARD_DISTILL_MOCK", "").lower() in ("1", "true", "yes"):
            reject_business_mock("CRYO_GUARD_DISTILL_MOCK", context="Teacher 蒸馏")
            # 仅 pytest 可达
            return TeacherResponse(
                raw_text=_MOCK_PAYLOADS[engine],
                model_id="cryo_mock_teacher",
                latency_ms=1,
                tokens_in=0,
                tokens_out=0,
            )
        if os.environ.get("CRYO_SKIP_D5", "").lower() in ("1", "true", "yes"):
            if self._anthropic:
                logger.info("CRYO_SKIP_D5=1，跳过维度五 HTTP，直接使用 Anthropic")
                return self._call_anthropic(instruction, user_prompt)
            raise RuntimeError(
                "CRYO_SKIP_D5=1 时需配置 ANTHROPIC_API_KEY；业务路径禁止 CRYO_GUARD_DISTILL_MOCK"
            )
        try:
            return self._call_d5(engine, instruction, user_prompt)
        except Exception as exc:
            logger.warning("D5 蒸馏不可用: %s", exc)
        if self._anthropic:
            return self._call_anthropic(instruction, user_prompt)
        raise RuntimeError("请配置 ANTHROPIC_API_KEY 或 CRYO_D5_DISTILL_URL（业务路径禁止 mock Teacher）")

    def _call_d5(self, engine: str, instruction: str, user_prompt: str) -> TeacherResponse:
        """POST DistillInput 形态到维度五 /api/distill/single。"""
        task_type = _map_engine_to_task_type(engine)
        t0 = time.perf_counter()
        payload = {
            "task_type": task_type,
            "raw_data": {"instruction": instruction, "user_prompt": user_prompt},
            "context": {},
            "sample_id": None,
        }
        with httpx.Client(timeout=120.0) as client:
            r = client.post(DEFAULT_D5_DISTILL_URL, json=payload)
            r.raise_for_status()
            js = r.json()
        out = js.get("output")
        if isinstance(out, dict):
            raw = json.dumps(out, ensure_ascii=False)
        else:
            raw = str(out) if out is not None else ""
        meta = js.get("metadata") or {}
        return TeacherResponse(
            raw_text=raw,
            model_id=str(meta.get("teacher_model", "d5_distill")),
            latency_ms=int((time.perf_counter() - t0) * 1000),
            tokens_in=0,
            tokens_out=0,
        )

    def _call_anthropic(self, instruction: str, user_prompt: str) -> TeacherResponse:
        import anthropic

        t0 = time.perf_counter()
        last_exc: Exception | None = None
        model = os.environ.get("ANTHROPIC_MODEL", settings.teacher_model)
        for attempt in range(MAX_RETRY):
            try:
                assert self._anthropic is not None
                msg = self._anthropic.messages.create(
                    model=model,
                    max_tokens=2048,
                    temperature=0.2,
                    system=instruction,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                txt = msg.content[0].text
                return TeacherResponse(
                    raw_text=txt,
                    model_id=model,
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    tokens_in=msg.usage.input_tokens,
                    tokens_out=msg.usage.output_tokens,
                )
            except anthropic.RateLimitError as exc:
                last_exc = exc
                sleep_s = (2**attempt) + 1
                logger.warning("Anthropic 限流，退避 %ss", sleep_s)
                time.sleep(sleep_s)
        raise RuntimeError(f"Anthropic 多次重试失败: {last_exc}")
