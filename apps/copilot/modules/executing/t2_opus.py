"""T2 Opus 决断（无 Key 则显式 pending · 禁止 mock）。

[Ref: 28_ §6 · 共享规约 26 — 仅 Opus 走 ANTHROPIC_HTTPS_PROXY]
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _t2_model() -> str:
    return (
        os.environ.get("EXECUTING_T2_MODEL", "").strip()
        or os.environ.get("LIGHTHOUSE_REMOTE_MODEL", "").strip()
        or os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")
    )


def run_t2_audit(telemetry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """返回 (audit_json, status) status=ok|pending|error"""
    from apps.copilot.modules.executing.t1_build import telemetry_probe_stats

    coverage = telemetry_probe_stats(telemetry)

    if os.environ.get("EXECUTING_T2_ENABLED", "").lower() not in ("1", "true", "yes"):
        return (
            {
                "Executing_Daily_Audit": {
                    "L3_Fundamental_Verdict": "T2 未启用（EXECUTING_T2_ENABLED）",
                    "L4_Microstructure_Verdict": "—",
                },
                "Reasoning_Engine": {"signal_conflicts": "", "cross_validation_logic": ""},
                "Execution_Command": {
                    "action": "hold",
                    "stop_loss_line": "待 T2 启用后生成",
                    "one_sentence_summary": "仅 T1 遥测完成，Opus 决断未执行",
                },
                "probe_coverage": {
                    "filled": coverage["filled"],
                    "missing": coverage["missing"],
                    "degraded_probes": coverage["degraded_probes"],
                    "data_integrity": coverage.get("data_integrity"),
                },
            },
            "pending",
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return (
            {"error": "ANTHROPIC_API_KEY 未配置"},
            "pending",
        )

    model = _t2_model()
    from apps.copilot.modules.executing.t2_preexec_envelope import (
        build_executing_opus_messages,
        build_t2_preexec_envelope,
    )

    envelope = build_t2_preexec_envelope(telemetry)
    messages = build_executing_opus_messages(envelope)

    try:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        disp = AIDispatcher.default()
        resp = disp.call(
            "radar_assess",
            messages,
            max_tokens=4096,
            temperature=0.2,
            force_route="remote",
            model_override=model,
        )
        text = resp.text or "{}"
        start = text.find("{")
        end = text.rfind("}") + 1
        audit = json.loads(text[start:end]) if start >= 0 and end > start else {"raw": text[:2000]}
        audit.setdefault("meta", {})
        audit["meta"]["model"] = resp.model or model
        audit["meta"]["route"] = resp.route
        audit["meta"]["latency_ms"] = resp.latency_ms
        if anthropic_proxy := os.environ.get("ANTHROPIC_HTTPS_PROXY", "").strip():
            # 仅记录是否配置代理，不写入 URL（含凭证）
            audit["meta"]["anthropic_proxy_configured"] = bool(anthropic_proxy)
        return audit, "ok"
    except BudgetExceededError as exc:
        logger.warning("T2 budget exceeded: %s", exc)
        return {"error": str(exc)[:500]}, "pending"
    except Exception as exc:
        logger.exception("T2 Opus failed")
        return {"error": str(exc)[:500]}, "error"
