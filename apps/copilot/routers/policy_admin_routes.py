"""Z0 政策 T0 Admin API 路由。

[Ref: 36_ §9 · 通用管理面板 · 供 HTMX 前端加载]
"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from apps.copilot.modules.policy_admin.render import (
    render_admin_index_page,
    render_document_detail_page,
    render_documents_page,
    render_matrix_page,
    render_sources_page,
    render_timeline_page,
)
from apps.copilot.modules.policy_admin.service import (
    get_all_configured_source_keys,
    get_all_sources,
    get_document_detail,
    get_event_timeline,
    get_sector_source_matrix,
    get_source_display_map,
    query_documents,
)
from apps.copilot.services.deepsea.policy_reader import load_policy_keywords

router = APIRouter(tags=["z0-policy-admin"])


@router.get("/z0/policy/admin", response_class=HTMLResponse)
@router.get("/api/z0/policy/admin", response_class=HTMLResponse)
async def z0_policy_admin_page(request: Request):
    """政策数据管理面板入口页（全页 + HTMX 兼容）。"""
    templates = request.app.state.templates
    return templates.TemplateResponse(request, "policy_admin/index.html", {"request": request})


@router.get("/api/z0/policy/admin/sources", response_class=HTMLResponse)
async def z0_policy_admin_sources():
    """数据源健康总览（Partial HTML）。"""
    sources = get_all_sources()
    return render_sources_page(sources)


@router.get("/api/z0/policy/admin/documents", response_class=HTMLResponse)
async def z0_policy_admin_documents(
    source: str = Query(""),
    sector: str = Query(""),
    limit: int = Query(100),
    offset: int = Query(0),
):
    """政策文档浏览器（Partial HTML）。"""
    docs, total = query_documents(
        source=source or None,
        sector=sector or None,
        limit=limit,
        offset=offset,
    )
    # 使用全量已配置数据源列表（不依赖查询结果），修复切换源后选项消失的 bug
    all_sources_list = get_all_configured_source_keys()
    source_display = get_source_display_map()
    kws = load_policy_keywords()
    all_sectors_list = sorted((kws.get("sector_aliases") or {}).keys())
    return render_documents_page(
        docs=docs,
        total=total,
        all_sources=all_sources_list,
        all_sectors=all_sectors_list,
        current_source=source,
        current_sector=sector,
        source_display=source_display,
    )


@router.get("/api/z0/policy/admin/document/{doc_id}", response_class=HTMLResponse)
async def z0_policy_admin_document_detail(doc_id: str):
    """单篇文档详情（Partial HTML，含全文展示）。"""
    doc = get_document_detail(doc_id)
    return render_document_detail_page(doc)


@router.get("/api/z0/policy/admin/matrix", response_class=HTMLResponse)
async def z0_policy_admin_matrix():
    """赛道×数据源矩阵（Partial HTML）。"""
    matrix = get_sector_source_matrix()
    source_display = get_source_display_map()
    all_sectors = sorted((load_policy_keywords().get("sector_aliases") or {}).keys())
    return render_matrix_page(matrix, source_display=source_display, all_sectors=all_sectors)


@router.get("/api/z0/policy/admin/timeline", response_class=HTMLResponse)
async def z0_policy_admin_timeline():
    """事件时间线（Partial HTML）。"""
    events = get_event_timeline(days=180, limit=100)
    source_display = get_source_display_map()
    return render_timeline_page(events, source_display=source_display)
