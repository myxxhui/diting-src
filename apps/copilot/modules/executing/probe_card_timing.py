"""JL4 探针卡片 · T1 有效/测算时间与 T0 增量采集时间。

语义约定（工作区卡片顶栏）：
- 左上 T1有效：指标所依据的数据截止交易日（非采集时刻）
- 左上 T1测算：最近一次 T1 硬算落库时间（仅当节点变化时刷新，非每次打开页面）
- 右上 T0增量：对应 Cron job 水位 last_success_at（优先于 probe_state）

[Ref: 28_ §4 · 工作区卡片时间语义]
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.datetime_util import as_utc_aware, utc_naive_to_shanghai_display
from apps.copilot.db.models import ExecutingT0ProbeState, ExecutingT1ProbeSnapshot
from apps.copilot.modules.executing.probe_registry import PROBE_REGISTRY
from apps.copilot.modules.executing.profile import L4_KEYS, load_profile

TimingHealth = Literal["ok", "stale", "failed", "missing"]

# 盘中探针除主 job_id 外，回退到更细粒度水位
_T0_JOB_FALLBACKS: dict[str, tuple[str, ...]] = {
    "qmt_atr_trailing": ("quote-intraday-close", "quote-intraday", "l4-atr-bars-sync"),
    "volume_price_div": ("l4-vol-div-15m-close", "l4-vol-div-15m"),
}


@dataclass(frozen=True)
class ProbeCardTiming:
    """单探针卡片顶栏时间元数据。"""

    t1_effective_label: str | None
    t1_published_label: str | None
    t0_collected_label: str | None
    health: TimingHealth
    t0_job_id: str | None = None
    alert: str | None = None


def _sym(symbol: str) -> str:
    return symbol.zfill(6)[-6:]


def _format_date_label(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    s = str(raw).strip()
    if not s:
        return None
    if " " in s and len(s) >= 16:
        cst = utc_naive_to_shanghai_display(s) if "T" in s else s[:16]
        if "盘中" not in cst and ":" in cst:
            return f"盘中 {cst[11:16]}"
        return cst[:16]
    s = s.replace("-", "")[:8]
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return str(raw)[:10]


def _node_effective_label(node: dict[str, Any] | None) -> str | None:
    if not node:
        return None
    rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
    for key in (
        "trade_date",
        "as_of",
        "inferred_trade_date",
        "data_as_of",
        "bar_as_of",
        "snapshot_end_date",
        "last_update_date",
        "last_bar_datetime",
        "last_tick_time",
    ):
        for src in (rm, node):
            if not isinstance(src, dict):
                continue
            label = _format_date_label(src.get(key))
            if label:
                if key in ("last_tick_time", "last_bar_datetime") and "盘中" not in label:
                    if " " in label:
                        return f"盘中 {label.split(' ', 1)[-1][:5]}"
                    return f"盘中 {label}"
                return label
    return None


def _resolve_t0_job_ids(probe_key: str) -> list[str]:
    spec = PROBE_REGISTRY.get(probe_key)
    primary = spec.spec.job_id if spec else None
    ids: list[str] = []
    if primary:
        ids.append(primary)
    for jid in _T0_JOB_FALLBACKS.get(probe_key, ()):
        if jid not in ids:
            ids.append(jid)
    return ids


def _parse_watermark_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip().replace("Z", "")
    try:
        if "T" in s:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        # 已是北京时间展示串
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=8))
        )
    except ValueError:
        return None


def _best_watermark(
    sync: dict[str, Any] | None,
    job_ids: list[str],
    *,
    symbol: str,
) -> tuple[str | None, str | None, str | None]:
    """返回 (展示时间, 命中 job_id, last_error)。"""
    if not sync or not job_ids:
        return None, None, None
    sym = _sym(symbol)
    best_label: str | None = None
    best_job: str | None = None
    best_dt: datetime | None = None
    err: str | None = None

    for jid in job_ids:
        for w in sync.get("watermarks") or []:
            if w.get("job_id") != jid:
                continue
            wsym = str(w.get("symbol") or "*")
            if wsym not in (sym, "*"):
                continue
            label = w.get("last_success_at_cst") or w.get("last_success_at")
            dt = _parse_watermark_dt(label) or _parse_watermark_dt(w.get("last_success_at"))
            if w.get("last_error"):
                err = str(w.get("last_error"))[:120]
            if dt is None:
                continue
            if best_dt is None or dt > best_dt:
                best_dt = dt
                best_label = label if isinstance(label, str) and " " in label else (
                    utc_naive_to_shanghai_display(dt.replace(tzinfo=None))
                    if dt.tzinfo
                    else label
                )
                best_job = jid
    return best_label, best_job, err


def build_card_timing(
    probe_key: str,
    *,
    symbol: str = "",
    node: dict[str, Any] | None = None,
    probe_state: ExecutingT0ProbeState | None = None,
    t1_row: ExecutingT1ProbeSnapshot | None = None,
    sync: dict[str, Any] | None = None,
    quote_job_at: str | None = None,
    stale_days: int = 1,
    now: datetime | None = None,
) -> ProbeCardTiming:
    """合成单卡顶栏：左上 T1 有效/测算 · 右上 T0 增量采集。"""
    now_utc = now or datetime.now(timezone.utc)
    job_ids = _resolve_t0_job_ids(probe_key)

    t1_effective = _node_effective_label(node)
    if not t1_effective and t1_row and t1_row.trade_date:
        t1_effective = t1_row.trade_date.isoformat()

    t1_published = None
    if t1_row and t1_row.collected_at:
        t1_published = utc_naive_to_shanghai_display(t1_row.collected_at)

    t0_collected, t0_job, wm_err = _best_watermark(sync, job_ids, symbol=symbol)
    if not t0_collected and probe_state and probe_state.collected_at:
        t0_collected = utc_naive_to_shanghai_display(probe_state.collected_at)
    if not t0_collected and probe_key == "qmt_atr_trailing" and quote_job_at:
        t0_collected = utc_naive_to_shanghai_display(quote_job_at) or str(quote_job_at)
        t0_job = "quote-intraday"

    health: TimingHealth = "missing"
    alert: str | None = None

    if wm_err:
        health = "failed"
        alert = wm_err
    elif probe_state:
        if probe_state.status != "ok":
            health = "failed"
            alert = (probe_state.blocker or "T0 采集未成功")[:120]
        elif probe_state.stale_after and as_utc_aware(probe_state.stale_after) < now_utc:
            health = "stale"
            alert = "数据已过期 · 未按预期日频更新"
        elif t0_collected:
            health = "ok"
        else:
            health = "missing"
            alert = "尚无 T0 增量采集记录"
    elif t0_collected:
        health = "ok"
    elif node is not None:
        health = "missing"
        alert = "尚无 T0 增量采集水位"

    if health == "ok" and t0_collected and stale_days > 0:
        state_still_fresh = bool(
            probe_state
            and probe_state.status == "ok"
            and probe_state.stale_after
            and as_utc_aware(probe_state.stale_after) >= now_utc
        )
        if not state_still_fresh:
            wm_dt = _parse_watermark_dt(t0_collected)
            if wm_dt and wm_dt.astimezone(timezone.utc) + timedelta(days=stale_days) < now_utc:
                health = "stale"
                alert = alert or f"超过 {stale_days} 天未增量刷新"

    if node and health == "ok":
        rm = node.get("raw_metrics") if isinstance(node.get("raw_metrics"), dict) else {}
        if rm.get("data_stale_warning"):
            health = "stale"
            alert = alert or "快照超过有效窗 · 未按预期更新"

    if health == "ok" and node is None:
        health = "missing"
        alert = "尚无 T1 节点"

    return ProbeCardTiming(
        t1_effective_label=t1_effective,
        t1_published_label=t1_published,
        t0_collected_label=t0_collected,
        t0_job_id=t0_job,
        health=health,
        alert=alert,
    )


async def build_probe_card_timing_map(
    session: AsyncSession,
    symbol: str,
    *,
    l4_nodes: dict[str, Any] | None = None,
    sync: dict[str, Any] | None = None,
    quote_job_at: str | None = None,
) -> dict[str, ProbeCardTiming]:
    """批量加载 L4 探针卡片时间元数据。"""
    sym = _sym(symbol)
    l4_nodes = l4_nodes or {}
    now = datetime.now(timezone.utc)
    prof = load_profile(sym)
    probes_cfg = prof.get("probes") or {}

    states = {
        p.probe_key: p
        for p in (
            await session.scalars(
                select(ExecutingT0ProbeState).where(ExecutingT0ProbeState.symbol == sym)
            )
        ).all()
    }
    snapshots = {
        r.probe_key: r
        for r in (
            await session.scalars(
                select(ExecutingT1ProbeSnapshot).where(ExecutingT1ProbeSnapshot.symbol == sym)
            )
        ).all()
    }

    out: dict[str, ProbeCardTiming] = {}
    for key in L4_KEYS:
        cfg = probes_cfg.get(key) or {}
        stale_days = int(cfg.get("stale_days", 1))
        out[key] = build_card_timing(
            key,
            symbol=sym,
            node=l4_nodes.get(key) if isinstance(l4_nodes.get(key), dict) else None,
            probe_state=states.get(key),
            t1_row=snapshots.get(key),
            sync=sync,
            quote_job_at=quote_job_at if key == "qmt_atr_trailing" else None,
            stale_days=stale_days,
            now=now,
        )
    return out


def render_card_timing_bar(timing: ProbeCardTiming | None) -> str:
    """卡片顶栏：左上 T1 有效/测算 · 右上 T0 增量（失败/过期红色告警）。"""
    if timing is None:
        return ""

    left_bits: list[str] = []
    if timing.t1_effective_label:
        left_bits.append(f"T1有效 {timing.t1_effective_label}")
    else:
        left_bits.append("T1有效 —")
    if timing.t1_published_label:
        left_bits.append(f"T1测算 {timing.t1_published_label}")

    right_cls = "text-gray-400"
    alert_html = ""
    if timing.health in ("failed", "stale", "missing"):
        right_cls = "text-rose-600 font-semibold"
        if timing.alert:
            alert_html = (
                f'<p class="text-[10px] text-rose-600 mt-0.5 text-right">{_esc_timing(timing.alert)}</p>'
            )

    collected = timing.t0_collected_label or "—"
    job_hint = f" · {timing.t0_job_id}" if timing.t0_job_id else ""
    right_main = f"T0增量 {collected}{job_hint}"
    if timing.health in ("failed", "stale", "missing") and not timing.alert:
        right_main += " · 未按预期更新"

    return f"""
<div class="flex items-start justify-between gap-3 mb-3 pb-2 border-b border-gray-100">
  <span class="text-[11px] text-gray-500 font-mono leading-snug">{_esc_timing(" · ".join(left_bits))}</span>
  <div class="text-right shrink-0 max-w-[55%]">
    <span class="text-[11px] font-mono leading-snug {right_cls}">{_esc_timing(right_main)}</span>
    {alert_html}
  </div>
</div>"""


def t1_node_signature(node: dict[str, Any]) -> str:
    """T1 节点内容指纹 · 用于避免页面刷新无意义地刷新测算时间。"""
    payload = {
        "value": node.get("value"),
        "fact_statement": node.get("fact_statement"),
        "calculation_logic": node.get("calculation_logic"),
        "raw_metrics": node.get("raw_metrics"),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def _esc_timing(s: str) -> str:
    import html as _html

    return _html.escape(s, quote=True)
