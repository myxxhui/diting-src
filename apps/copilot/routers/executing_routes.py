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
from apps.copilot.modules.executing.profile import L3_KEYS, L4_KEYS
from apps.copilot.modules.executing.pipeline_status import build_sync_status
from apps.copilot.modules.executing.positions import (
    delete_position,
    list_positions,
    profit_context,
    upsert_position,
)
from apps.copilot.modules.executing.symbol_base import load_symbol_base
from apps.copilot.modules.executing.universe import load_executing_collect_symbols
from apps.copilot.modules.executing.workspace_settings import (
    get_workspace_settings,
    save_workspace_settings,
)
from apps.copilot.services.redis_wait import wait_for_sync_redis

logger = logging.getLogger(__name__)
router = APIRouter(tags=["executing"])


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


@router.get("/api/executing/settings")
async def api_get_settings(session: AsyncSession = Depends(get_db)):
    settings = await get_workspace_settings(session)
    symbols = await load_executing_collect_symbols(session)
    bases = [await load_symbol_base(session, s) for s in symbols]
    return {**settings, "symbols": bases}


@router.post("/api/executing/settings/save")
async def api_save_settings_form(
    available_cash: float | None = Form(None),
    session: AsyncSession = Depends(get_db),
):
    await save_workspace_settings(session, available_cash=available_cash)
    await session.commit()
    return await api_settings_html(session)


@router.put("/api/executing/settings")
async def api_put_settings(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db),
):
    cash = body.get("available_cash")
    row = await save_workspace_settings(
        session,
        available_cash=float(cash) if cash is not None else None,
    )
    await session.commit()
    return {
        "available_cash": float(row.available_cash) if row.available_cash is not None else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/api/executing/settings-html", response_class=HTMLResponse)
async def api_settings_html(session: AsyncSession = Depends(get_db)):
    settings = await get_workspace_settings(session)
    cash = settings.get("available_cash")
    return HTMLResponse(
        f"""
<div id="executing-global-settings" class="border border-emerald-200 rounded-lg p-4 mb-4 bg-emerald-50/60">
  <h3 class="font-semibold text-emerald-900 mb-2">执行区全局 · 账户可用资金</h3>
  <form hx-post="/api/executing/settings/save" hx-target="#executing-global-settings" hx-swap="outerHTML"
        class="flex flex-wrap items-end gap-3 text-sm">
    <label class="flex flex-col gap-1">可用资金（元）
      <input name="available_cash" type="number" step="0.01" min="0"
        class="border rounded px-2 py-1 w-48 bg-white"
        value="{_esc(cash if cash is not None else '')}" placeholder="如 500000">
    </label>
    <button type="submit" class="px-4 py-1.5 rounded bg-emerald-700 text-white hover:bg-emerald-800">
      保存全局设置
    </button>
    <span class="text-xs text-emerald-800">与下方各标的持仓一并写入数据库 · 作为 T1 基础输入</span>
  </form>
</div>
"""
    )


@router.get("/api/executing/positions")
async def api_list_positions(session: AsyncSession = Depends(get_db)):
    symbols = await load_executing_collect_symbols(session)
    out = []
    for sym in symbols:
        base = await load_symbol_base(session, sym)
        if base.get("has_base"):
            out.append(base)
    if not out:
        rows = await list_positions(session)
        out = [
            {
                "symbol": r.symbol,
                "name": r.name,
                "quantity": r.quantity,
                "cost_price": r.cost_price,
                "position_pct": r.position_pct,
                "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                "notes": r.notes,
            }
            for r in rows
        ]
    return out


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
    opened_at: str = Form(""),
    notes: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """HTMX 表单保存标的基础数据（持仓 + 执行列表同步）。"""
    body: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "quantity": quantity,
        "cost_price": cost_price,
        "position_pct": position_pct,
        "opened_at": opened_at or None,
        "notes": notes,
        "source": "ui",
    }
    await upsert_position(session, body)
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


@router.get("/api/executing/t1-batch")
async def api_t1_batch(session: AsyncSession = Depends(get_db)):
    """T1 整包 JSON（batch_meta + portfolio_signals）· 不触发 T2。"""
    from apps.copilot.modules.executing.t1_assembler import assemble_batch_portfolio

    redis = wait_for_sync_redis()
    symbols = await load_executing_collect_symbols(session)
    if not symbols:
        symbols = [r.symbol for r in await list_positions(session)]
    telemetry = await assemble_batch_portfolio(session, symbols, redis_client=redis)
    return telemetry


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
    audit = audit_row.audit_json if audit_row else {}

    base = await load_symbol_base(session, sym)
    opened_val = ctx.get("opened_at") or base.get("opened_at") or ""
    if opened_val and "T" in str(opened_val):
        opened_val = str(opened_val)[:10]
    notes_val = base.get("notes") or ""

    from apps.copilot.modules.executing.money_unit import (
        EXECUTING_MONEY_UNIT,
        format_price_display,
    )

    money_hint = f"货币单位：<strong>{_esc(EXECUTING_MONEY_UNIT)}</strong>"
    mark_disp = format_price_display(ctx.get("mark_price"))
    cost_disp = format_price_display(ctx.get("cost_price"))
    pos_form = f"""
<div class="executing-position-card bg-white border border-gray-200 rounded-xl shadow-sm p-6 mb-4">
  <h3 class="text-base font-semibold text-gray-900 mb-1">层 A · 标的基础数据 · {_esc(sym)}</h3>
  <p class="text-xs text-gray-400 mb-1">保存后同步写入 <code class="text-[11px] bg-gray-100 px-1 rounded">user_positions</code> 与 <code class="text-[11px] bg-gray-100 px-1 rounded">executing_collect_symbols</code></p>
  <p class="text-xs text-gray-500 mb-4">{money_hint} · 价格字段均为此单位</p>
  <form hx-post="/api/executing/positions/{sym}/save" hx-target="#executing-detail-{sym}" hx-swap="outerHTML"
        class="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
    <label class="flex flex-col gap-1 text-gray-700">名称
      <input name="name" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value="{_esc(ctx.get('name',''))}">
    </label>
    <label class="flex flex-col gap-1 text-gray-700">持股数量
      <input name="quantity" type="number" step="any" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        value="{_esc(ctx.get('quantity',''))}">
    </label>
    <label class="flex flex-col gap-1 text-gray-700">成本价（{EXECUTING_MONEY_UNIT}）
      <input name="cost_price" type="number" step="0.0001" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        value="{_esc(ctx.get('cost_price',''))}">
    </label>
    <label class="flex flex-col gap-1 text-gray-700">占仓位（%）
      <input name="position_pct" type="number" step="0.0001" min="0" max="100"
        class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value="{_esc(ctx.get('position_pct',''))}"
        placeholder="如 29.37">
    </label>
    <label class="flex flex-col gap-1 text-gray-700">建仓时间
      <input name="opened_at" type="date" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
        value="{_esc(opened_val)}" required>
    </label>
    <label class="flex flex-col gap-1 md:col-span-1 text-gray-700">备注
      <input name="notes" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value="{_esc(notes_val)}">
    </label>
    <div class="col-span-2 md:col-span-3 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5">
      现价 <strong class="text-gray-900">{_esc(mark_disp)}</strong>
      · 成本 <strong class="text-gray-900">{_esc(cost_disp)}</strong>
      · 浮盈 <strong class="text-emerald-500">{_esc(ctx.get('unrealized_pnl_pct','—'))}%</strong>
      · 仓位 <strong class="text-gray-900">{_esc(ctx.get('position_pct','—'))}%</strong>
      {'· <span class="text-amber-600">行情 stale</span>' if ctx.get('price_stale') else ''}
    </div>
    <button type="submit" class="col-span-2 md:col-span-3 bg-blue-600 text-white rounded-lg py-2.5 hover:bg-blue-700 font-medium transition-colors">
      保存标的基础数据
    </button>
  </form>
</div>
"""

    from apps.copilot.modules.executing.executing_render import (
        _quote_intraday_watermark,
        render_degraded_probes,
        render_hot_data_timeline,
        render_layer_b_prerequisite_banner,
        render_probe_domain,
    )
    from apps.copilot.modules.executing.t1_assembler import assemble_stock_signal

    has_entry = bool(str(opened_val or "").strip())
    degraded_hints: list[str] = []
    l3: dict = {}
    l4: dict = {}
    layer_b_banner = ""
    if not has_entry:
        layer_b_banner = render_layer_b_prerequisite_banner()
    else:
        signal = await assemble_stock_signal(session, sym, redis_client=redis)
        indicators = signal.get("indicators") or {}
        l3 = {k: v for k, v in indicators.items() if k in L3_KEYS}
        l4 = {k: v for k, v in indicators.items() if k in L4_KEYS}
        degraded_hints = list(signal.get("degraded_probes") or [])

    cmd_root = (audit.get("Execution_Command") or {}) if isinstance(audit, dict) else {}
    code_key = f"{sym}.{'SH' if sym.startswith('6') else 'SZ'}"
    if isinstance(cmd_root, dict) and code_key in cmd_root:
        cmd = cmd_root[code_key]
    elif isinstance(cmd_root, dict) and "action" in cmd_root:
        cmd = cmd_root
    elif isinstance(cmd_root, dict) and len(cmd_root) == 1:
        cmd = next(iter(cmd_root.values()), {})
    else:
        cmd = cmd_root if isinstance(cmd_root, dict) else {}

    toolbar = f"""
<div class="flex gap-2 mb-4 flex-wrap text-sm">
  <button class="px-3 py-1.5 bg-gray-900 text-white rounded-lg hover:bg-gray-800 font-medium transition-colors"
    hx-post="/api/executing/{sym}/daily-run-html" hx-target="#executing-detail-{sym}" hx-swap="outerHTML">
    立即跑今日体检
  </button>
  <button class="px-3 py-1.5 border border-gray-200 bg-white text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
    hx-get="/api/executing/sync-status" hx-target="#executing-sync-badge" hx-swap="innerHTML">
    检查数据同步
  </button>
  <span id="executing-sync-badge" class="text-xs text-gray-500 self-center">
    同步：stale {sync.get('stale_count',0)} · missing {sync.get('missing_count',0)}
  </span>
</div>
"""

    audit_html = f"""
<article class="bg-white border border-gray-200 rounded-xl shadow-sm p-6 mb-4">
  <h3 class="text-base font-semibold text-gray-900 mb-3 pb-2 border-b border-gray-200">层 C · T2 风控日报</h3>
  <p class="text-sm text-gray-600"><span class="text-gray-400">action</span> <strong class="text-gray-900">{_esc(cmd.get('action','pending'))}</strong></p>
  <p class="text-sm text-gray-600 mt-2 leading-relaxed">{_esc(cmd.get('one_sentence_summary',''))}</p>
  <p class="text-sm text-rose-600 mt-2">硬防线 {_esc(cmd.get('stop_loss_line',''))}</p>
  <p class="text-[11px] text-gray-400 mt-3 pt-2 border-t border-gray-100">t2_status={_esc(audit_row.t2_status if audit_row else 'none')}</p>
</article>
"""

    qmt_node = l4.get("qmt_atr_trailing") if isinstance(l4, dict) else None
    quote_wm = _quote_intraday_watermark(sync, sym)
    hot_timeline = (
        render_hot_data_timeline(qmt_node, quote_job_at=quote_wm)
        if has_entry
        else ""
    )
    layer_b_html = (
        f"{layer_b_banner}"
        f"{render_degraded_probes(degraded_hints)}"
        f"{hot_timeline}"
        f'{render_probe_domain(l4, title="层 B · T1 指标（#15~#20）", accent="orange", empty_hint="暂无可用指标 · 点「立即跑今日体检」或等待 Cron 采集", symbol=sym, sync=sync)}'
    )

    return HTMLResponse(
        f'<div id="executing-detail-{sym}" class="executing-workspace bg-gray-50 rounded-xl p-4 -mx-1">'
        f"{toolbar}{pos_form}"
        f"{layer_b_html}"
        f"{audit_html}"
        f'<p class="text-[11px] text-gray-400 text-center mt-2">advisory only · no-auto-execute · [Ref: 28_]</p></div>'
    )
