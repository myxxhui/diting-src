"""执行区标的卡 · 最近一次 T2 持仓分析摘要（来自 executing_t2_analyst_requests）。

[Ref: 28_ §5]
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.t2_analyst import _parse_opus_audit_json

_ACTION_LABELS: dict[str, str] = {
    "hold": "持有",
    "trim": "减持",
    "trim_30_pct": "减持 30%",
    "dump": "清仓",
    "dump_all": "全部清仓",
    "rotate": "换股",
    "watch": "观察",
}


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _norm_keys(symbol: str) -> set[str]:
    s = (symbol or "").strip().upper()
    if not s:
        return set()
    keys = {s, s.lower()}
    code = s.split(".")[0] if "." in s else s[-6:]
    for suffix in ("SH", "SZ", "BJ"):
        keys.add(f"{code}.{suffix}")
        keys.add(f"{code}.{suffix.lower()}")
    return keys


def _match_symbol(audit_syms: dict[str, Any], symbol: str) -> str | None:
    wanted = _norm_keys(symbol)
    for k in audit_syms:
        if k in wanted or k.split(".")[0] in {w.split(".")[0] for w in wanted}:
            return k
    return None


def structured_audit_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """从 payload 取可渲染 audit；必要时用 opus_raw_text 重新解析。"""
    audit = payload.get("opus_audit") or {}
    if isinstance(audit, dict) and (
        audit.get("Execution_Command") or audit.get("symbol_audits")
    ):
        return audit
    raw = payload.get("opus_raw_text") or audit.get("raw_text") or ""
    if raw:
        reparsed = _parse_opus_audit_json(str(raw))
        if reparsed.get("Execution_Command") or reparsed.get("symbol_audits"):
            return reparsed
    return audit if isinstance(audit, dict) else {}


def extract_symbol_advice(
    payload: dict[str, Any],
    symbol: str,
    *,
    created_at: datetime | None = None,
    request_id: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    """从单次 T2 payload 提取单标的摘要。"""
    audit = structured_audit_from_payload(payload)
    if not audit.get("Execution_Command") and not audit.get("symbol_audits"):
        return None

    sym_audits = audit.get("symbol_audits") or {}
    matched = _match_symbol(sym_audits, symbol)
    sym_audit = sym_audits.get(matched or "") or {}

    cmd = audit.get("Execution_Command") or {}
    action = sym_audit.get("near_term_advice") or cmd.get("action") or "—"
    target = next(
        (
            t
            for t in (cmd.get("targets") or [])
            if _match_symbol({t.get("symbol", ""): t}, symbol)
        ),
        None,
    )
    if target and target.get("advice"):
        action = target.get("advice")

    summary = (cmd.get("one_sentence_summary") or "").strip()
    core = (sym_audit.get("cross_validation") or "").strip()
    if not core:
        core = ((audit.get("Reasoning_Engine") or {}).get("cross_validation_logic") or "").strip()
    honesty = (sym_audit.get("holding_honesty") or "").strip()
    if target and target.get("rationale") and not summary:
        summary = str(target.get("rationale"))

    return {
        "request_id": request_id,
        "model_id": model_id or payload.get("model_id"),
        "analyzed_at": created_at,
        "action": action,
        "action_label": _ACTION_LABELS.get(str(action).lower(), str(action)),
        "summary": summary[:280],
        "core_eval": core[:320],
        "operation_hint": honesty[:320] or summary[:200],
    }


async def load_latest_t2_summaries_for_symbols(
    session: AsyncSession,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """按标的取最近一次成功解析的 T2 分析摘要。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest

    if not symbols:
        return {}

    wanted: dict[str, set[str]] = {s: _norm_keys(s) for s in symbols}
    found: dict[str, dict[str, Any]] = {}

    rows = (
        await session.scalars(
            select(ExecutingT2AnalystRequest)
            .where(ExecutingT2AnalystRequest.api_connected.is_(True))
            .order_by(ExecutingT2AnalystRequest.created_at.desc())
            .limit(120)
        )
    ).all()

    for row in rows:
        payload = row.payload_json or {}
        if isinstance(payload, str):
            payload = json.loads(payload)
        row_syms = row.symbols_json or payload.get("symbols") or []
        for sym in symbols:
            if sym in found:
                continue
            keys = wanted.get(sym) or set()
            if not any(rs in keys or rs.split(".")[0] in {k.split(".")[0] for k in keys} for rs in row_syms):
                continue
            advice = extract_symbol_advice(
                payload,
                sym,
                created_at=row.created_at,
                request_id=row.request_id,
                model_id=row.model_id,
            )
            if advice:
                found[sym] = advice
        if len(found) >= len(symbols):
            break
    return found


def render_executing_t2_banner(sym: str, advice: dict[str, Any] | None) -> str:
    """执行区标的卡顶端 · T2 分析摘要条。"""
    if not advice:
        return (
            f"<div class='rounded-t-xl border border-b-0 border-gray-200 bg-gray-50/80 px-5 py-2.5 "
            f"text-[11px] text-gray-500' data-symbol='{_esc(sym)}'>"
            f"暂无同步到执行区的 T2 分析 · 在 <a href='/opus' class='underline text-indigo-600'>Opus 分析</a> 回复菜单中选择「同步到执行区」</div>"
        )

    ts = advice.get("analyzed_at")
    ts_s = ts.strftime("%Y-%m-%d %H:%M") if isinstance(ts, datetime) else "—"
    rid = advice.get("request_id") or ""
    audit_link = (
        f"<a href='/audit?t2_id={_esc(rid)}' class='underline text-indigo-600'>审计 {_esc(rid[:8])}</a>"
        if rid
        else ""
    )
    model = advice.get("model_id") or "—"
    action_label = _esc(advice.get("action_label") or advice.get("action") or "—")
    summary = _esc(advice.get("summary") or "")
    core = _esc(advice.get("core_eval") or "")
    op = _esc(advice.get("operation_hint") or "")

    core_block = f"<p class='text-xs text-indigo-900/90 mt-1 leading-relaxed'>{core}</p>" if core else ""
    op_block = (
        f"<p class='text-[11px] text-indigo-800/80 mt-1 leading-relaxed'>"
        f"<span class='text-indigo-500'>操作建议 · </span>{op}</p>"
        if op and op != summary
        else ""
    )

    return (
        f"<div class='rounded-t-xl border border-b-0 border-indigo-200 bg-gradient-to-r from-indigo-50 "
        f"to-violet-50 px-5 py-3' data-symbol='{_esc(sym)}' data-t2-request='{_esc(rid)}'>"
        f"<div class='flex flex-wrap items-center justify-between gap-2 text-[10px] text-indigo-600'>"
        f"<span>执行区 T2 · {_esc(ts_s)} · 模型 {_esc(model)}</span>"
        f"<span>{audit_link}</span></div>"
        f"<div class='flex flex-wrap items-center gap-2 mt-1'>"
        f"<span class='text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-600 text-white'>"
        f"{action_label}</span>"
        f"<p class='text-sm font-medium text-indigo-950 flex-1 min-w-[12rem]'>{summary or core[:120] or '—'}</p>"
        f"</div>{core_block}{op_block}</div>"
    )
