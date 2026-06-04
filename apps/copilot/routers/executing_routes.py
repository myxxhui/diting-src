"""执行中工作区 API + HTMX 片段。

[Ref: 28_ §5.3 §7]
"""
from __future__ import annotations

import html
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.db.models import ExecutingDailyAudit
from apps.copilot.modules.executing.orchestrator import run_daily_pipeline, run_t0_collect
from apps.copilot.modules.executing.pipeline_status import build_sync_status
from apps.copilot.modules.executing.positions import (
    delete_position,
    list_positions,
    profit_context,
    upsert_position,
)
from apps.copilot.modules.executing.universe import upsert_executing_collect
from apps.copilot.services.redis_wait import wait_for_sync_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["executing"])


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


@router.get("/api/executing/positions")
async def api_list_positions(session: AsyncSession = Depends(get_db)):
    rows = await list_positions(session)
    return [
        {
            "symbol": r.symbol,
            "name": r.name,
            "quantity": r.quantity,
            "cost_price": r.cost_price,
            "position_pct": r.position_pct,
            "opened_at": r.opened_at.isoformat() if r.opened_at else None,
            "notes": r.notes,
            "source": r.source,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/api/executing/positions/{symbol}")
async def api_get_position(symbol: str, session: AsyncSession = Depends(get_db)):
    redis = wait_for_sync_redis()
    ctx = await profit_context(session, symbol, redis)
    if not ctx.get("has_position"):
        raise HTTPException(404, "position not found")
    return ctx


@router.post("/api/executing/positions/{symbol}/save")
async def api_save_position_form(
    symbol: str,
    name: str = Form(""),
    quantity: float = Form(0),
    cost_price: float = Form(0),
    position_pct: float | None = Form(None),
    notes: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """HTMX 表单保存持仓。"""
    body: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "quantity": quantity,
        "cost_price": cost_price,
        "position_pct": position_pct,
        "notes": notes,
        "source": "ui",
    }
    row = await upsert_position(session, body)
    await upsert_executing_collect(session, row.symbol, enabled=True)
    await session.commit()
    return await api_executing_detail_html(symbol, session)


@router.put("/api/executing/positions/{symbol}")
async def api_put_position(
    symbol: str,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db),
):
    body["symbol"] = symbol
    body.setdefault("source", "ui")
    row = await upsert_position(session, body)
    await upsert_executing_collect(
        session,
        row.symbol,
        name=row.name,
        enabled=True,
    )
    await session.commit()
    redis = wait_for_sync_redis()
    return await profit_context(session, symbol, redis)


@router.delete("/api/executing/positions/{symbol}")
async def api_delete_position(symbol: str, session: AsyncSession = Depends(get_db)):
    ok = await delete_position(session, symbol)
    if not ok:
        raise HTTPException(404, "not found")
    await session.commit()
    return {"deleted": symbol}


@router.get("/api/executing/sync-status")
async def api_sync_status(session: AsyncSession = Depends(get_db)):
    return await build_sync_status(session)


@router.post("/api/executing/{symbol}/daily-run")
async def api_daily_run(symbol: str, session: AsyncSession = Depends(get_db)):
    redis = wait_for_sync_redis()
    result = await run_daily_pipeline(session, symbol, redis_client=redis)
    await session.commit()
    return result


@router.post("/api/executing/{symbol}/daily-run-html", response_class=HTMLResponse)
async def api_daily_run_html(symbol: str, session: AsyncSession = Depends(get_db)):
    redis = wait_for_sync_redis()
    await run_daily_pipeline(session, symbol, redis_client=redis)
    await session.commit()
    return await api_executing_detail_html(symbol, session)


@router.post("/api/executing/{symbol}/collect")
async def api_collect(symbol: str, session: AsyncSession = Depends(get_db)):
    result = await run_t0_collect(session, symbol)
    await session.commit()
    return result


@router.get("/api/executing/{symbol}/detail", response_class=HTMLResponse)
async def api_executing_detail_html(symbol: str, session: AsyncSession = Depends(get_db)):
    sym = symbol.zfill(6)[-6:]
    redis = wait_for_sync_redis()
    ctx = await profit_context(session, sym, redis)
    sync = await build_sync_status(session)

    audit_row = (
        await session.scalars(
            select(ExecutingDailyAudit)
            .where(ExecutingDailyAudit.symbol == sym)
            .order_by(ExecutingDailyAudit.created_at.desc())
            .limit(1)
        )
    ).first()

    telemetry = audit_row.telemetry_json if audit_row else {}
    audit = audit_row.audit_json if audit_row else {}
    l3 = telemetry.get("L3_Business") or {}
    l4 = telemetry.get("L4_Game") or {}
    cmd = (audit.get("Execution_Command") or {}) if isinstance(audit, dict) else {}

    pos_form = f"""
<div class="executing-position-card border rounded-lg p-4 mb-4 bg-white shadow-sm">
  <h3 class="font-bold text-lg mb-2">层 A · 我的真持仓 · {_esc(sym)}</h3>
  <form hx-post="/api/executing/positions/{sym}/save" hx-target="#executing-detail-{sym}" hx-swap="outerHTML"
        class="grid grid-cols-2 gap-2 text-sm">
    <label>名称 <input name="name" class="border rounded px-2 w-full" value="{_esc(ctx.get('name',''))}"></label>
    <label>持股数量 <input name="quantity" type="number" step="any" class="border rounded px-2 w-full"
      value="{_esc(ctx.get('quantity',''))}"></label>
    <label>成本价 <input name="cost_price" type="number" step="0.0001" class="border rounded px-2 w-full"
      value="{_esc(ctx.get('cost_price',''))}"></label>
    <label>仓位% <input name="position_pct" type="number" step="0.1" class="border rounded px-2 w-full"
      value="{_esc(ctx.get('position_pct',''))}"></label>
    <label class="col-span-2">备注 <input name="notes" class="border rounded px-2 w-full"></label>
    <div class="col-span-2 text-gray-600">
      现价 {_esc(ctx.get('mark_price','—'))}
      · 浮盈 {_esc(ctx.get('unrealized_pnl_pct','—'))}%
      {'· <span class="text-amber-600">行情stale</span>' if ctx.get('price_stale') else ''}
    </div>
    <button type="submit" class="col-span-2 bg-blue-600 text-white rounded py-2">保存到数据库</button>
  </form>
</div>
"""

    def _probe_rows(domain: dict, title: str, color: str) -> str:
        rows = []
        for k, node in domain.items():
            if not isinstance(node, dict):
                continue
            val = node.get("value")
            st = "ok" if val is not None else "missing"
            dot = "🟢" if st == "ok" else "🔴"
            rows.append(
                f"<tr><td class='font-mono text-xs'>{_esc(k)}</td>"
                f"<td>{dot} {_esc(val)}</td>"
                f"<td class='text-xs text-gray-600'>{_esc(node.get('fact_statement',''))[:80]}</td></tr>"
            )
        body = "".join(rows) or "<tr><td colspan='3'>尚无 T1 数据 · 点击下方采集</td></tr>"
        return f"""
<div class="border-l-4 border-{color}-500 pl-3 mb-4">
  <h4 class="font-semibold mb-2">{_esc(title)}</h4>
  <table class="w-full text-sm"><thead><tr><th>探针</th><th>值</th><th>事实</th></tr></thead><tbody>{body}</tbody></table>
</div>
"""

    toolbar = f"""
<div class="flex gap-2 mb-3 flex-wrap text-sm">
  <button class="px-3 py-1 bg-indigo-600 text-white rounded"
    hx-post="/api/executing/{sym}/daily-run-html" hx-target="#executing-detail-{sym}" hx-swap="outerHTML">
    立即跑今日体检
  </button>
  <button class="px-3 py-1 border rounded"
    hx-get="/api/executing/sync-status" hx-target="#executing-sync-badge" hx-swap="innerHTML">
    检查数据同步
  </button>
  <span id="executing-sync-badge" class="text-amber-700">
    同步：stale {sync.get('stale_count',0)} · missing {sync.get('missing_count',0)}
  </span>
</div>
"""

    audit_html = f"""
<div class="border rounded-lg p-4 bg-slate-50">
  <h3 class="font-bold mb-2">层 C · T2 风控日报</h3>
  <p><strong>action</strong> {_esc(cmd.get('action','pending'))}</p>
  <p class="text-sm">{_esc(cmd.get('one_sentence_summary',''))}</p>
  <p class="text-sm text-red-700">硬防线 {_esc(cmd.get('stop_loss_line',''))}</p>
  <p class="text-xs text-gray-500">t2_status={_esc(audit_row.t2_status if audit_row else 'none')}</p>
</div>
"""

    return HTMLResponse(
        f'<div id="executing-detail-{sym}" class="executing-workspace">'
        f"{toolbar}{pos_form}"
        f'<div class="border rounded-lg p-4 mb-4">{_probe_rows(l3, "层 B · L3 宏观与产业链", "blue")}'
        f'{_probe_rows(l4, "层 B · L4 资金博弈", "orange")}</div>'
        f"{audit_html}"
        f'<p class="text-xs text-gray-400 mt-2">advisory only · no-auto-execute · [Ref: 28_]</p></div>'
    )
