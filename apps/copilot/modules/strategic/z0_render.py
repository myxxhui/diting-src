"""Z0 前端 partial 渲染（Jinja2）。

[Ref: 33_ §4 · §8]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TPL_DIR = Path(__file__).resolve().parents[2] / "templates" / "planning"
_env = Environment(
    loader=FileSystemLoader(str(_TPL_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _render(name: str, **ctx: Any) -> str:
    return _env.get_template(name).render(**ctx)


def render_wind_scan_panel(scan: Optional[dict[str, Any]]) -> str:
    return _render("_wind_scan_panel.html", scan=scan)


def render_p0_regime_banner(p0: Optional[dict[str, Any]]) -> str:
    return _render("_p0_regime_banner.html", p0=p0 or {})


def render_genesis_wizard(
    *,
    step: int = 1,
    wind_scan: Optional[dict[str, Any]] = None,
    preview: Optional[dict[str, Any]] = None,
    error: str = "",
    candidates: Optional[list[dict[str, Any]]] = None,
    boards: Optional[list[dict[str, Any]]] = None,
) -> str:
    return _render(
        "_genesis_wizard.html",
        step=step,
        wind_scan=wind_scan,
        preview=preview,
        error=error,
        candidates=candidates or [],
        boards=boards or [],
    )


def render_cvm_matrix_table(
    phase_id: int,
    rows: list[dict[str, Any]],
    *,
    dispatch: Optional[dict[str, Any]] = None,
    error: str = "",
) -> str:
    return _render(
        "_cvm_matrix_table.html",
        phase_id=phase_id,
        rows=rows,
        dispatch=dispatch,
        error=error,
    )


def render_core_pool_panel(
    phase_id: int,
    pool: list[dict[str, Any]],
    *,
    dispatch: Optional[dict[str, Any]] = None,
) -> str:
    return _render(
        "_core_pool_panel.html",
        phase_id=phase_id,
        pool=pool,
        dispatch=dispatch,
    )


def render_left_sidebar_z0(
    *,
    mode: str,
    boards: list[dict[str, Any]],
    selected_board_id: Optional[int] = None,
    wind_scan: Optional[dict[str, Any]] = None,
) -> str:
    return _render(
        "_left_sidebar_z0.html",
        mode=mode,
        boards=boards,
        selected_board_id=selected_board_id,
        wind_scan=wind_scan,
    )


def render_sector_detail_body(detail: dict[str, Any]) -> str:
    return _render("_sector_detail_body.html", detail=detail)
