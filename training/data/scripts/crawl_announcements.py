"""重点公司公告采集：默认巨潮资讯 PDF 全文 + 元数据（免费公开披露）。

与 ``crawl_financial_reports`` 共用 ``.env`` / ``CRYO_CRAWL_CONFIG``、标的与时间窗
（``env_crawl_interval_dates``）。

**ORM**：指 SQLAlchemy 模型与 SQLite 表映射（见 ``apps/cryo_guard/db/models.py``）。
写入表 ``announcements``（字段含 ``content`` 正文、``url`` 巨潮详情页、``raw_json`` 原始 JSON）。

后端选择：

  CRYO_ANN_BACKEND=cninfo（默认）— 巨潮列表 + ``static.cninfo`` PDF 抽取正文
  CRYO_ANN_BACKEND=eastmoney — 仅东财元数据（无可靠全文时不推荐）

巨潮正文：

  CRYO_ANN_FETCH_FULLTEXT=1（默认）— 拉 PDF 并抽取文本写入 ``content``；设为 0 则仅元数据
  CRYO_ANN_PDF_MAX_BYTES / CRYO_ANN_PDF_MAX_PAGES / CRYO_ANN_PDF_MAX_CHARS — 控制体积

分页与限量：

  CRYO_ANN_PAGE_SIZE — 巨潮每页条数（默认 30）
  CRYO_ANN_MAX_PAGES — 最大翻页数（不限则不设）
  CRYO_ANN_MAX_ITEMS — 每只股票最多入库条数（默认 200，按通过分类后的公告计）

  CRYO_ANN_ENRICH_EMPTY=1 — 仅对库内「正文过短/空」的公告按日匹配巨潮并回填 PDF 文本（适合先前东财入库）
  CRYO_ANN_ENRICH_MIN_LEN — 视为需补全的正文长度上限（默认 80）
  CRYO_ANN_ENRICH_MAX — 每只股票最多补全条数（默认 300）
  CRYO_ANN_ENRICH_MAX_PAGES — 单日检索最大翻页（默认 15）

仍仅入库可归入「增持/减持/业绩/质押/战略」的标题（与东财路径一致）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

import logging
import os
import time
from typing import Any, Iterable

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tqdm import tqdm

from apps.cryo_guard.cninfo_client import (
    fetch_cninfo_adjunct_pdf_text,
    iter_cninfo_announcements,
)
from apps.cryo_guard.db.models import Announcement
from apps.cryo_guard.db.sync_session import session_scope
from training.data.scripts.crawl_financial_reports import (
    env_crawl_interval_dates,
    env_throttle_sec,
    get_all_a_stock_symbols,
)

logger = logging.getLogger(__name__)

ANN_TYPES = (
    "增持", "减持", "业绩", "质押", "战略",
    "人事变动", "监管问询", "关联交易",
)

_EM_ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _symbol_to_stock_list_param(symbol: str) -> str:
    """东财 ``stock_list`` 用 6 位代码（无 sh/sz 前缀）。"""
    s = symbol.strip().lower()
    for p in ("sh", "sz", "bj"):
        if s.startswith(p):
            s = s[len(p) :]
            break
    if not s.isdigit():
        return symbol.strip()[-6:].zfill(6)
    return s.zfill(6)[-6:]


def _parse_notice_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, (int, float)):
        ts = float(val)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.utcfromtimestamp(ts).date()
    s = str(val).strip().replace("/", "-")
    if len(s) >= 10:
        s = s[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _cninfo_ms_to_date(ms: Any) -> date | None:
    try:
        v = int(ms)
        return datetime.fromtimestamp(v / 1000.0, tz=_SH_TZ).date()
    except (TypeError, ValueError, OSError):
        return None


def _cninfo_detail_url(sec_code: str, announcement_id: str, org_id: str, announcement_time_ms: int) -> str:
    d = datetime.fromtimestamp(announcement_time_ms / 1000.0, tz=_SH_TZ).strftime("%Y-%m-%d")
    return (
        f"http://www.cninfo.com.cn/new/disclosure/detail?stockCode={sec_code}"
        f"&announcementId={announcement_id}&orgId={org_id}&announcementTime={d}"
    )


def _classify_ann_type(title: str, column_name: str) -> str | None:
    t = f"{title or ''} {(column_name or '')}"
    if any(k in t for k in (
        "聘任", "辞任", "辞职", "离任", "调任", "选举", "罢免",
        "独立董事", "总裁", "总经理", "副总经理", "财务总监",
        "董事会秘书", "董秘", "高级管理人员", "高管", "监事会",
        "董事变更", "监事变更", "管理层变动",
    )):
        return "人事变动"
    if any(k in t for k in (
        "问询函", "监管函", "警示函", "关注函", "立案", "处罚",
        "行政处罚", "纪律处分", "约谈", "调查", "整改", "责令",
        "通报批评", "公开谴责",
    )):
        return "监管问询"
    if any(k in t for k in ("关联交易", "关联方", "关联企业", "关联担保", "关联购销")):
        return "关联交易"
    if "增持" in t:
        return "增持"
    if "减持" in t:
        return "减持"
    if any(k in t for k in ("质押", "解除质押")):
        return "质押"
    if any(
        k in t
        for k in (
            "业绩", "预告", "快报",
            "年度报告", "半年度报告", "季度报告",
            "一季度", "三季报", "年报", "半年报", "季报",
        )
    ):
        return "业绩"
    if any(k in t for k in ("战略", "合作", "框架协议", "重组", "收购", "对外投资", "合资")):
        return "战略"
    return None


def _ann_fetch_params_em() -> tuple[int, int, float]:
    max_pages = int(os.environ.get("CRYO_ANN_MAX_PAGES", "50"))
    page_size = int(os.environ.get("CRYO_ANN_PAGE_SIZE", "100"))
    throttle = env_throttle_sec()
    return max(1, max_pages), max(1, min(page_size, 200)), max(0.0, throttle)


def _fetch_eastmoney_announcements(
    symbol_6: str,
    begin: date,
    end: date,
) -> list[dict[str, Any]]:
    max_pages, page_size, throttle = _ann_fetch_params_em()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; diting-cryo-guard/1.0; +https://example.invalid)",
        "Accept": "application/json",
    }
    out: list[dict[str, Any]] = []
    begin_s = begin.isoformat()
    end_s = end.isoformat()

    for page in range(1, max_pages + 1):
        params = {
            "sr": "-1",
            "page_size": str(page_size),
            "page_index": str(page),
            "ann_type": "A",
            "client_source": "web",
            "f_node": "0",
            "s_node": "0",
            "begin_time": begin_s,
            "end_time": end_s,
            "stock_list": symbol_6,
        }
        try:
            r = requests.get(_EM_ANN_URL, params=params, headers=headers, timeout=60)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            logger.warning("东财公告 HTTP/JSON 失败 %s page=%s: %s", symbol_6, page, exc)
            break

        data = payload.get("data") or {}
        items = data.get("list") or []
        if not items:
            break

        for item in items:
            codes = item.get("codes") or []
            code0 = codes[0] if codes else {}
            cols = item.get("columns") or []
            col0 = cols[0] if cols else {}
            out.append(
                {
                    "stock_code": str(code0.get("stock_code") or symbol_6),
                    "short_name": code0.get("short_name"),
                    "title": item.get("title") or "",
                    "column_name": col0.get("column_name") or "",
                    "notice_date": item.get("notice_date"),
                    "art_code": item.get("art_code") or "",
                }
            )

        total_hits = int(data.get("total_hits") or 0)
        if page * page_size >= total_hits:
            break
        time.sleep(throttle)

    return out


def _em_notice_url(stock_code: str, art_code: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html"


def _mock_ann_base_date(begin: date, end: date) -> date:
    y_mid = (begin.year + end.year) // 2
    base = date(y_mid, 6, 15)
    if base < begin:
        return begin
    if base > end:
        return end
    return base


def _mock_announcements(symbol: str, company_name: str, begin: date, end: date) -> list[Announcement]:
    rows = []
    base = _mock_ann_base_date(begin, end)
    for i, at in enumerate(ANN_TYPES):
        rows.append(
            Announcement(
                symbol=symbol,
                company_name=company_name,
                ann_type=at,
                title=f"{company_name}{at}相关公告-{i}"[:256],
                ann_date=base,
                content=f"mock body {at}",
                url=None,
                raw_json={"mock": True},
                source="mock",
            )
        )
    return rows


def _crawl_symbol_eastmoney(session: Session, symbol: str, company_name: str) -> int:
    added = 0
    sym6 = _symbol_to_stock_list_param(symbol)
    begin, end = env_crawl_interval_dates()
    logger.info("东财公告 %s (%s) %s ~ %s", company_name, sym6, begin, end)
    try:
        raw_rows = _fetch_eastmoney_announcements(sym6, begin, end)
    except Exception as exc:
        logger.warning("东财公告拉取异常 %s: %s", sym6, exc)
        return 0

    for rec in raw_rows:
        title = (rec.get("title") or "")[:256]
        col = rec.get("column_name") or ""
        ann_type = _classify_ann_type(title, col)
        if ann_type is None:
            continue
        ann_d = _parse_notice_date(rec.get("notice_date"))
        if ann_d is None:
            continue
        code = str(rec.get("stock_code") or sym6).zfill(6)[-6:]
        name = str(rec.get("short_name") or company_name)[:64]
        art = rec.get("art_code") or ""
        detail_url = _em_notice_url(code, art) if art else None

        exists = session.scalar(
            select(Announcement.id).where(
                Announcement.symbol == code,
                Announcement.title == title,
                Announcement.ann_date == ann_d,
            )
        )
        if exists:
            continue
        session.add(
            Announcement(
                symbol=code,
                company_name=name,
                ann_type=ann_type,
                title=title,
                ann_date=ann_d,
                content=None,
                url=detail_url,
                raw_json={"eastmoney": rec},
                source="eastmoney",
            )
        )
        added += 1
    return added


def _crawl_symbol_cninfo(session: Session, symbol: str, company_name: str) -> int:
    begin, end = env_crawl_interval_dates()
    start_s = begin.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    sym6 = _symbol_to_stock_list_param(symbol)
    page_size = max(10, min(int(os.environ.get("CRYO_ANN_PAGE_SIZE", "30")), 100))
    mp = os.environ.get("CRYO_ANN_MAX_PAGES", "").strip()
    max_pages = int(mp) if mp.isdigit() else None
    max_items = int(os.environ.get("CRYO_ANN_MAX_ITEMS", "200"))
    throttle = env_throttle_sec()
    fetch_body = os.environ.get("CRYO_ANN_FETCH_FULLTEXT", "1").strip() != "0"

    logger.info("巨潮公告 %s (%s) %s ~ %s", company_name, sym6, begin, end)
    added = 0
    try:
        it = iter_cninfo_announcements(
            sym6,
            start_s,
            end_s,
            category=os.environ.get("CRYO_ANN_CNINFO_CATEGORY", "").strip(),
            keyword=os.environ.get("CRYO_ANN_CNINFO_KEYWORD", "").strip(),
            page_size=page_size,
            max_pages=max_pages,
            throttle_sec=throttle,
        )
    except Exception as exc:
        logger.warning("巨潮公告列表失败 %s: %s", sym6, exc)
        return 0

    for item in it:
        if added >= max_items:
            break
        title = (item.get("announcementTitle") or "")[:256]
        ann_type = _classify_ann_type(title, "")
        if ann_type is None:
            continue
        ann_d = _cninfo_ms_to_date(item.get("announcementTime"))
        if ann_d is None:
            continue
        code = str(item.get("secCode") or sym6).zfill(6)[-6:]
        name = str(item.get("secName") or company_name)[:64]
        aid = str(item.get("announcementId") or "")
        oid = str(item.get("orgId") or "")
        try:
            t_ms = int(item.get("announcementTime") or 0)
        except (TypeError, ValueError):
            t_ms = 0
        detail_url = _cninfo_detail_url(code, aid, oid, t_ms) if aid and oid and t_ms else None

        exists = session.scalar(
            select(Announcement.id).where(
                Announcement.symbol == code,
                Announcement.title == title,
                Announcement.ann_date == ann_d,
            )
        )
        if exists:
            continue

        content: str | None = None
        if fetch_body:
            content = fetch_cninfo_adjunct_pdf_text(item.get("adjunctUrl"), item.get("adjunctType"))
            if not content:
                content = None

        session.add(
            Announcement(
                symbol=code,
                company_name=name,
                ann_type=ann_type,
                title=title,
                ann_date=ann_d,
                content=content,
                url=detail_url[:512] if detail_url else None,
                raw_json={"cninfo": item},
                source="cninfo",
            )
        )
        added += 1

    return added


def _normalize_title(t: str) -> str:
    """东财标题常带「公司名:」前缀，与巨潮标题对齐。"""
    t = (t or "").strip()
    if ":" in t:
        t = t.split(":", 1)[-1].strip()
    if "：" in t:
        t = t.split("：", 1)[-1].strip()
    return t


def _titles_match(db_title: str, cn_title: str) -> bool:
    a = _normalize_title(db_title)
    b = _normalize_title(cn_title)
    if not a or not b:
        return False
    if a == b:
        return True
    n = min(80, len(a), len(b))
    if n >= 12 and a[:n] == b[:n]:
        return True
    if len(a) >= 6 and (a in b):
        return True
    if len(b) >= 6 and (b in a):
        return True
    if len(a) >= 15 and (a in b or b in a):
        return True
    return False


def enrich_symbol_announcement_bodies(session: Session, symbol: str, company_name: str) -> int:
    """对已入库但无正文的公告，按公告日在巨潮检索同名 PDF 并写 ``content``（不新增行）。"""
    sym6 = _symbol_to_stock_list_param(symbol)
    min_len = int(os.environ.get("CRYO_ANN_ENRICH_MIN_LEN", "80"))
    max_upd = int(os.environ.get("CRYO_ANN_ENRICH_MAX", "300"))
    throttle = env_throttle_sec()
    fetch_body = os.environ.get("CRYO_ANN_FETCH_FULLTEXT", "1").strip() != "0"

    stmt = (
        select(Announcement)
        .where(Announcement.symbol == sym6)
        .where((Announcement.content.is_(None)) | (func.length(Announcement.content) < min_len))
    )
    rows = list(session.execute(stmt).scalars().all())
    updated = 0
    for row in rows:
        if updated >= max_upd:
            break
        d = row.ann_date.strftime("%Y%m%d")
        found: dict | None = None
        try:
            for item in iter_cninfo_announcements(
                sym6,
                d,
                d,
                page_size=50,
                max_pages=int(os.environ.get("CRYO_ANN_ENRICH_MAX_PAGES", "15")),
                throttle_sec=throttle,
            ):
                cn_title = item.get("announcementTitle") or ""
                if not _titles_match(row.title, cn_title):
                    continue
                if _classify_ann_type(cn_title, "") != row.ann_type:
                    continue
                found = item
                break
        except Exception as exc:
            logger.warning("巨潮补全检索失败 %s %s %s: %s", sym6, d, row.title[:40], exc)
            continue
        if not found:
            logger.info("巨潮未匹配 %s %s %s", sym6, d, row.title[:50])
            continue
        body = ""
        if fetch_body:
            body = fetch_cninfo_adjunct_pdf_text(found.get("adjunctUrl"), found.get("adjunctType"))
        if not body:
            logger.info("PDF 无文本或需安装 pdfplumber %s %s", sym6, row.title[:40])
            continue
        cap = int(os.environ.get("CRYO_ANN_PDF_MAX_CHARS", "500000"))
        row.content = body[:cap]
        aid = str(found.get("announcementId") or "")
        oid = str(found.get("orgId") or "")
        try:
            t_ms = int(found.get("announcementTime") or 0)
        except (TypeError, ValueError):
            t_ms = 0
        if aid and oid and t_ms:
            row.url = _cninfo_detail_url(sym6, aid, oid, t_ms)[:512]
        row.source = "cninfo"
        base = dict(row.raw_json) if isinstance(row.raw_json, dict) else {}
        base["cninfo_enrich"] = found
        row.raw_json = base
        updated += 1
    if updated:
        logger.info("公告正文补全 %s (%s) %d 条", company_name, sym6, updated)
    return updated


def crawl_symbol(session: Session, symbol: str, company_name: str) -> int:
    if os.environ.get("CRYO_MOCK", "").strip() == "1":
        begin, end = env_crawl_interval_dates()
        added = 0
        for row in _mock_announcements(symbol, company_name, begin, end):
            exists = session.scalar(
                select(Announcement.id).where(
                    Announcement.symbol == row.symbol,
                    Announcement.title == row.title,
                    Announcement.ann_date == row.ann_date,
                )
            )
            if exists:
                continue
            session.add(row)
            added += 1
        return added

    backend = os.environ.get("CRYO_ANN_BACKEND", "cninfo").strip().lower()
    if backend == "eastmoney":
        return _crawl_symbol_eastmoney(session, symbol, company_name)
    return _crawl_symbol_cninfo(session, symbol, company_name)


def main(symbols: Iterable[tuple[str, str]] | None = None) -> None:
    from apps.common.no_mock_policy import reject_business_mock

    reject_business_mock("CRYO_MOCK", context="crawl_announcements")
    if symbols is None:
        symbols = get_all_a_stock_symbols()
    symbols = list(symbols)
    max_n = os.environ.get("CRYO_MAX_SYMBOLS")
    if max_n and max_n.isdigit():
        symbols = symbols[: int(max_n)]

    if os.environ.get("CRYO_ANN_ENRICH_EMPTY", "").strip() == "1":
        with session_scope() as session:
            total = 0
            for sym, name in tqdm(symbols, desc="补全公告正文(巨潮PDF)"):
                total += enrich_symbol_announcement_bodies(session, sym, name)
                session.commit()
            logger.info("补全完成，共更新 %d 条（无匹配/PDF失败则跳过）", total)
        return

    with session_scope() as session:
        for sym, name in tqdm(symbols, desc="采集公告"):
            crawl_symbol(session, sym, name)
            session.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
