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
                    "filled": 25 - len(telemetry.get("unavailable_data", [])),
                    "missing": telemetry.get("unavailable_data", []),
                    "blockers": telemetry.get("blockers", []),
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
    prompt = (
        "你是首席风控官。仅基于下列 T1 遥测 JSON 输出一个 JSON 对象，"
        "结构含 Executing_Daily_Audit, Reasoning_Engine, Execution_Command, probe_coverage。"
        "禁止编造未给出的数字。action 仅 hold|trim_30_pct|dump_all|rotate。\n\n"
        + json.dumps(telemetry, ensure_ascii=False)[:120000]
    )

    try:
        from apps.common.ai_dispatcher import AIDispatcher, BudgetExceededError

        disp = AIDispatcher.default()
        resp = disp.call(
            "radar_assess",
            [{"role": "user", "content": prompt}],
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
