"""战略板块服务层。

[Ref: 33_五区工作台_前端区际联动与数据携带契约.md]
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.copilot.db.models import (
    CampaignSymbol,
    StrategicBoard,
    StrategicPhase,
    StrategicPhaseProbe,
    StrategicPhaseReview,
    StrategicPhaseSymbol,
    SymbolStrategicTag,
)
from apps.copilot.modules.planning.funnel import normalize_symbol
from apps.copilot.modules.strategic.jl_catalog import catalog_entry, JL_PROBE_CATALOG
from apps.copilot.modules.strategic.seed import AI_ECOSYSTEM_SEED


def phase_progress_pct(start_year: int, end_year: int, today: Optional[date] = None) -> int:
    """阶段进度（纯日期，非投资判断）。"""
    today = today or date.today()
    if end_year <= start_year:
        return 0
    total_days = (date(end_year, 12, 31) - date(start_year, 1, 1)).days
    if total_days <= 0:
        return 0
    elapsed = (today - date(start_year, 1, 1)).days
    if elapsed <= 0:
        return 0
    if elapsed >= total_days:
        return 100
    return max(0, min(100, int(round(elapsed * 100 / total_days))))


def active_phase_for_board(phases: list[StrategicPhase], today: Optional[date] = None) -> Optional[StrategicPhase]:
    today = today or date.today()
    y = today.year
    for ph in sorted(phases, key=lambda p: p.sort_order):
        if ph.start_year <= y <= ph.end_year:
            return ph
    future = [p for p in phases if p.start_year > y]
    if future:
        return min(future, key=lambda p: p.start_year)
    if phases:
        return max(phases, key=lambda p: p.end_year)
    return None


async def count_boards(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(StrategicBoard)) or 0)


async def list_boards_summary(session: AsyncSession) -> list[dict[str, Any]]:
    boards = (
        await session.scalars(
            select(StrategicBoard)
            .options(selectinload(StrategicBoard.phases))
            .order_by(StrategicBoard.updated_at.desc())
        )
    ).all()
    out: list[dict[str, Any]] = []
    for b in boards:
        active = active_phase_for_board(list(b.phases))
        alert = await _board_alert_counts(session, b.id)
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "horizon_start": b.horizon_start,
                "horizon_end": b.horizon_end,
                "color_token": b.color_token,
                "is_template": b.is_template,
                "active_phase_name": active.name if active else "—",
                "active_phase_id": active.id if active else None,
                "phase_count": len(b.phases),
                "alerts": alert,
            }
        )
    return out


async def _board_alert_counts(session: AsyncSession, board_id: int) -> dict[str, int]:
    phases = (
        await session.scalars(select(StrategicPhase.id).where(StrategicPhase.board_id == board_id))
    ).all()
    red = yellow = green = pending = 0
    for pid in phases:
        probes = await get_phase_probe_status(session, int(pid))
        for p in probes:
            st = p.get("status") or "pending"
            if st == "red":
                red += 1
            elif st == "yellow":
                yellow += 1
            elif st == "green":
                green += 1
            else:
                pending += 1
    return {"red": red, "yellow": yellow, "green": green, "pending": pending}


async def get_board_detail(session: AsyncSession, board_id: int) -> Optional[dict[str, Any]]:
    board = await session.scalar(
        select(StrategicBoard)
        .options(
            selectinload(StrategicBoard.phases).selectinload(StrategicPhase.watch_symbols),
            selectinload(StrategicBoard.phases).selectinload(StrategicPhase.probes),
        )
        .where(StrategicBoard.id == board_id)
    )
    if board is None:
        return None

    phases_out: list[dict[str, Any]] = []
    for ph in sorted(board.phases, key=lambda p: (p.sort_order, p.wave_no)):
        stats = await phase_funnel_stats(session, ph.id)
        alerts = await get_phase_probe_status(session, ph.id)
        alert_counts = {"red": 0, "yellow": 0, "green": 0, "pending": 0}
        for a in alerts:
            st = a.get("status") or "pending"
            alert_counts[st if st in alert_counts else "pending"] += 1
        phases_out.append(
            {
                "id": ph.id,
                "wave_no": ph.wave_no,
                "name": ph.name,
                "start_year": ph.start_year,
                "end_year": ph.end_year,
                "situation_md": ph.situation_md,
                "playbook_md": ph.playbook_md,
                "cso_barbell_pct_json": ph.cso_barbell_pct_json,
                "progress_pct": phase_progress_pct(ph.start_year, ph.end_year),
                "watch_count": len(ph.watch_symbols),
                "stats": stats,
                "alert_counts": alert_counts,
            }
        )

    active = active_phase_for_board(list(board.phases))

    return {
        "id": board.id,
        "name": board.name,
        "horizon_start": board.horizon_start,
        "horizon_end": board.horizon_end,
        "qualitative_md": board.qualitative_md,
        "barbell_config_json": board.barbell_config_json,
        "stock_pool_json": board.stock_pool_json,
        "color_token": board.color_token,
        "phases": phases_out,
        "active_phase_id": active.id if active else None,
    }


async def phase_funnel_stats(session: AsyncSession, phase_id: int) -> dict[str, int]:
    """按阶段猎物池 + 标签聚合 funnel_stage 计数。"""
    symbols = set(
        normalize_symbol(s)
        for s in (
            await session.scalars(
                select(StrategicPhaseSymbol.symbol).where(
                    StrategicPhaseSymbol.phase_id == phase_id
                )
            )
        ).all()
    )
    tagged = (
        await session.scalars(
            select(SymbolStrategicTag.symbol).where(SymbolStrategicTag.phase_id == phase_id)
        )
    ).all()
    symbols.update(normalize_symbol(s) for s in tagged)

    stats = {
        "radar": 0,
        "roadmap": 0,
        "planning": 0,
        "executing": 0,
        "archived": 0,
        "watch_only": len(symbols),
    }
    if not symbols:
        return stats

    rows = (
        await session.scalars(
            select(CampaignSymbol).where(
                CampaignSymbol.symbol.in_(list(symbols)),
                CampaignSymbol.ui_removed_at.is_(None),
            )
        )
    ).all()
    for row in rows:
        st = row.funnel_stage or "planning"
        if st == "radar_intake":
            stats["radar"] += 1
        elif st in stats:
            stats[st] += 1
    return stats


async def get_phase_detail(session: AsyncSession, phase_id: int) -> Optional[dict[str, Any]]:
    ph = await session.scalar(
        select(StrategicPhase)
        .options(
            selectinload(StrategicPhase.board),
            selectinload(StrategicPhase.watch_symbols),
            selectinload(StrategicPhase.probes),
        )
        .where(StrategicPhase.id == phase_id)
    )
    if ph is None:
        return None

    probes = await get_phase_probe_status(session, phase_id)
    symbols = await phase_symbol_rows(session, ph)
    reviews = (
        await session.scalars(
            select(StrategicPhaseReview)
            .where(StrategicPhaseReview.phase_id == phase_id)
            .order_by(StrategicPhaseReview.created_at.desc())
            .limit(5)
        )
    ).all()

    return {
        "id": ph.id,
        "board_id": ph.board_id,
        "board_name": ph.board.name if ph.board else "",
        "wave_no": ph.wave_no,
        "name": ph.name,
        "start_year": ph.start_year,
        "end_year": ph.end_year,
        "situation_md": ph.situation_md,
        "playbook_md": ph.playbook_md,
        "cso_barbell_pct_json": ph.cso_barbell_pct_json,
        "layer": ph.layer,
        "s_curve_position": ph.s_curve_position,
        "niche_template_json": ph.niche_template_json,
        "concurrent_with_json": ph.concurrent_with_json,
        "progress_pct": phase_progress_pct(ph.start_year, ph.end_year),
        "probes": probes,
        "symbols": symbols,
        "stats": await phase_funnel_stats(session, phase_id),
        "barbell_config_json": ph.board.barbell_config_json if ph.board else None,
        "reviews": [
            {"id": r.id, "review_md": r.review_md, "created_at": r.created_at.isoformat()}
            for r in reviews
        ],
    }


async def phase_symbol_rows(session: AsyncSession, ph: StrategicPhase) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    funnel_map: dict[str, str] = {}
    sym_set = [normalize_symbol(w.symbol) for w in ph.watch_symbols]
    if sym_set:
        for cs in (
            await session.scalars(
                select(CampaignSymbol).where(
                    CampaignSymbol.symbol.in_(sym_set),
                    CampaignSymbol.ui_removed_at.is_(None),
                )
            )
        ).all():
            funnel_map[cs.symbol or ""] = cs.funnel_stage

    for w in ph.watch_symbols:
        sym = normalize_symbol(w.symbol)
        rows.append(
            {
                "symbol": sym,
                "role_tag": w.role_tag,
                "watch_only": w.watch_only,
                "funnel_stage": funnel_map.get(sym),
                "source": w.source,
            }
        )
    return rows


async def get_phase_probe_status(session: AsyncSession, phase_id: int) -> list[dict[str, Any]]:
    """P0：无 T0 联通时全部 pending（no-mock）。"""
    configured = (
        await session.scalars(
            select(StrategicPhaseProbe)
            .where(StrategicPhaseProbe.phase_id == phase_id, StrategicPhaseProbe.enabled.is_(True))
            .order_by(StrategicPhaseProbe.layer, StrategicPhaseProbe.probe_key)
        )
    ).all()
    out: list[dict[str, Any]] = []
    for row in configured:
        meta = catalog_entry(row.probe_key)
        out.append(
            {
                "probe_key": row.probe_key,
                "layer": row.layer,
                "label": meta["label"],
                "cadence": row.cadence or meta["cadence"],
                "source_hint": meta["source_hint"],
                "status": "pending",
                "latest_value": None,
                "blocker": "T0 采集未联通 · P2 待接入",
                "red_flag_rule_json": row.red_flag_rule_json,
            }
        )
    return out


async def seed_ai_ecosystem_board(session: AsyncSession) -> StrategicBoard:
    existing = await session.scalar(
        select(StrategicBoard).where(StrategicBoard.name == AI_ECOSYSTEM_SEED["name"]).limit(1)
    )
    if existing:
        return existing
    board, _ = await _create_board_from_payload(session, AI_ECOSYSTEM_SEED)
    return board


async def create_board(
    session: AsyncSession,
    *,
    name: str,
    horizon_start: int,
    horizon_end: int,
    qualitative_md: str = "",
    color_token: str = "indigo",
    load_template: bool = False,
) -> StrategicBoard:
    if load_template:
        return await seed_ai_ecosystem_board(session)
    payload = {
        "name": name,
        "horizon_start": horizon_start,
        "horizon_end": horizon_end,
        "qualitative_md": qualitative_md,
        "color_token": color_token,
        "barbell_config_json": None,
        "phases": [],
    }
    board, _ = await _create_board_from_payload(session, payload)
    return board


async def _create_board_from_payload(
    session: AsyncSession, payload: dict
) -> tuple[StrategicBoard, list[StrategicPhase]]:
    board = StrategicBoard(
        name=payload["name"],
        horizon_start=int(payload["horizon_start"]),
        horizon_end=int(payload["horizon_end"]),
        qualitative_md=payload.get("qualitative_md"),
        barbell_config_json=payload.get("barbell_config_json"),
        color_token=payload.get("color_token") or "indigo",
        is_template=bool(payload.get("is_template", False)),
    )
    session.add(board)
    await session.flush()

    created_phases: list[StrategicPhase] = []
    for idx, ph_data in enumerate(payload.get("phases") or []):
        ph = StrategicPhase(
            board_id=board.id,
            wave_no=int(ph_data.get("wave_no") or idx + 1),
            name=ph_data["name"],
            start_year=int(ph_data["start_year"]),
            end_year=int(ph_data["end_year"]),
            situation_md=ph_data.get("situation_md"),
            playbook_md=ph_data.get("playbook_md"),
            cso_barbell_pct_json=ph_data.get("cso_barbell_pct_json"),
            sort_order=idx,
        )
        session.add(ph)
        await session.flush()
        created_phases.append(ph)

        for sym, role in ph_data.get("symbols") or []:
            session.add(
                StrategicPhaseSymbol(
                    phase_id=ph.id,
                    symbol=normalize_symbol(sym),
                    role_tag=role,
                    watch_only=True,
                    source="seed",
                )
            )

        for probe_key in ph_data.get("probes") or []:
            if probe_key not in JL_PROBE_CATALOG:
                continue
            meta = catalog_entry(probe_key)
            session.add(
                StrategicPhaseProbe(
                    phase_id=ph.id,
                    probe_key=probe_key,
                    layer=meta["layer"],
                    cadence=meta["cadence"],
                    enabled=True,
                )
            )

    await session.flush()
    return board, created_phases


async def delete_board(session: AsyncSession, board_id: int) -> bool:
    """删除板块，级联删除其 phases/symbols/probes/cvm scorecards。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return False
    await session.delete(board)
    await session.flush()
    return True


async def update_board(
    session: AsyncSession,
    board_id: int,
    *,
    name: str,
    horizon_start: int,
    horizon_end: int,
    sector: str,
    concept_names: list[str],
    bom_node_ids: list[str] | None = None,
) -> bool:
    """更新板块基本信息与赛道/概念/时间骨架。清除生态位分析结果（需重新触发）。"""
    board = await session.get(StrategicBoard, board_id)
    if not board:
        return False
    board.name = name.strip()
    board.horizon_start = horizon_start
    board.horizon_end = horizon_end
    # 更新 barbell_config_json 中 genesis 相关信息
    bcj = dict(board.barbell_config_json or {})
    bcj["genesis_sector"] = sector
    bcj["genesis_concepts"] = concept_names
    # 存储选中的 BOM 节点（优先从定制化 YAML 查找节点名称，回退到 ID）
    from apps.copilot.modules.strategic.render import load_curated_bom
    curated = load_curated_bom(sector)
    bom_lookup: dict[str, dict] = {n["node_id"]: n for n in curated if n.get("node_id")}
    bcj["genesis_bom_nodes"] = [
        {
            "node_id": nid,
            "name": bom_lookup.get(nid, {}).get("name", nid),
            "tier": bom_lookup.get(nid, {}).get("tier", "配套"),
            "layer": bom_lookup.get(nid, {}).get("layer") or None,
        }
        for nid in bom_node_ids
    ] if bom_node_ids else []
    board.barbell_config_json = bcj
    # 清除旧生态位分析结果（需重新触发）
    board.stock_pool_json = None
    await session.flush()
    return True


async def add_phase_review(
    session: AsyncSession,
    phase_id: int,
    review_md: str,
    trigger_summary: Optional[dict] = None,
) -> StrategicPhaseReview:
    row = StrategicPhaseReview(
        phase_id=phase_id,
        review_md=review_md.strip(),
        trigger_summary_json=trigger_summary,
    )
    session.add(row)
    await session.flush()
    return row


async def list_board_phase_options(session: AsyncSession) -> list[dict[str, Any]]:
    """晋级/改标 Modal 用：板块 → 阶段 → 角色列表。"""
    boards = (
        await session.scalars(
            select(StrategicBoard)
            .options(
                selectinload(StrategicBoard.phases).selectinload(
                    StrategicPhase.watch_symbols
                )
            )
            .order_by(StrategicBoard.updated_at.desc())
        )
    ).all()
    out: list[dict[str, Any]] = []
    for b in boards:
        phases: list[dict[str, Any]] = []
        for ph in sorted(b.phases, key=lambda p: (p.sort_order, p.wave_no)):
            roles = sorted(
                {w.role_tag for w in ph.watch_symbols if w.role_tag}
            )
            phases.append(
                {
                    "phase_id": ph.id,
                    "wave_no": ph.wave_no,
                    "name": ph.name,
                    "label": f"{ph.name} ({ph.start_year}-{ph.end_year})",
                    "roles": roles,
                }
            )
        out.append(
            {
                "board_id": b.id,
                "board_name": b.name,
                "color_token": b.color_token,
                "phases": phases,
            }
        )
    return out


async def suggest_tag_for_symbol(
    session: AsyncSession,
    symbol: str,
) -> Optional[dict[str, Any]]:
    """规则建议：猎物池命中 > 板块当前活跃阶段。"""
    sym = normalize_symbol(symbol)
    hit_row = (
        await session.execute(
            select(StrategicPhaseSymbol, StrategicPhase, StrategicBoard)
            .join(StrategicPhase, StrategicPhase.id == StrategicPhaseSymbol.phase_id)
            .join(StrategicBoard, StrategicBoard.id == StrategicPhase.board_id)
            .where(StrategicPhaseSymbol.symbol == sym)
            .limit(1)
        )
    ).first()
    if hit_row:
        ps, ph, b = hit_row
        return {
            "board_id": b.id,
            "phase_id": ph.id,
            "role_tag": ps.role_tag,
            "reason": f"已在「{b.name}」猎物池",
        }
    boards = (
        await session.scalars(
            select(StrategicBoard).options(selectinload(StrategicBoard.phases))
        )
    ).all()
    for b in boards:
        active = active_phase_for_board(list(b.phases))
        if active:
            return {
                "board_id": b.id,
                "phase_id": active.id,
                "role_tag": None,
                "reason": f"匹配板块「{b.name}」当前活跃阶段",
            }
    return None


async def get_primary_tags_map(
    session: AsyncSession, symbols: list[str]
) -> dict[str, dict[str, Any]]:
    syms = [normalize_symbol(s) for s in symbols if s]
    if not syms:
        return {}
    rows = (
        await session.scalars(
            select(SymbolStrategicTag)
            .where(
                SymbolStrategicTag.symbol.in_(syms),
                SymbolStrategicTag.is_primary.is_(True),
            )
        )
    ).all()
    if not rows:
        return {}
    board_ids = {r.board_id for r in rows}
    phase_ids = {r.phase_id for r in rows}
    boards = {
        b.id: b
        for b in (
            await session.scalars(
                select(StrategicBoard).where(StrategicBoard.id.in_(board_ids))
            )
        ).all()
    }
    phases = {
        p.id: p
        for p in (
            await session.scalars(
                select(StrategicPhase).where(StrategicPhase.id.in_(phase_ids))
            )
        ).all()
    }
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        sym = normalize_symbol(r.symbol)
        b = boards.get(r.board_id)
        ph = phases.get(r.phase_id)
        out[sym] = {
            "board_id": r.board_id,
            "phase_id": r.phase_id,
            "board_name": b.name if b else "",
            "phase_name": ph.name if ph else "",
            "wave_no": ph.wave_no if ph else None,
            "role_tag": r.role_tag,
            "color_token": (b.color_token if b else "indigo"),
            "tagged_from": r.tagged_from,
        }
    return out


async def jl_summary_for_phase(session: AsyncSession, phase_id: int) -> str:
    probes = await get_phase_probe_status(session, phase_id)
    counts = {"red": 0, "yellow": 0, "green": 0, "pending": 0}
    for p in probes:
        st = p.get("status") or "pending"
        counts[st if st in counts else "pending"] += 1
    parts = []
    if counts["red"]:
        parts.append(f"🔴{counts['red']}")
    if counts["yellow"]:
        parts.append(f"🟡{counts['yellow']}")
    if counts["green"]:
        parts.append(f"🟢{counts['green']}")
    if not parts:
        parts.append(f"⚪{counts['pending']}")
    return " · ".join(parts)


async def upsert_primary_strategic_tag(
    session: AsyncSession,
    symbol: str,
    *,
    board_id: int,
    phase_id: int,
    role_tag: Optional[str] = None,
    tagged_from: str = "manual",
    add_to_watchlist: bool = False,
) -> SymbolStrategicTag:
    sym = normalize_symbol(symbol)
    existing_rows = (
        await session.scalars(
            select(SymbolStrategicTag).where(SymbolStrategicTag.symbol == sym)
        )
    ).all()
    for row in existing_rows:
        row.is_primary = False

    match = await session.scalar(
        select(SymbolStrategicTag).where(
            SymbolStrategicTag.symbol == sym,
            SymbolStrategicTag.phase_id == phase_id,
        )
    )
    if match:
        match.is_primary = True
        match.board_id = board_id
        match.role_tag = role_tag or match.role_tag
        match.tagged_from = tagged_from
        tag = match
    else:
        tag = SymbolStrategicTag(
            symbol=sym,
            board_id=board_id,
            phase_id=phase_id,
            role_tag=role_tag,
            is_primary=True,
            tagged_from=tagged_from,
        )
        session.add(tag)

    if add_to_watchlist:
        ws = await session.scalar(
            select(StrategicPhaseSymbol).where(
                StrategicPhaseSymbol.phase_id == phase_id,
                StrategicPhaseSymbol.symbol == sym,
            )
        )
        if ws is None:
            session.add(
                StrategicPhaseSymbol(
                    phase_id=phase_id,
                    symbol=sym,
                    role_tag=role_tag,
                    watch_only=False,
                    source=tagged_from,
                )
            )
        elif role_tag and not ws.role_tag:
            ws.role_tag = role_tag

    await session.flush()
    return tag


async def clear_primary_strategic_tag(session: AsyncSession, symbol: str) -> None:
    sym = normalize_symbol(symbol)
    rows = (
        await session.scalars(
            select(SymbolStrategicTag).where(
                SymbolStrategicTag.symbol == sym,
                SymbolStrategicTag.is_primary.is_(True),
            )
        )
    ).all()
    for r in rows:
        r.is_primary = False
    await session.flush()
