"""财报附注中关联方片段抽取（pdfplumber 文本；OCR 为可选增强）。

可先自巨潮拉取**年报 PDF** 再抽附注关联方行：

  CRYO_NOTES_FETCH_PDF=1 — 按 ``get_all_a_stock_symbols`` + ``env_crawl_years`` 下载年报至本目录树
  CRYO_NOTES_PDF_MAX_BYTES — 单文件上限（默认 80MB）
  仍遵守 ``CRYO_SYMBOL_LIST`` / ``CRYO_MAX_SYMBOLS`` / ``CRYO_CRAWL_CONFIG``（需 ``bootstrap_crawl_env``）

未安装 paddleocr 时仅使用 extract_text；失败写入 failed_ocr_pages。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from apps.cryo_guard.crawl_env_bootstrap import bootstrap_crawl_env

bootstrap_crawl_env(_REPO_ROOT)

import pdfplumber
from tqdm import tqdm

from apps.cryo_guard.db.models import FailedOcrPage, RelatedPartyRaw
from apps.cryo_guard.db.sync_session import session_scope

logger = logging.getLogger(__name__)

RELATED_PARTY_KEYWORDS = ("关联方", "关联交易", "重大关联交易", "其他关联方")
AMOUNT_PATTERN = re.compile(r"([\d,]+(?:\.\d+)?)\s*(万元|亿元|元)?")
RELATIONSHIP_HINTS = ("控股股东", "实际控制人", "母公司", "子公司", "联营", "合营", "董监高", "关联自然人")
TRANS_HINTS = ("销售", "采购", "借款", "担保", "租赁", "劳务", "资金拆借", "代付")


def _annual_title_ok(title: str) -> bool:
    if "年度报告" not in title:
        return False
    bad = (
        "摘要",
        "英文",
        "英文版",
        "半年度",
        "一季度",
        "三季度",
        "第一季度",
        "第三季度",
        "半年报告",
    )
    return all(b not in title for b in bad)


def fetch_annual_pdfs_from_cninfo(pdf_root: Path) -> int:
    """自巨潮「年报」类目拉取 annual PDF，保存为 ``{pdf_root}/{code}_{year}/report.pdf``。"""
    from apps.cryo_guard.cninfo_client import (  # noqa: PLC0415
        download_pdf_bytes,
        iter_cninfo_announcements,
        static_file_url,
    )
    from training.data.scripts.crawl_financial_reports import (  # noqa: PLC0415
        env_crawl_years,
        env_throttle_sec,
        get_all_a_stock_symbols,
    )

    max_b = int(os.environ.get("CRYO_NOTES_PDF_MAX_BYTES", str(80 * 1024 * 1024)))
    throttle = env_throttle_sec()
    written = 0
    symbols = list(get_all_a_stock_symbols())
    max_n = os.environ.get("CRYO_MAX_SYMBOLS")
    if max_n and max_n.isdigit():
        symbols = symbols[: int(max_n)]
    years = env_crawl_years()

    for sym, _short in symbols:
        for year in years:
            start_s = f"{year}0101"
            end_s = f"{year}1231"
            candidates: list[tuple[int, str, dict]] = []
            try:
                for item in iter_cninfo_announcements(
                    sym,
                    start_s,
                    end_s,
                    category="年报",
                    page_size=30,
                    max_pages=int(os.environ.get("CRYO_NOTES_QUERY_MAX_PAGES", "10")),
                    throttle_sec=throttle,
                ):
                    title = str(item.get("announcementTitle") or "")
                    if not _annual_title_ok(title):
                        continue
                    adj_type = str(item.get("adjunctType") or "").upper()
                    adj_url = str(item.get("adjunctUrl") or "")
                    if adj_type and "PDF" not in adj_type:
                        continue
                    if not adj_url.upper().endswith(".PDF"):
                        continue
                    try:
                        sz = int(item.get("adjunctSize") or 0)
                    except (TypeError, ValueError):
                        sz = 0
                    candidates.append((sz, title, item))
            except Exception as exc:
                logger.warning("年报 PDF 检索失败 %s %s: %s", sym, year, exc)
                continue

            if not candidates:
                logger.warning("未找到 %s %s 的年报 PDF（可调大 CRYO_NOTES_QUERY_MAX_PAGES）", sym, year)
                continue

            candidates.sort(key=lambda x: -x[0])
            _sz, _title, item = candidates[0]
            url = static_file_url(item.get("adjunctUrl"))
            if not url:
                continue
            dest_dir = pdf_root / f"{sym}_{year}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "report.pdf"
            if dest.is_file() and dest.stat().st_size > 1024:
                logger.info("已存在跳过 %s", dest)
                written += 1
                continue
            try:
                data = download_pdf_bytes(url, max_bytes=max_b)
                dest.write_bytes(data)
                logger.info("已下载 %s %s -> %s (%s KB)", sym, year, dest, len(data) // 1024)
                written += 1
            except Exception as exc:
                logger.warning("下载失败 %s %s: %s", sym, year, exc)
    return written


def _normalize_amount(text: str) -> float | None:
    m = AMOUNT_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").strip()
    if not raw:
        return None
    num = float(raw)
    unit = m.group(2)
    if unit == "万元":
        num *= 10_000
    elif unit == "亿元":
        num *= 100_000_000
    return num


def _detect_relationship(text: str) -> str | None:
    for hint in RELATIONSHIP_HINTS:
        if hint in text:
            return hint
    return None


def _detect_trans_type(text: str) -> str | None:
    for hint in TRANS_HINTS:
        if hint in text:
            return hint
    return None


def _iter_related_party_pages(pdf_path: Path) -> Iterator[tuple[int, str]]:
    with pdfplumber.open(pdf_path) as pdf:
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if any(kw in text for kw in RELATED_PARTY_KEYWORDS):
                yield idx, text


def process_pdf(pdf_path: Path, symbol: str, company_name: str, report_year: int) -> int:
    written = 0
    ocr = None
    try:
        from paddleocr import PaddleOCR  # noqa: PLC0415

        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    except Exception:
        logger.info("paddleocr 不可用，跳过 OCR 增强")

    with session_scope() as session:
        for page_no, text in _iter_related_party_pages(pdf_path):
            try:
                if len(text.strip()) < 80 and ocr is not None:
                    with pdfplumber.open(pdf_path) as pdf:
                        page = pdf.pages[page_no]
                        img = page.to_image(resolution=200).original
                        result = ocr.ocr(img, cls=True)
                        lines = [line[1][0] for line in (result[0] or [])]
                        text = "\n".join(lines)
            except Exception as exc:
                session.add(
                    FailedOcrPage(
                        symbol=symbol,
                        report_year=report_year,
                        page_no=page_no,
                        pdf_path=str(pdf_path),
                        error_reason=str(exc)[:240],
                    )
                )
                continue
            for line in text.splitlines():
                line = line.strip()
                if len(line) < 8:
                    continue
                session.add(
                    RelatedPartyRaw(
                        symbol=symbol,
                        company_name=company_name,
                        report_year=report_year,
                        party_name=line[:250],
                        relationship=_detect_relationship(line),
                        transaction_type=_detect_trans_type(line),
                        amount=_normalize_amount(line),
                        percentage_of_total=None,
                        pricing_method=None,
                        raw_text=line,
                        pdf_page_no=page_no,
                    )
                )
                written += 1
    return written


def main(pdf_root: str = "data/raw/financial_notes") -> None:
    root = Path(pdf_root)
    if not root.is_absolute():
        root = (_REPO_ROOT / root).resolve()

    if os.environ.get("CRYO_NOTES_FETCH_PDF", "").strip() == "1":
        root.mkdir(parents=True, exist_ok=True)
        n = fetch_annual_pdfs_from_cninfo(root)
        logger.info("巨潮年报 PDF 就绪 %d 个文件（含已存在跳过）", n)

    if not root.exists():
        logger.warning("目录不存在 %s，跳过 OCR", root)
        return

    try:
        from training.data.scripts.crawl_financial_reports import get_all_a_stock_symbols  # noqa: PLC0415

        name_by = {a: b for a, b in get_all_a_stock_symbols()}
    except Exception:
        name_by = {}

    pdfs = list(root.rglob("*.pdf"))
    for p in tqdm(pdfs, desc="OCR 附注"):
        parts = p.parts
        token = parts[-2] if len(parts) >= 2 else "UNKNOWN_2023"
        sym = token.split("_", 1)[0] if "_" in token else "000000"
        year_s = token.split("_", 1)[1] if "_" in token else "2023"
        try:
            y = int(year_s)
        except ValueError:
            y = 2023
        co = str(name_by.get(sym, sym))[:64]
        process_pdf(Path(p), sym, co, y)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
