"""执行中工作区 API + HTMX 片段。

[Ref: 28_ §5.3 §7]
"""
from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Any

from pathlib import Path

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.database import get_db
from apps.copilot.db.models import ExecutingDailyAudit
from apps.copilot.modules.executing.orchestrator import run_daily_pipeline, run_t0_collect
from apps.copilot.modules.executing.profile import L4_KEYS, load_profile, profile_l3_keys
from apps.copilot.modules.executing.pipeline_status import build_sync_status
from apps.copilot.modules.executing.positions import (
    delete_position,
    list_positions,
    overlay_intraday_qmt_price,
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
_templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates"),
)


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def _redis_for_panel() -> Any:
    """面板加载用 Redis：短超时，失败则 None（避免 HTMX 卡 120s 空白）。"""
    try:
        return wait_for_sync_redis(timeout_sec=3.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("执行区面板 Redis 未就绪，降级无 Redis: %s", exc)
        return None


async def _load_analyst_symbol_rows(
    session: AsyncSession,
    redis: Any,
) -> list[dict[str, Any]]:
    """与执行区标的卡对齐：funnel executing ∪ executing_collect ∪ user_positions。"""
    from apps.copilot.modules.planning.service import list_workspace_symbols

    seen: set[str] = set()
    ordered: list[str] = []

    for item in await list_workspace_symbols(session, view="executing"):
        sym = str(item.get("symbol") or "").zfill(6)[-6:]
        if sym and sym not in seen:
            seen.add(sym)
            ordered.append(sym)

    for sym in await load_executing_collect_symbols(session):
        s = str(sym).zfill(6)[-6:]
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)

    for row in await list_positions(session):
        s = str(row.symbol).zfill(6)[-6:]
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)

    symbol_rows: list[dict[str, Any]] = []
    for sym in ordered:
        ctx = await profit_context(session, sym, redis)
        if not ctx.get("has_position"):
            base = await load_symbol_base(session, sym)
            ctx = {
                "symbol": sym,
                "has_position": bool(base.get("has_base")),
                "name": base.get("name"),
                "quantity": base.get("quantity"),
                "mark_price": None,
                "position_pct": base.get("position_pct"),
                "unrealized_pnl_pct": None,
                "cost_price": base.get("cost_price"),
            }
        symbol_rows.append(
            {
                "symbol": sym,
                "name": ctx.get("name"),
                "quantity": ctx.get("quantity"),
                "mark_price": ctx.get("mark_price"),
                "position_pct": ctx.get("position_pct"),
                "unrealized_pnl_pct": ctx.get("unrealized_pnl_pct"),
                "cost_price": ctx.get("cost_price"),
                "price_stale": ctx.get("price_stale"),
            }
        )
    return symbol_rows


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


@router.get("/api/executing/positions/{symbol}/mark-strip", response_class=HTMLResponse)
async def api_position_mark_strip(symbol: str, session: AsyncSession = Depends(get_db)):
    """层 A 现价条 · HTMX 轮询（与热数据 Redis 同源）。"""
    sym = symbol.zfill(6)[-6:]
    redis = _redis_for_panel()
    ctx = await profit_context(session, sym, redis)
    if not ctx.get("has_position"):
        return HTMLResponse("", status_code=404)
    return HTMLResponse(_render_mark_price_strip(sym, ctx))


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
    return await api_executing_detail_html(symbol, session=session)


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
    redis = _redis_for_panel()
    await run_daily_pipeline(session, symbol, redis_client=redis)
    await session.commit()
    return await api_executing_detail_html(symbol, session, live=True)


@router.post("/api/executing/{symbol}/collect")
async def api_collect(symbol: str, session: AsyncSession = Depends(get_db)):
    result = await run_t0_collect(session, symbol)
    await session.commit()
    return result


@router.post("/api/executing/{symbol}/enroll-collect", response_class=HTMLResponse)
async def api_enroll_collect(symbol: str, session: AsyncSession = Depends(get_db)):
    """待建仓标的入采集宇宙 · 开放层 B 独立 JL4（不要求成本/建仓日）。"""
    from apps.copilot.modules.executing.universe import enroll_executing_collect

    sym = symbol.zfill(6)[-6:]
    await enroll_executing_collect(session, sym)
    await session.commit()
    return await api_executing_detail_html(sym, session=session)


@router.get("/api/executing/{symbol}/detail", response_class=HTMLResponse)
async def api_executing_detail_html(
    symbol: str,
    live: bool = False,
    session: AsyncSession = Depends(get_db),
):
    """执行区单标的详情 · 默认读 PG 快照（秒开）；live=1 时触发 T1 live 装配。"""
    sym = symbol.zfill(6)[-6:]
    redis = _redis_for_panel()
    try:
        return await _render_executing_detail_html(
            sym,
            session,
            redis_client=redis,
            live=live,
        )
    except Exception as exc:
        logger.exception("执行区详情渲染失败 symbol=%s", sym)
        await session.rollback()
        return HTMLResponse(
            f'<div id="executing-detail-body-{sym}" data-detail-state="error" data-symbol="{sym}" '
            f'class="executing-detail-body executing-workspace bg-rose-50 rounded-xl p-4 border border-rose-200">'
            f'<p class="text-sm text-rose-800">加载 JL 指标失败：{_esc(str(exc)[:300])}</p>'
            f'<p class="text-xs text-rose-600 mt-2">可点「立即跑今日体检」重试，或刷新页面。</p></div>',
            status_code=200,
        )


def _render_mark_price_strip(sym: str, ctx: dict[str, Any]) -> str:
    from apps.copilot.modules.executing.money_unit import format_price_display

    mark_disp = format_price_display(ctx.get("mark_price"))
    cost_disp = format_price_display(ctx.get("cost_price"))
    as_of = ctx.get("mark_price_as_of")
    as_of_html = (
        f" · 行情 {_esc(str(as_of)[:19])}"
        if as_of and not ctx.get("price_stale")
        else ""
    )
    stale_html = ' · <span class="text-amber-600">行情 stale</span>' if ctx.get("price_stale") else ""
    return f"""
<div id="executing-mark-{sym}" class="col-span-2 md:col-span-3 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2.5"
     hx-get="/api/executing/positions/{sym}/mark-strip"
     hx-trigger="every 60s"
     hx-target="this"
     hx-swap="outerHTML"
     hx-disinherit="hx-target hx-swap">
  现价 <strong class="text-gray-900">{_esc(mark_disp)}</strong>
  · 成本 <strong class="text-gray-900">{_esc(cost_disp)}</strong>
  · 浮盈 <strong class="text-emerald-500">{_esc(ctx.get('unrealized_pnl_pct','—'))}%</strong>
  · 仓位 <strong class="text-gray-900">{_esc(ctx.get('position_pct','—'))}%</strong>
  {as_of_html}{stale_html}
</div>
"""


async def _render_executing_detail_html(
    sym: str,
    session: AsyncSession,
    *,
    redis_client: Any,
    live: bool = False,
) -> HTMLResponse:
    ctx = await profit_context(session, sym, redis_client)
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
    from apps.copilot.modules.executing.position_lifecycle import (
        LIFECYCLE_HOLDING,
        LIFECYCLE_PENDING_BUILD,
        filter_l4_for_lifecycle,
        is_collect_enrolled,
        resolve_lifecycle_status,
    )

    lifecycle = resolve_lifecycle_status(base)
    in_collect = is_collect_enrolled(base)
    opened_val = ctx.get("opened_at") or base.get("opened_at") or ""
    if opened_val and "T" in str(opened_val):
        opened_val = str(opened_val)[:10]
    notes_val = base.get("notes") or ""
    from apps.copilot.modules.executing.money_unit import EXECUTING_MONEY_UNIT

    money_hint = f"货币单位：<strong>{_esc(EXECUTING_MONEY_UNIT)}</strong>"
    mark_strip = _render_mark_price_strip(sym, ctx) if lifecycle == LIFECYCLE_HOLDING else ""
    enroll_btn = ""
    if not in_collect:
        enroll_btn = f"""
  <form hx-post="/api/executing/{sym}/enroll-collect" hx-target="#executing-detail-body-{sym}" hx-swap="innerHTML" class="mb-3">
    <button type="submit" class="text-sm px-3 py-1.5 rounded-lg bg-sky-600 text-white hover:bg-sky-700 font-medium">
      加入数据获取列表
    </button>
    <span class="text-xs text-gray-500 ml-2">入表后 Cron 采集 JL4 · 待建仓亦可跟踪盘面指标</span>
  </form>
"""
    from apps.copilot.modules.executing.executing_render import (
        _quote_intraday_watermark,
        build_layer_a_header_summary,
        render_degraded_probes,
        render_hot_data_timeline,
        render_layer_b_collect_gate_banner,
        render_layer_b_pending_build_banner,
        render_l3_probe_domain,
        render_probe_domain,
        render_qmt_atr_pending_placeholder,
        wrap_executing_layer_a_section,
    )

    lifecycle_label = "持仓中" if lifecycle == LIFECYCLE_HOLDING else "待建仓"
    layer_a_summary = build_layer_a_header_summary(
        ctx, sym=sym, lifecycle_label=lifecycle_label
    )
    pos_form_inner = f"""
  {enroll_btn}
  <p class="text-xs text-gray-400 mb-1">保存后同步写入 <code class="text-[11px] bg-gray-100 px-1 rounded">user_positions</code> 与 <code class="text-[11px] bg-gray-100 px-1 rounded">executing_collect_symbols</code></p>
  <p class="text-xs text-gray-500 mb-4">{money_hint} · 价格字段均为此单位 · 现价随热数据 Cron 刷新（约 60s 自动更新）</p>
  {mark_strip}
  <form hx-post="/api/executing/positions/{sym}/save" hx-target="#executing-detail-body-{sym}" hx-swap="innerHTML"
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
        value="{_esc(opened_val)}" placeholder="持仓后填写 · 待建仓可留空">
    </label>
    <label class="flex flex-col gap-1 md:col-span-1 text-gray-700">备注
      <input name="notes" class="border border-gray-200 rounded-lg px-2 py-1.5 w-full focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400" value="{_esc(notes_val)}">
    </label>
    <button type="submit" class="col-span-2 md:col-span-3 bg-blue-600 text-white rounded-lg py-2.5 hover:bg-blue-700 font-medium transition-colors">
      保存标的基础数据
    </button>
  </form>
"""
    pos_form = wrap_executing_layer_a_section(
        f'<div class="executing-position-card px-2">{pos_form_inner}</div>',
        header_summary=layer_a_summary,
    )

    from apps.copilot.modules.executing.probe_card_timing import build_probe_card_timing_map
    from apps.copilot.modules.executing.t1_assembler import (
        assemble_stock_signal,
        load_cached_stock_signal,
    )

    has_holding = lifecycle == LIFECYCLE_HOLDING
    layer_b_enabled = in_collect
    prof = load_profile(sym)
    symbol_l3_keys = profile_l3_keys(prof)
    degraded_hints: list[str] = []
    l3: dict = {}
    l4: dict = {}
    event_probe_states: dict[str, dict] = {}
    layer_b_banner = ""
    qmt_pending_html = ""
    cache_note = ""
    if not layer_b_enabled:
        layer_b_banner = render_layer_b_collect_gate_banner()
    elif not has_holding:
        layer_b_banner = render_layer_b_pending_build_banner()
        qmt_pending_html = render_qmt_atr_pending_placeholder()
    if layer_b_enabled:
        if live:
            signal = await assemble_stock_signal(session, sym, redis_client=redis_client)
            cache_note = (
                "<p class='text-[11px] text-blue-700 bg-blue-50 border border-blue-100 "
                "rounded px-2 py-1 mb-3'>已触发 T1 live 装配（较慢 · 结果已写 PG 快照）</p>"
            )
        else:
            signal = await load_cached_stock_signal(session, sym, redis_client=redis_client)
            cache_note = (
                "<p class='text-[11px] text-gray-500 bg-white border border-gray-100 "
                "rounded px-2 py-1 mb-3'>指标来自 PG 快照缓存 · "
                "点「立即跑今日体检」可触发 live 刷新</p>"
            )
        indicators = signal.get("indicators") or {}
        l3 = {k: v for k, v in indicators.items() if k in symbol_l3_keys}
        l4 = {k: v for k, v in indicators.items() if k in L4_KEYS}
        l4 = filter_l4_for_lifecycle(l4, lifecycle)
        if has_holding and isinstance(l4.get("qmt_atr_trailing"), dict):
            l4["qmt_atr_trailing"] = overlay_intraday_qmt_price(
                l4["qmt_atr_trailing"],
                mark_price=ctx.get("mark_price"),
                mark_as_of=ctx.get("mark_price_as_of"),
                stale=bool(ctx.get("price_stale")),
            )
        degraded_hints = list(signal.get("degraded_probes") or [])
        if "block_trade_discount" not in l4:
            from apps.copilot.modules.executing.block_trade_discount import (
                describe_block_trade_ui_state,
                load_block_trade_payload,
            )

            bt_payload = await load_block_trade_payload(
                session, sym, redis_client=redis_client
            )
            event_probe_states["block_trade_discount"] = describe_block_trade_ui_state(bt_payload)
        if "etf_redemption_impact" not in l4:
            from apps.copilot.modules.executing.etf_redemption_impact import (
                describe_etf_redemption_ui_state,
                load_etf_redemption_payload,
            )

            etf_payload = await load_etf_redemption_payload(
                session, sym, redis_client=redis_client
            )
            event_probe_states["etf_redemption_impact"] = describe_etf_redemption_ui_state(
                etf_payload
            )

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
    hx-post="/api/executing/{sym}/daily-run-html" hx-target="#executing-detail-body-{sym}" hx-swap="innerHTML">
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
    timing_map = (
        await build_probe_card_timing_map(
            session,
            sym,
            l4_nodes=l4,
            sync=sync,
            quote_job_at=quote_wm,
        )
        if layer_b_enabled
        else {}
    )
    hot_timeline = (
        render_hot_data_timeline(qmt_node, quote_job_at=quote_wm)
        if has_holding
        else ""
    )
    layer_b_html = (
        f"{layer_b_banner}"
        f"{qmt_pending_html}"
        f"{render_degraded_probes(degraded_hints)}"
        f"{hot_timeline}"
        f'{render_l3_probe_domain(l3, timing_map=timing_map, l3_keys=symbol_l3_keys)}'
        f'{render_probe_domain(l4, title="JL4 · 盘面指标", accent="orange", empty_hint="暂无可用指标 · 点「立即跑今日体检」或等待 Cron 采集", symbol=sym, sync=sync, event_probe_states=event_probe_states, timing_map=timing_map)}'
    )

    jl3_ready_keys = [k for k in symbol_l3_keys if isinstance(l3.get(k), dict)]
    jl3_keys_attr = ",".join(symbol_l3_keys)
    body_html = (
        f"{toolbar}{cache_note}{pos_form}"
        f"{layer_b_html}"
        f"{audit_html}"
        f'<p class="text-[11px] text-gray-400 text-center mt-2">advisory only · no-auto-execute · [Ref: 28_]</p>'
    )
    return HTMLResponse(
        f'<div id="executing-detail-body-{sym}" '
        f'data-detail-state="loaded" data-symbol="{sym}" '
        f'data-detail-cache-version="3" '
        f'data-jl3-keys="{_esc(jl3_keys_attr)}" '
        f'data-jl3-ready="{_esc(",".join(jl3_ready_keys))}" '
        f'class="executing-detail-body executing-workspace executing-detail-loaded bg-gray-50 rounded-xl p-4 -mx-1">'
        f"{body_html}</div>"
    )


@router.get("/api/executing/analyst-panel-html", response_class=HTMLResponse)
async def api_analyst_panel_html(
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """Opus 持仓 T2 分析面板 HTML（/opus 页加载）。"""
    from apps.copilot.modules.executing.t2_analyst import (
        DEFAULT_JL13_DATA_TEMPLATE,
        DEFAULT_PROMPT_TEMPLATE,
    )
    from apps.copilot.modules.executing.t2_token_limits import token_limits_summary
    from apps.copilot.modules.radar.chat import DEFAULT_CHAT_MODEL, RADAR_CHAT_MODELS

    redis = _redis_for_panel()
    symbol_rows = await _load_analyst_symbol_rows(session, redis)
    return _templates.TemplateResponse(
        request,
        "planning/_t2_analyst_panel.html",
        {
            "symbols": symbol_rows,
            "chat_models": RADAR_CHAT_MODELS,
            "default_model": DEFAULT_CHAT_MODEL,
            "default_prompt_template": DEFAULT_PROMPT_TEMPLATE,
            "default_jl13_data_template": DEFAULT_JL13_DATA_TEMPLATE,
            "token_limits": token_limits_summary(),
        },
    )


def _render_analyst_payload_details(data: dict[str, Any]) -> str:
    import json

    payload_json = json.dumps(data, ensure_ascii=False, indent=2)
    if len(payload_json) > 120_000:
        payload_json = payload_json[:120_000] + "\n…(截断)"
    opus_json = json.dumps(data.get("opus_messages"), ensure_ascii=False, indent=2)[:80000]
    audit_json = json.dumps(data.get("opus_audit"), ensure_ascii=False, indent=2)[:80000]
    audit_block = ""
    if data.get("opus_audit"):
        audit_block = (
            "<details class='mt-1' open>"
            "<summary class='cursor-pointer text-[11px] font-medium text-emerald-700'>"
            "opus_audit（模型输出 JSON）</summary>"
            f"<pre class='mt-1 text-[10px] bg-emerald-950 text-emerald-100 p-2 rounded-lg "
            f"overflow-x-auto max-h-48'>{_esc(audit_json)}</pre></details>"
        )
    return (
        "<details class='mt-2'>"
        "<summary class='cursor-pointer text-[11px] font-medium text-violet-700'>"
        "opus_messages（system + user）</summary>"
        f"<pre class='mt-1 text-[10px] bg-gray-900 text-green-100 p-2 rounded-lg "
        f"overflow-x-auto max-h-48'>{_esc(opus_json)}</pre></details>"
        f"{audit_block}"
        "<details class='mt-1'>"
        "<summary class='cursor-pointer text-[11px] font-medium text-violet-700'>"
        "完整 payload JSON</summary>"
        f"<pre class='mt-1 text-[10px] bg-slate-900 text-slate-100 p-2 rounded-lg "
        f"overflow-x-auto max-h-64'>{_esc(payload_json)}</pre></details>"
    )


def _render_t2_analyst_job_progress(state: dict[str, Any]) -> str:
    """T2 后台任务进度（运行中由 HTMX 轮询 GET /api/executing/analyst/chat/job/{id}）。"""
    job_id = _esc(state.get("job_id") or "")
    status = state.get("status") or "running"
    pct = int(state.get("pct") or 0)
    step_label = _esc(state.get("step_label") or "分析进行中…")
    syms = _esc(", ".join(state.get("symbols") or []))
    started = float(state.get("started_at") or time.time())
    elapsed = int(time.time() - started)
    err = state.get("error")

    poll_attrs = ""
    if status == "running" and job_id:
        poll_attrs = (
            f" id='t2-analyst-job-progress' data-job-id='{job_id}'"
            f" hx-get='/api/executing/analyst/chat/job/{job_id}'"
            f" hx-trigger='every 3s'"
            f" hx-target='#t2-analyst-messages'"
            f" hx-swap='innerHTML'"
            f" hx-indicator='#t2-analyst-spinner'"
        )

    bar_color = "bg-violet-500"
    if status == "error":
        bar_color = "bg-red-400"
    elif status == "done":
        bar_color = "bg-emerald-500"

    err_html = ""
    if status == "error" and err:
        err_html = (
            f"<p class='text-sm text-red-700 mt-3'>{_esc(str(err)[:400])}</p>"
            f"<p class='text-xs text-gray-500 mt-1'>可修改提示词后重新提交 · 审计页可查拼接数据</p>"
        )

    return (
        f"<div class='rounded-xl border border-violet-200 bg-white/90 p-4'{poll_attrs}>"
        f"<div class='flex flex-wrap items-center justify-between gap-2 mb-2'>"
        f"<p class='text-sm font-medium text-violet-900'>T2 Opus 后台分析中</p>"
        f"<span class='text-xs text-violet-600'>{syms} · 已运行 {elapsed}s</span></div>"
        f"<div class='h-2 rounded-full bg-violet-100 overflow-hidden mb-2'>"
        f"<div class='h-full {bar_color} transition-all duration-500' style='width:{pct}%'></div></div>"
        f"<p class='text-xs text-gray-600'>{step_label}</p>"
        f"<p class='text-[11px] text-gray-400 mt-2'>"
        f"长连接走新加坡出口代理 · 正常约 3～5 分钟 · 可刷新页面，任务在服务端继续</p>"
        f"{err_html}</div>"
    )


def _render_analyst_chat_panel(payload: dict[str, Any]) -> str:
    """T2 持仓分析对话区 HTML。"""
    from apps.copilot.modules.executing.t2_analyst import new_analyst_session_id

    sid = _esc(payload.get("session_id") or new_analyst_session_id())
    messages = payload.get("messages") or []
    err = payload.get("error")

    bubbles: list[str] = []
    if not messages:
        bubbles.append(
            "<div class='text-center text-sm text-gray-400 py-8'>"
            "<p class='mb-1'>持仓分析</p>"
            "<p class='text-xs'>选择标的 → 输入问题 → 回车开始分析</p>"
            "</div>"
        )
    for m in messages:
        role = m.get("role")
        content = _esc(m.get("content") or "")
        if role == "user":
            meta = m.get("meta") or {}
            syms = ", ".join(meta.get("symbols") or [])
            tag = (
                f"<p class='text-[10px] text-blue-100/80 mt-1'>{_esc(syms)} · "
                f"JL4 {'开' if meta.get('include_t1_jl4') else '关'}</p>"
                if syms
                else ""
            )
            bubbles.append(
                f"<div class='flex justify-end t2-analyst-user' data-role='user'>"
                f"<div class='max-w-[88%] rounded-2xl rounded-tr-sm "
                f"bg-violet-600 text-white px-4 py-2.5 text-sm leading-relaxed shadow-sm'>"
                f"<p class='whitespace-pre-wrap'>{content}</p>{tag}</div></div>"
            )
        elif role == "assistant":
            meta = m.get("meta") or {}
            data = meta.get("payload") or meta.get("preview") or {}
            from apps.copilot.modules.executing.t2_analyst_render import (
                render_opus_assistant_bubble,
                render_t2_chat_prose,
                _assistant_pin_eligible,
            )

            card = ""
            if data:
                card = render_t2_chat_prose(data, meta)
            elif content:
                card = f"<p class='whitespace-pre-wrap text-sm'>{content}</p>"
            rid = str(meta.get("request_id") or data.get("request_id") or "")
            pin_ok = bool(data and _assistant_pin_eligible(data, meta))
            bubble = render_opus_assistant_bubble(
                card, request_id=rid, pin_eligible=pin_ok
            )
            bubbles.append(
                f"<div class='flex justify-start w-full'>{bubble}</div>"
            )

    err_html = ""
    if err:
        err_html = (
            f"<div class='mx-2 mb-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 "
            f"text-sm text-amber-800'>⚠️ {_esc(err)}</div>"
        )

    return (
        f"<div id='executing-analyst-chat-inner' data-session-id='{sid}'>"
        f"{err_html}"
        f"<div class='space-y-3 px-1 py-2'>"
        f"{''.join(bubbles)}</div></div>"
    )


def _render_analyst_assembly_html(data: dict[str, Any]) -> str:
    from apps.copilot.modules.executing.t2_analyst import (
        format_assembly_summary,
        new_analyst_session_id,
    )

    return _render_analyst_chat_panel(
        {
            "session_id": new_analyst_session_id(),
            "messages": [
                {
                    "role": "user",
                    "content": data.get("user_question") or "",
                    "meta": {
                        "symbols": data.get("symbols"),
                        "include_t1_jl4": data.get("include_t1_jl4"),
                    },
                },
                {
                    "role": "assistant",
                    "content": format_assembly_summary(data),
                    "meta": {"payload": data, "preview_only": True},
                },
            ],
        }
    )


@router.get("/api/executing/analyst/chat/{session_id}", response_class=HTMLResponse)
async def api_analyst_chat_history(
    session_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """拉取 T2 持仓分析对话历史；若该 session 有进行中的后台任务则返回进度面板。"""
    from apps.copilot.modules.executing.t2_analyst import load_analyst_messages
    from apps.copilot.modules.executing.t2_analyst_progress import active_job_id, load

    redis = _redis_for_panel()
    sid = (session_id or "").strip()
    if sid and sid != "placeholder":
        job_id = active_job_id(redis, sid)
        if job_id:
            state = load(redis, job_id)
            if state and state.get("status") == "running":
                return HTMLResponse(_render_t2_analyst_job_progress(state))
            if state and state.get("status") == "done":
                result = state.get("result") or {}
                return HTMLResponse(_render_analyst_chat_panel(result))

    messages = await load_analyst_messages(
        session_id, redis_client=redis, db_session=session
    )
    await session.commit()
    payload = {"session_id": session_id, "messages": messages, "status": "ok"}
    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_analyst_chat_panel(payload))
    return JSONResponse(payload)


@router.get("/api/executing/analyst/sessions")
async def api_analyst_chat_sessions(
    session: AsyncSession = Depends(get_db),
    limit: int = 40,
):
    from apps.copilot.modules.executing.t2_analyst import list_t2_analyst_sessions

    return {"sessions": await list_t2_analyst_sessions(session, limit=limit)}


@router.post("/api/executing/analyst/chat/new", response_class=HTMLResponse)
async def api_analyst_chat_new(
    request: Request,
    session_id: str = Form(""),
    session: AsyncSession = Depends(get_db),
):
    """清空当前分析会话。"""
    from apps.copilot.modules.executing.t2_analyst import (
        clear_analyst_session,
        new_analyst_session_id,
    )

    redis = _redis_for_panel()
    await clear_analyst_session(session_id, redis_client=redis, db_session=session)
    await session.commit()
    payload = {"session_id": new_analyst_session_id(), "messages": [], "status": "new"}
    if request.headers.get("hx-request"):
        return HTMLResponse(_render_analyst_chat_panel(payload))
    return JSONResponse(payload)


@router.post("/api/executing/analyst/pin-to-executing")
async def api_pin_t2_to_executing(
    request_id: str = Form(""),
    symbols: list[str] = Form(default=[]),
    session: AsyncSession = Depends(get_db),
):
    """用户手动将某条 T2 分析同步到执行区标的卡（须勾选标的）。"""
    from apps.copilot.modules.executing.t2_executing_pin import pin_t2_to_executing

    try:
        result = await pin_t2_to_executing(
            session, request_id=request_id, symbols=symbols
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    except Exception as exc:
        await session.rollback()
        logger.exception("pin T2 to executing failed")
        return JSONResponse({"ok": False, "error": str(exc)[:200]}, status_code=500)

    return JSONResponse({"ok": True, **result})


@router.post("/api/executing/{symbol}/unpin-t2-summary", response_class=HTMLResponse)
async def api_unpin_t2_summary(symbol: str, session: AsyncSession = Depends(get_db)):
    """解除固定 T2 摘要 · 恢复自动同步最近一次 Opus 分析。"""
    from apps.copilot.modules.executing.t2_advice_summary import (
        load_executing_t2_summaries_for_symbols,
        render_executing_t2_banner,
    )
    from apps.copilot.modules.executing.t2_executing_pin import unpin_t2_from_executing

    sym = symbol.zfill(6)[-6:]
    try:
        await unpin_t2_from_executing(session, sym)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        return HTMLResponse(
            f"<div id='executing-t2-banner-{sym}' class='executing-t2-banner px-5 py-2 text-xs text-rose-700'>"
            f"{_esc(str(exc))}</div>",
            status_code=400,
        )
    summaries = await load_executing_t2_summaries_for_symbols(session, [sym])
    return HTMLResponse(render_executing_t2_banner(sym, summaries.get(sym)))


@router.post("/api/executing/analyst/chat", response_class=HTMLResponse)
async def api_analyst_chat(
    request: Request,
    message: str = Form(""),
    session_id: str = Form(""),
    model_id: str = Form(""),
    include_t1_jl4: str = Form(""),
    include_jl13_data: str = Form(""),
    jl13_data_prompt: str = Form(""),
    symbols: list[str] = Form(default=[]),
    session: AsyncSession = Depends(get_db),
):
    """T2 持仓分析：Opus 启用时后台任务 + HTMX 轮询；否则同步组装。"""
    from apps.copilot.modules.executing.t2_analyst import (
        analyst_chat_turn,
        new_analyst_session_id,
        run_t2_analyst_job,
        t2_opus_enabled,
    )
    from apps.copilot.modules.executing.t2_analyst_progress import init_job, new_job_id

    if not symbols:
        payload = {
            "session_id": session_id,
            "messages": [],
            "error": "请至少选择一个标的",
        }
        return HTMLResponse(_render_analyst_chat_panel(payload), status_code=400)

    redis = _redis_for_panel()
    sid = (session_id or "").strip() or new_analyst_session_id()
    if sid == "placeholder":
        sid = new_analyst_session_id()

    if t2_opus_enabled():
        job_id = new_job_id()
        state = init_job(redis, job_id, session_id=sid, symbols=symbols)
        asyncio.create_task(
            run_t2_analyst_job(
                job_id,
                session_id=sid,
                symbols=symbols,
                user_question=message,
                model_id=model_id or None,
                include_t1_jl4=include_t1_jl4 == "1",
                jl13_data_prompt=jl13_data_prompt,
                include_jl13_data=include_jl13_data == "1",
                redis_client=redis,
            )
        )
        html_out = _render_t2_analyst_job_progress(state)
        if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
            return HTMLResponse(html_out)
        return JSONResponse({"job_id": job_id, "status": "running", "session_id": sid})

    try:
        result = await analyst_chat_turn(
            session,
            session_id=sid,
            symbols=symbols,
            user_question=message,
            model_id=model_id or None,
            include_t1_jl4=include_t1_jl4 == "1",
            jl13_data_prompt=jl13_data_prompt,
            include_jl13_data=include_jl13_data == "1",
            redis_client=redis,
        )
    except ValueError as exc:
        payload = {
            "session_id": sid,
            "messages": [],
            "error": str(exc),
        }
        return HTMLResponse(_render_analyst_chat_panel(payload), status_code=400)
    except Exception as exc:
        logger.exception("T2 analyst chat failed")
        payload = {
            "session_id": sid,
            "messages": [],
            "error": f"分析失败：{str(exc)[:300]}",
        }
        return HTMLResponse(_render_analyst_chat_panel(payload), status_code=500)

    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_analyst_chat_panel(result))
    return JSONResponse(result)


@router.get("/api/executing/analyst/chat/active/{session_id}", response_class=HTMLResponse)
async def api_analyst_chat_active(session_id: str):
    """按 session 恢复进行中的 T2 后台任务（刷新页面后轮询）。"""
    from apps.copilot.modules.executing.t2_analyst_progress import active_job_id, load

    redis = _redis_for_panel()
    job_id = active_job_id(redis, session_id)
    if not job_id:
        return HTMLResponse("", status_code=204)
    state = load(redis, job_id)
    if not state or state.get("status") == "running":
        return HTMLResponse(_render_t2_analyst_job_progress(state or {"job_id": job_id, "status": "running"}))
    if state.get("status") == "done":
        return HTMLResponse(_render_analyst_chat_panel(state.get("result") or {}))
    return HTMLResponse(_render_t2_analyst_job_progress(state))


@router.get("/api/executing/analyst/chat/job/{job_id}", response_class=HTMLResponse)
async def api_analyst_chat_job(
    job_id: str,
    request: Request,
):
    """轮询 T2 后台分析任务；完成时返回完整对话区 HTML。"""
    from apps.copilot.modules.executing.t2_analyst_progress import load

    redis = _redis_for_panel()
    state = load(redis, job_id)
    if not state:
        return HTMLResponse(
            "<p class='text-sm text-amber-700 p-4'>任务不存在或已过期，请重新提交分析。</p>",
            status_code=404,
        )
    status = state.get("status") or "running"
    if status == "done":
        result = state.get("result") or {}
        return HTMLResponse(_render_analyst_chat_panel(result))
    if status == "error":
        return HTMLResponse(_render_t2_analyst_job_progress(state))
    return HTMLResponse(_render_t2_analyst_job_progress(state))


@router.post("/api/executing/analyst/preview-html", response_class=HTMLResponse)
async def api_analyst_preview_html(
    request: Request,
    message: str = Form(""),
    model_id: str = Form(""),
    include_t1_jl4: str = Form(""),
    symbols: list[str] = Form(default=[]),
    session: AsyncSession = Depends(get_db),
):
    """仅组装 T2 envelope（不调用 Opus）。"""
    from apps.copilot.modules.executing.t2_analyst import assemble_t2_analyst_payload

    if not symbols:
        return HTMLResponse(
            '<p class="text-amber-700 text-sm">请至少选择一个标的。</p>',
            status_code=400,
        )
    redis = _redis_for_panel()
    try:
        data = await assemble_t2_analyst_payload(
            session,
            symbols,
            user_question=message,
            model_id=model_id or None,
            include_t1_jl4=include_t1_jl4 == "1",
            redis_client=redis,
        )
        data["preview_only"] = True
        data["api_connected"] = False
        data["opus_skip_reason"] = "preview-html 端点仅组装"
    except ValueError as exc:
        return HTMLResponse(f'<p class="text-amber-700 text-sm">{_esc(exc)}</p>', status_code=400)
    except Exception as exc:
        logger.exception("T2 analyst assembly failed")
        return HTMLResponse(
            f'<p class="text-rose-700 text-sm">组装失败：{_esc(str(exc)[:300])}</p>',
            status_code=500,
        )
    return HTMLResponse(_render_analyst_assembly_html(data))


@router.post("/api/executing/analyst/preview")
async def api_analyst_preview_json(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_db),
):
    """JSON 版 envelope 组装（供脚本/检查）。"""
    from apps.copilot.modules.executing.t2_analyst import assemble_t2_analyst_payload

    symbols = body.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    redis = _redis_for_panel()
    data = await assemble_t2_analyst_payload(
        session,
        list(symbols),
        user_question=str(body.get("message") or body.get("user_question") or ""),
        model_id=body.get("model_id"),
        include_t1_jl4=bool(body.get("include_t1_jl4", True)),
        redis_client=redis,
    )
    return JSONResponse(data)


def _render_t2_analyst_audit_list(rows: list[Any]) -> str:
    if not rows:
        return (
            "<p class='text-sm text-gray-500 py-4 text-center'>"
            "暂无 T2 预分析记录 · 在执行中工作台提交问题后自动生成</p>"
        )
    items: list[str] = []
    for r in rows:
        syms = ", ".join(r.symbols_json or [])
        q = (r.user_question or "")[:80]
        if len(r.user_question or "") > 80:
            q += "…"
        ts = r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "—"
        mode = "仅拼接" if r.dry_run else "Opus"
        items.append(
            f"<tr class='border-b border-gray-100 hover:bg-violet-50/40'>"
            f"<td class='py-2 pr-3 text-xs text-gray-500 whitespace-nowrap'>{_esc(ts)}</td>"
            f"<td class='py-2 pr-3 text-xs font-mono text-violet-700'>"
            f"<a href='/audit?t2_id={_esc(r.request_id)}' class='underline'>{_esc(r.request_id)}</a></td>"
            f"<td class='py-2 pr-3 text-xs text-gray-700'>{_esc(syms)}</td>"
            f"<td class='py-2 pr-3 text-xs text-gray-600 max-w-md truncate' title='{_esc(r.user_question)}'>"
            f"{_esc(q)}</td>"
            f"<td class='py-2 pr-3 text-xs'>{_esc(r.model_id or '—')}</td>"
            f"<td class='py-2 text-xs'>{_esc(mode)} · JL4 {'开' if r.include_t1_jl4 else '关'}</td>"
            f"</tr>"
        )
    return (
        "<div class='overflow-x-auto'><table class='w-full text-left text-sm'>"
        "<thead><tr class='text-xs text-gray-500 border-b border-gray-200'>"
        "<th class='py-2 pr-3'>时间</th><th class='py-2 pr-3'>request_id</th>"
        "<th class='py-2 pr-3'>标的</th><th class='py-2 pr-3'>问题摘要</th>"
        "<th class='py-2 pr-3'>模型</th><th class='py-2'>模式</th></tr></thead>"
        f"<tbody>{''.join(items)}</tbody></table></div>"
    )


def _render_t2_analyst_audit_detail(row: Any) -> str:
    import json

    from apps.copilot.modules.executing.t2_analyst_render import render_t2_assistant_card

    payload = row.payload_json or {}
    opus = payload.get("opus_messages") or []
    audit = structured_audit_from_payload(payload)
    if audit is not payload.get("opus_audit"):
        payload = {**payload, "opus_audit": audit}
    system_txt = opus[0].get("content", "") if opus else ""
    user_txt = opus[1].get("content", "") if len(opus) > 1 else ""
    try:
        user_obj = json.loads(user_txt) if user_txt else {}
        user_pretty = json.dumps(user_obj, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        user_obj = {}
        user_pretty = user_txt
    full_pretty = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(full_pretty) > 200_000:
        full_pretty = full_pretty[:200_000] + "\n…(截断)"

    syms = ", ".join(row.symbols_json or [])
    ts = row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "—"
    status = "ok" if row.api_connected and payload.get("opus_audit") else (
        "error" if payload.get("opus_error") else "assembly_only"
    )
    render_html = ""
    if payload:
        render_html = render_t2_assistant_card(
            payload,
            {
                "status": status,
                "request_id": row.request_id,
                "error": payload.get("opus_error"),
            },
        )
    opus_raw = (payload.get("opus_raw_text") or "")[:120000]
    opus_audit_json = json.dumps(payload.get("opus_audit"), ensure_ascii=False, indent=2)[:80000]
    opus_reply_block = ""
    if render_html:
        opus_reply_block = (
            "<div class='mb-4 rounded-xl border border-emerald-200 bg-white p-3'>"
            "<h4 class='text-xs font-semibold text-emerald-800 mb-2'>Opus 结构化回复（已落库）</h4>"
            f"{render_html}</div>"
        )
    return f"""
<div class="rounded-xl border border-violet-200 bg-violet-50/30 p-4 mb-4 text-sm">
  <h3 class="font-semibold text-violet-900 mb-2">T2 持仓审计 · {_esc(row.request_id)}</h3>
  <p class="text-xs text-gray-600 mb-3">
    时间 {_esc(ts)} · 标的 {_esc(syms)} · 模型 {_esc(row.model_id or '—')} ·
    JL4 {'开' if row.include_t1_jl4 else '关'} ·
    preview_only={str(row.dry_run).lower()} · api_connected={str(row.api_connected).lower()}
  </p>
  <p class="text-xs text-gray-700 mb-3 whitespace-pre-wrap border-l-2 border-violet-300 pl-3">
    <span class="text-gray-400">user_question：</span>{_esc(row.user_question)}
  </p>
  {opus_reply_block}
  <details class="mb-2" open>
    <summary class="cursor-pointer text-xs font-medium text-emerald-800">opus_audit（模型输出 JSON）</summary>
    <pre class="mt-2 text-[10px] bg-emerald-950 text-emerald-100 p-3 rounded-lg overflow-x-auto max-h-96">{_esc(opus_audit_json)}</pre>
  </details>
  <details class="mb-2">
    <summary class="cursor-pointer text-xs font-medium text-violet-800">opus_raw_text（原始文本）</summary>
    <pre class="mt-2 text-[10px] bg-gray-900 text-green-100 p-3 rounded-lg overflow-x-auto max-h-48">{_esc(opus_raw)}</pre>
  </details>
  <details class="mb-2">
    <summary class="cursor-pointer text-xs font-medium text-violet-800">Opus 收到什么？（消息结构说明）</summary>
    <div class="mt-2 text-xs text-gray-600 space-y-2 pl-2">
      <p><strong>messages[0] system</strong>：投资哲学 + 问答路由 + 输出铁律（约 {len(system_txt)} 字）</p>
      <p><strong>messages[1] user</strong>：JSON 字符串，含 qa_index、t1、profit、optional、checklist、jl4_catalog、output_contract、coverage、user_question</p>
      <p>JL4 指标数：{_esc(str(payload.get('jl4_indicator_counts')))}</p>
    </div>
  </details>
  <details class="mb-2">
    <summary class="cursor-pointer text-xs font-medium text-violet-800">messages[0] system_prompt</summary>
    <pre class="mt-2 text-[10px] bg-gray-900 text-green-100 p-3 rounded-lg overflow-x-auto max-h-48">{_esc(system_txt[:60000])}</pre>
  </details>
  <details class="mb-2" open>
    <summary class="cursor-pointer text-xs font-medium text-violet-800">messages[1] user JSON（Opus 实际输入）</summary>
    <pre class="mt-2 text-[10px] bg-slate-900 text-slate-100 p-3 rounded-lg overflow-x-auto max-h-96">{_esc(user_pretty[:120000])}</pre>
  </details>
  <details>
    <summary class="cursor-pointer text-xs font-medium text-violet-800">完整 payload（envelope + opus_messages + 元数据）</summary>
    <pre class="mt-2 text-[10px] bg-slate-950 text-slate-200 p-3 rounded-lg overflow-x-auto max-h-[32rem]">{_esc(full_pretty)}</pre>
  </details>
  <p class="text-[10px] text-gray-400 mt-2">
    <a href="/api/executing/analyst/audit/{_esc(row.request_id)}" class="text-violet-600 underline" target="_blank">下载 JSON</a>
  </p>
</div>
"""


@router.get("/api/executing/analyst/audit-html", response_class=HTMLResponse)
async def api_t2_analyst_audit_list_html(
    session: AsyncSession = Depends(get_db),
    limit: int = 30,
):
    """T2 预分析审计列表（HTMX 片段）。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest
    from sqlalchemy import select

    rows = (
        await session.scalars(
            select(ExecutingT2AnalystRequest)
            .order_by(ExecutingT2AnalystRequest.created_at.desc())
            .limit(min(limit, 100))
        )
    ).all()
    return HTMLResponse(_render_t2_analyst_audit_list(list(rows)))


@router.get("/api/executing/analyst/audit/{request_id}")
async def api_t2_analyst_audit_detail(
    request_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """单条 T2 数据集（JSON 或 HTML）。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest

    row = await session.scalar(
        select(ExecutingT2AnalystRequest).where(
            ExecutingT2AnalystRequest.request_id == request_id.strip()
        )
    )
    if row is None:
        raise HTTPException(404, "T2 审计记录不存在")
    if request.headers.get("hx-request") or "text/html" in request.headers.get("accept", ""):
        return HTMLResponse(_render_t2_analyst_audit_detail(row))
    return JSONResponse(row.payload_json or {})


@router.get("/api/executing/analyst/audit-detail-html", response_class=HTMLResponse)
async def api_t2_analyst_audit_detail_html(
    t2_id: str = "",
    session: AsyncSession = Depends(get_db),
):
    """审计页按 t2_id 加载详情片段。"""
    from apps.copilot.db.models import ExecutingT2AnalystRequest

    rid = (t2_id or "").strip()
    if not rid:
        return HTMLResponse("<p class='text-sm text-gray-400'>选择上方记录查看完整数据集</p>")
    row = await session.scalar(
        select(ExecutingT2AnalystRequest).where(ExecutingT2AnalystRequest.request_id == rid)
    )
    if row is None:
        return HTMLResponse(f"<p class='text-sm text-rose-700'>未找到记录 {_esc(rid)}</p>")
    return HTMLResponse(_render_t2_analyst_audit_detail(row))
