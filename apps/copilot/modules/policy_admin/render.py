"""Z0 政策 T0 Admin 渲染器。

[Ref: 36_ §9]
"""
from __future__ import annotations

import html as html_mod
from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 使用 templates/ 作为根目录，policy_admin/ 下模板引用 base.html 用相对路径
_TEMPLATES_DIR = _BASE_DIR / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def esc(v: Any) -> str:
    return html_mod.escape(str(v if v is not None else ""))


def render_sources_page(sources: list[dict[str, Any]]) -> str:
    return _templates.get_template("policy_admin/_sources.html").render(sources=sources)


def render_documents_page(
    docs: list[dict[str, Any]],
    total: int,
    all_sources: list[str],
    all_sectors: list[str],
    current_source: str = "",
    current_sector: str = "",
    source_display: dict[str, str] | None = None,
) -> str:
    return _templates.get_template("policy_admin/_documents.html").render(
        docs=docs,
        total=total,
        all_sources=all_sources,
        all_sectors=all_sectors,
        current_source=current_source,
        current_sector=current_sector,
        source_display=source_display or {},
    )


def render_document_detail_page(doc: dict[str, Any] | None) -> str:
    return _templates.get_template("policy_admin/_document_detail.html").render(doc=doc)


def render_matrix_page(matrix: dict[str, Any], source_display: dict[str, str] | None = None, all_sectors: list[str] | None = None) -> str:
    return _templates.get_template("policy_admin/_matrix.html").render(
        matrix=matrix,
        source_display=source_display or {},
        all_sectors=all_sectors or [],
    )


def render_timeline_page(events: list[dict[str, Any]], source_display: dict[str, str] | None = None) -> str:
    return _templates.get_template("policy_admin/_timeline.html").render(
        events=events,
        source_display=source_display or {},
    )


def render_admin_index_page() -> str:
    return _templates.get_template("policy_admin/index.html").render()
