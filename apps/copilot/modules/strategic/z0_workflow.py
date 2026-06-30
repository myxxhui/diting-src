"""Z0 指标先行工作流 · wind_scan / genesis / CVM / dispatch。

[Ref: 33_ §4 · §10.1 · 32_ §2.4]
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.copilot.db.models import (
    CvmScorecard,
    ScanDispatch,
    ScanDispatchAudit,
    StrategicBoard,
    StrategicPhase,
    StrategicPhaseSymbol,
    WindScan,
)
from apps.copilot.modules.strategic.cvm_scorer import score_peer_set
from apps.copilot.modules.strategic.service import get_board_detail, get_phase_detail

_GENESIS_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "config" / "strategic_board_genesis_template.yaml"
)


def _load_genesis_template() -> dict[str, Any]:
    if _GENESIS_TEMPLATE_PATH.is_file():
        with open(_GENESIS_TEMPLATE_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"template_version": "1.0", "default_horizon_years": 10, "default_phases": []}


def wind_scan_to_dict(row: WindScan) -> dict[str, Any]:
    return {
        "id": row.id,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "p0_snapshot": row.p0_snapshot_json or {},
        "candidates": row.candidates_json or [],
        "status": row.status,
        "blocker": row.blocker,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def get_latest_wind_scan(session: AsyncSession) -> Optional[dict[str, Any]]:
    q = await session.execute(select(WindScan).order_by(desc(WindScan.id)).limit(1))
    row = q.scalar_one_or_none()
    return wind_scan_to_dict(row) if row else None


def _pg_naive_utc(dt: datetime) -> datetime:
    """PostgreSQL TIMESTAMP WITHOUT TIME ZONE 列 · 写入 naive UTC。"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def persist_wind_scan_from_synthesis(
    session: AsyncSession,
    synth: dict[str, Any],
) -> dict[str, Any]:
    """将 M0 合成结果写入 wind_scans 表。"""
    now = _pg_naive_utc(datetime.now(timezone.utc))
    as_of = now
    as_of_raw = synth.get("as_of")
    if as_of_raw:
        try:
            parsed = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00"))
            as_of = _pg_naive_utc(parsed)
        except ValueError:
            pass
    row = WindScan(
        as_of=as_of,
        p0_snapshot_json=synth.get("p0_snapshot") or {},
        candidates_json=synth.get("candidates") or [],
        status=synth.get("status") or "empty",
        blocker=synth.get("blocker"),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return wind_scan_to_dict(row)


async def run_wind_scan(session: AsyncSession, *, redis_client: Any = None) -> dict[str, Any]:
    """段 A：读 metric 快照 → M0 合成 → 落 wind_scan（no-mock）。"""
    from apps.copilot.metrics.synthesizer.wind_scan import synthesize_wind_scan
    from apps.copilot.metrics.z0_storage import read_metrics_bundle
    from apps.copilot.services.redis_wait import wait_for_sync_redis

    redis = redis_client if redis_client is not None else wait_for_sync_redis()
    metrics = await read_metrics_bundle(session, redis)
    synth = synthesize_wind_scan(metrics)
    return await persist_wind_scan_from_synthesis(session, synth)


def _scorecard_row_dict(sc: CvmScorecard) -> dict[str, Any]:
    role = sc.role_override or sc.role_suggested
    scores = sc.scores_json or {}
    c7 = (scores.get("c7") or {}).get("pass", True)
    return {
        "id": sc.id,
        "phase_id": sc.phase_id,
        "niche_id": sc.niche_id,
        "symbol": sc.symbol,
        "scores": scores,
        "anchor_path": sc.anchor_path,
        "role_suggested": sc.role_suggested,
        "role_effective": role,
        "pool_eligible": sc.pool_eligible,
        "dispatch_selected": sc.dispatch_selected,
        "provisional": sc.provisional,
        "human_confirmed": sc.human_confirmed,
        "c7_pass": c7,
        "override_reason": sc.override_reason,
    }


async def list_cvm_scorecards(session: AsyncSession, phase_id: int) -> list[dict[str, Any]]:
    q = await session.execute(
        select(CvmScorecard)
        .where(CvmScorecard.phase_id == phase_id)
        .order_by(CvmScorecard.symbol)
    )
    return [_scorecard_row_dict(r) for r in q.scalars().all()]


async def run_cvm_for_phase(session: AsyncSession, phase_id: int) -> list[dict[str, Any]]:
    phase = await get_phase_detail(session, phase_id)
    if not phase:
        raise ValueError("阶段不存在")
    niche = (phase.get("niche_template_json") or {}).get("niche_id") or "default"
    peers = [
        {"symbol": s["symbol"], "role_tag": s.get("role_tag")}
        for s in (phase.get("symbols") or [])
    ]
    if not peers:
        raise ValueError("本阶段尚无 peer 候选 · 请先配置猎物池或 genesis niche")

    scored = score_peer_set(peers, niche_id=niche)
    await session.execute(
        CvmScorecard.__table__.delete().where(CvmScorecard.phase_id == phase_id)
    )
    out: list[dict[str, Any]] = []
    for row in scored:
        sc = CvmScorecard(
            phase_id=phase_id,
            niche_id=row["niche_id"],
            symbol=row["symbol"],
            scores_json=row["scores"],
            anchor_path=row["anchor_path"],
            role_suggested=row["role_suggested"],
            pool_eligible=row["pool_eligible"],
            dispatch_selected=row["pool_eligible"],
            provisional=row["provisional"],
        )
        session.add(sc)
        await session.flush()
        out.append(_scorecard_row_dict(sc))
    return out


async def confirm_cvm_pool(
    session: AsyncSession,
    phase_id: int,
    *,
    selected_symbols: list[str],
    role_overrides: Optional[dict[str, str]] = None,
    override_reasons: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    q = await session.execute(select(CvmScorecard).where(CvmScorecard.phase_id == phase_id))
    rows = list(q.scalars().all())
    if not rows:
        raise ValueError("请先运行 CVM 评分")
    sel = {s.strip() for s in selected_symbols if s.strip()}
    now = datetime.now(timezone.utc)
    role_overrides = role_overrides or {}
    override_reasons = override_reasons or {}

    for sc in rows:
        scores = sc.scores_json or {}
        c7_pass = (scores.get("c7") or {}).get("pass", True)
        chosen = sc.symbol in sel and c7_pass and sc.pool_eligible
        sc.dispatch_selected = chosen
        sc.human_confirmed = chosen
        sc.confirmed_at = now if chosen else None
        if sc.symbol in role_overrides:
            raw = role_overrides[sc.symbol] or ""
            if len(raw) > 32:
                raw = raw[:32]
            sc.role_override = raw
            sc.override_reason = override_reasons.get(sc.symbol) or "用户覆盖"
        if chosen:
            sym_row = await session.execute(
                select(StrategicPhaseSymbol).where(
                    StrategicPhaseSymbol.phase_id == phase_id,
                    StrategicPhaseSymbol.symbol == sc.symbol,
                )
            )
            ps = sym_row.scalar_one_or_none()
            if ps:
                ps.source = "cvm_confirmed"
                role = sc.role_override or sc.role_suggested
                if role:
                    ps.role_tag = role
    await session.flush()
    return [_scorecard_row_dict(r) for r in rows]


async def create_scan_dispatch(
    session: AsyncSession,
    phase_id: int,
    *,
    theme: Optional[str] = None,
) -> dict[str, Any]:
    phase = await get_phase_detail(session, phase_id)
    if not phase:
        raise ValueError("阶段不存在")
    q = await session.execute(
        select(CvmScorecard).where(
            CvmScorecard.phase_id == phase_id,
            CvmScorecard.human_confirmed.is_(True),
            CvmScorecard.dispatch_selected.is_(True),
        )
    )
    confirmed = list(q.scalars().all())
    if not confirmed:
        raise ValueError("须先确认 CVM 核心池（human_confirmed）")

    for sc in confirmed:
        c7 = (sc.scores_json or {}).get("c7") or {}
        if not c7.get("pass", True):
            raise ValueError(f"{sc.symbol} C7 未通过 · 不可派单")

    board_id = phase["board_id"]
    symbols = [c.symbol for c in confirmed]
    roles = {
        c.symbol: c.role_override or c.role_suggested or ""
        for c in confirmed
    }
    dispatch_theme = theme or phase.get("name") or "战略扫描"

    old_q = await session.execute(
        select(ScanDispatch).where(
            ScanDispatch.phase_id == phase_id,
            ScanDispatch.status == "active",
        )
    )
    for old in old_q.scalars().all():
        old.status = "superseded"
        session.add(
            ScanDispatchAudit(
                dispatch_id=old.id,
                action="superseded",
                reason_md="新派单覆盖",
            )
        )

    ref = f"cvm://phase/{phase_id}"
    # CVM 快照：供 Z1.5 生意认知引擎 Step3 护城河分析直接消费（避免 Z1.5 再查表）
    cvm_snapshot: dict[str, Any] = {}
    for c in confirmed:
        sc_scores = c.scores_json or {}
        cvm_snapshot[c.symbol] = {
            "role": c.role_override or c.role_suggested or "",
            "anchor_path": c.anchor_path or "",
            "irreplaceability": sc_scores.get("irreplaceability", {}),
            "c7": sc_scores.get("c7", {}),
            "c2_band": (sc_scores.get("c2") or {}).get("band", ""),
            "c4_band": (sc_scores.get("c4") or {}).get("band", ""),
        }
    now = datetime.now(timezone.utc)
    disp = ScanDispatch(
        board_id=board_id,
        phase_id=phase_id,
        layer=phase.get("layer"),
        theme=dispatch_theme,
        symbols_json=symbols,
        symbol_roles_json=roles,
        cvm_scorecard_ref=ref,
        ecosystem_e1_e5_json=(phase.get("niche_template_json") or {}).get("e1_e5_weights"),
        status="active",
        human_confirmed=True,
        dispatched_at=now,
        genesis_ref_json={
            "board_id": board_id,
            "phase_id": phase_id,
            "cvm_snapshot": cvm_snapshot,
        },
    )
    session.add(disp)
    await session.flush()
    session.add(
        ScanDispatchAudit(dispatch_id=disp.id, action="dispatch", reason_md=dispatch_theme)
    )
    return dispatch_to_dict(disp)


def dispatch_to_dict(d: ScanDispatch) -> dict[str, Any]:
    return {
        "id": d.id,
        "board_id": d.board_id,
        "phase_id": d.phase_id,
        "layer": d.layer,
        "theme": d.theme,
        "symbols": d.symbols_json or [],
        "symbol_roles": d.symbol_roles_json or {},
        "cvm_scorecard_ref": d.cvm_scorecard_ref,
        "status": d.status,
        "dispatched_at": d.dispatched_at.isoformat() if d.dispatched_at else None,
    }


async def get_active_dispatch_for_phase(
    session: AsyncSession, phase_id: int
) -> Optional[dict[str, Any]]:
    q = await session.execute(
        select(ScanDispatch)
        .where(ScanDispatch.phase_id == phase_id, ScanDispatch.status == "active")
        .order_by(desc(ScanDispatch.id))
        .limit(1)
    )
    row = q.scalar_one_or_none()
    return dispatch_to_dict(row) if row else None


async def revoke_dispatch(session: AsyncSession, dispatch_id: int) -> dict[str, Any]:
    disp = await session.get(ScanDispatch, dispatch_id)
    if not disp:
        raise ValueError("派单不存在")
    disp.status = "revoked"
    disp.revoked_at = datetime.now(timezone.utc)
    session.add(
        ScanDispatchAudit(dispatch_id=disp.id, action="revoked", reason_md="用户撤销")
    )
    return dispatch_to_dict(disp)


async def genesis_preview(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """段 B · genesis 预览（不落库）。"""
    tmpl = _load_genesis_template()
    wind_id = payload.get("wind_scan_id")
    candidates = payload.get("candidates") or []
    title = (payload.get("board_title") or "").strip() or "新战略板块"
    horizon = int(payload.get("horizon_years") or tmpl.get("default_horizon_years") or 10)
    start_year = int(payload.get("start_year") or datetime.now().year)
    phases_in = payload.get("phases") or tmpl.get("default_phases") or []
    end_year = start_year + horizon

    phases = []
    cursor = start_year
    for i, ph in enumerate(phases_in[:4]):
        yrs = int(ph.get("window_years") or 3)
        pe = cursor + yrs - 1
        phases.append(
            {
                "wave_no": ph.get("wave_no") or (i + 1),
                "name": f"{ph.get('name_suffix') or f'第{i+1}波'} · {title[:12]}",
                "start_year": cursor,
                "end_year": pe,
                "layer": ph.get("layer") or "infra",
                "s_curve_position": ph.get("s_curve_position") or "early",
            }
        )
        cursor = pe + 1

    return {
        "board_title": title,
        "horizon_start": start_year,
        "horizon_end": end_year,
        "source_wind_scan_id": wind_id,
        "candidates": candidates,
        "phases": phases,
        "template_version": tmpl.get("template_version", "1.0"),
    }


async def genesis_apply(session: AsyncSession, payload: dict[str, Any]) -> StrategicBoard:
    from apps.copilot.modules.strategic.service import _create_board_from_payload

    preview = await genesis_preview(session, payload)
    barbell = payload.get("barbell_config_json") or None
    selected_concepts = payload.get("selected_concepts") or []
    selected_sector = payload.get("sector") or ""
    selected_bom_nodes = payload.get("selected_bom_nodes") or []
    if not barbell and (selected_concepts or selected_sector or selected_bom_nodes):
        # 查找官方展示名（AI算力 → 人工智能产业）
        _dname = selected_sector
        try:
            from pathlib import Path
            import yaml as _yaml
            _p = Path(__file__).resolve().parents[4] / "data" / "config" / "metrics" / "z0_policy_keywords.yaml"
            with _p.open(encoding="utf-8") as _f:
                _cfg = _yaml.safe_load(_f) or {}
            _cs = (_cfg.get("canonical_sectors") or {}).get(selected_sector) or {}
            _dname = str(_cs.get("display_name") or selected_sector)
        except Exception:
            pass
        barbell = {
            "genesis_sector": selected_sector,
            "genesis_sector_display_name": _dname,
            "genesis_concepts": selected_concepts,
            "genesis_bom_nodes": [
                {"node_id": n["node_id"], "name": n.get("name", n["node_id"]), "tier": n.get("tier", "配套"), "layer": n.get("layer") or None, "representative_stocks": n.get("representative_stocks") or []}
                for n in selected_bom_nodes
            ],
        }
    board_payload = {
        "name": preview["board_title"],
        "horizon_start": preview["horizon_start"],
        "horizon_end": preview["horizon_end"],
        "qualitative_md": (payload.get("qualitative_md") or "").strip()
        or f"智能建板 · 候选 {len(preview.get('candidates') or [])} 项",
        "color_token": "indigo",
        "barbell_config_json": barbell,
        "phases": preview.get("phases") or [],
    }
    board, phases = await _create_board_from_payload(session, board_payload)
    if preview.get("source_wind_scan_id"):
        board.source_wind_scan_id = int(preview["source_wind_scan_id"])

    # v5.1: 保存 LLM 生态位推断标的池
    stock_pool_raw = payload.get("stock_pool_json")
    if stock_pool_raw:
        import json as _json
        if isinstance(stock_pool_raw, str):
            try:
                stock_pool_raw = _json.loads(stock_pool_raw)
            except _json.JSONDecodeError:
                pass
        if isinstance(stock_pool_raw, dict):
            board.stock_pool_json = stock_pool_raw

            # 自动填充第一阶段 symbols
            pools = stock_pool_raw.get("concept_pools") or []
            seen_symbols: set[str] = set()
            first_phase = phases[0] if phases else None
            if first_phase:
                for pool in pools:
                    for stock in (pool.get("stocks") or []):
                        sym = str(stock.get("symbol", "")).strip()
                        if not sym or not sym.isdigit() or len(sym) != 6:
                            continue
                        if sym in seen_symbols:
                            continue
                        seen_symbols.add(sym)
                        from apps.copilot.db.models import StrategicPhaseSymbol
                        session.add(StrategicPhaseSymbol(
                            phase_id=first_phase.id,
                            symbol=sym,
                            role_tag=str(stock.get("ecosystem_position", "")),
                            watch_only=True,
                            source="genesis_llm",
                        ))

    niche_layers = payload.get("niche_layers") or []
    default_weights = (_load_genesis_template().get("niche_defaults") or {}).get(
        "e1_e5_weights"
    ) or {"e1": 0.25, "e2": 0.2, "e3": 0.2, "e4": 0.2, "e5": 0.15}

    for i, ph in enumerate(phases):
        niche = niche_layers[i] if i < len(niche_layers) else {}
        ph.niche_template_json = {
            "niche_id": niche.get("niche_id") or f"niche-{ph.wave_no}",
            "e1_e5_weights": niche.get("e1_e5_weights") or default_weights,
            "peer_list": niche.get("peer_list") or [],
        }
        preview_ph = (preview.get("phases") or [])[i] if i < len(preview.get("phases") or []) else {}
        ph.layer = preview_ph.get("layer") or ph.layer
        ph.s_curve_position = preview_ph.get("s_curve_position")
    await session.flush()
    return board


async def get_confirmed_core_pool(session: AsyncSession, phase_id: int) -> list[dict[str, Any]]:
    q = await session.execute(
        select(CvmScorecard).where(
            CvmScorecard.phase_id == phase_id,
            CvmScorecard.human_confirmed.is_(True),
        )
    )
    out = []
    for sc in q.scalars().all():
        row = _scorecard_row_dict(sc)
        if row.get("c7_pass"):
            out.append(row)
    return out
