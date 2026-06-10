"""T2 分析 · 手动同步到执行区标的卡（pin）。

[Ref: 28_ §5]
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.modules.executing.t2_advice_summary import (
    _norm_keys,
    extract_symbol_advice,
    structured_audit_from_payload,
)


def _canonical_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        return ""
    if "." in s:
        return s
    if s.startswith(("6", "5", "9")):
        return f"{s}.SH"
    return f"{s}.SZ"


async def pin_t2_to_executing(
    session: AsyncSession,
    *,
    request_id: str,
    symbols: list[str],
) -> dict[str, Any]:
    """将指定 request 同步到执行区各标的卡（须用户显式选择标的）。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest, ExecutingT2ExecutingPin

    rid = (request_id or "").strip()
    if not rid:
        raise ValueError("缺少 request_id")
    syms = [_canonical_symbol(s) for s in symbols if (s or "").strip()]
    syms = [s for s in syms if s]
    if not syms:
        raise ValueError("请先在上方勾选要同步的标的")

    row = await session.scalar(
        select(ExecutingT2AnalystRequest).where(ExecutingT2AnalystRequest.request_id == rid)
    )
    if not row:
        raise ValueError("分析记录不存在")
    if not row.api_connected:
        raise ValueError("该条分析未成功完成，无法同步")

    payload = row.payload_json or {}
    audit = structured_audit_from_payload(payload)
    if not audit.get("Execution_Command") and not audit.get("symbol_audits"):
        raise ValueError("该条分析无有效结构化结论，无法同步")

    pinned: list[str] = []
    skipped: list[dict[str, str]] = []
    now = datetime.utcnow()

    for sym in syms:
        advice = extract_symbol_advice(
            payload,
            sym,
            created_at=row.created_at,
            request_id=rid,
            model_id=row.model_id,
        )
        if not advice:
            skipped.append({"symbol": sym, "reason": "该分析未覆盖此标的"})
            continue

        existing = await session.scalar(
            select(ExecutingT2ExecutingPin).where(ExecutingT2ExecutingPin.symbol == sym)
        )
        if existing:
            existing.request_id = rid
            existing.pinned_at = now
        else:
            session.add(ExecutingT2ExecutingPin(symbol=sym, request_id=rid, pinned_at=now))
        pinned.append(sym)

    await session.flush()
    if not pinned:
        raise ValueError("所选标的均无法从该分析提取摘要")

    return {
        "request_id": rid,
        "pinned_symbols": pinned,
        "skipped": skipped,
        "executing_url": "/planning?view=executing",
    }


async def load_pinned_t2_summaries_for_symbols(
    session: AsyncSession,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """仅加载用户手动 pin 到执行区的 T2 摘要（不再自动取最近一次分析）。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest, ExecutingT2ExecutingPin

    if not symbols:
        return {}

    wanted: dict[str, set[str]] = {s: _norm_keys(s) for s in symbols}
    canon_to_orig: dict[str, str] = {}
    for s in symbols:
        c = _canonical_symbol(s)
        if c:
            canon_to_orig[c] = s
        for k in _norm_keys(s):
            canon_to_orig.setdefault(k.split(".")[0], s)

    pins = (
        await session.scalars(select(ExecutingT2ExecutingPin))
    ).all()
    pin_by_symbol = {p.symbol: p for p in pins}

    found: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        keys = wanted.get(sym) or set()
        pin_row = None
        for k in keys:
            c = _canonical_symbol(k) if len(k) <= 6 else k.upper()
            if c in pin_by_symbol:
                pin_row = pin_by_symbol[c]
                break
            code = k.split(".")[0]
            for ps, pr in pin_by_symbol.items():
                if ps.split(".")[0] == code:
                    pin_row = pr
                    break
            if pin_row:
                break
        if not pin_row:
            continue

        req = await session.scalar(
            select(ExecutingT2AnalystRequest).where(
                ExecutingT2AnalystRequest.request_id == pin_row.request_id
            )
        )
        if not req:
            continue
        payload = req.payload_json or {}
        advice = extract_symbol_advice(
            payload,
            sym,
            created_at=req.created_at,
            request_id=req.request_id,
            model_id=req.model_id,
        )
        if advice:
            advice["pinned"] = True
            advice["pinned_at"] = pin_row.pinned_at
            found[sym] = advice
    return found
