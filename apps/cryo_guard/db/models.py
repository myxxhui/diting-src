"""SQLAlchemy 模型（step_02 数据采集 + step_01 蒸馏/审计表）。

[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_01]
[Ref: 03_/01_维度一_极寒防御/stages/stage_1_启动期/steps/step_02]
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.cryo_guard.db.session import Base


class FinancialReport(Base):
    """全 A 股财务报表三表聚合行（按报告期 + 报告类型）。"""

    __tablename__ = "financial_reports"
    __table_args__ = (
        UniqueConstraint("symbol", "report_date", "report_type", name="uq_fr_sym_date_type"),
        Index("ix_fr_symbol_date", "symbol", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_balance_sheet: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_income_statement: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_cash_flow: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    cash_and_equivalents: Mapped[Optional[float]] = mapped_column(Float)
    accounts_receivable: Mapped[Optional[float]] = mapped_column(Float)
    inventory: Mapped[Optional[float]] = mapped_column(Float)
    total_assets: Mapped[Optional[float]] = mapped_column(Float)
    short_term_debt: Mapped[Optional[float]] = mapped_column(Float)
    long_term_debt: Mapped[Optional[float]] = mapped_column(Float)
    total_liabilities: Mapped[Optional[float]] = mapped_column(Float)
    revenue: Mapped[Optional[float]] = mapped_column(Float)
    cost_of_revenue: Mapped[Optional[float]] = mapped_column(Float)
    gross_profit: Mapped[Optional[float]] = mapped_column(Float)
    operating_profit: Mapped[Optional[float]] = mapped_column(Float)
    net_profit: Mapped[Optional[float]] = mapped_column(Float)
    rd_expense: Mapped[Optional[float]] = mapped_column(Float)
    rd_capitalized: Mapped[Optional[float]] = mapped_column(Float)
    operating_cash_flow: Mapped[Optional[float]] = mapped_column(Float)
    investing_cash_flow: Mapped[Optional[float]] = mapped_column(Float)
    financing_cash_flow: Mapped[Optional[float]] = mapped_column(Float)
    gross_margin: Mapped[Optional[float]] = mapped_column(Float)
    net_margin: Mapped[Optional[float]] = mapped_column(Float)
    roe: Mapped[Optional[float]] = mapped_column(Float)
    receivable_turnover: Mapped[Optional[float]] = mapped_column(Float)
    inventory_turnover: Mapped[Optional[float]] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="akshare")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Announcement(Base):
    """大股东 / 公司相关公告。"""

    __tablename__ = "announcements"
    __table_args__ = (Index("ix_ann_symbol_type_date", "symbol", "ann_type", "ann_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str] = mapped_column(String(64), nullable=False)
    ann_type: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    ann_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(String(512))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="cninfo")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RelatedPartyRaw(Base):
    """关联交易原始抽取（财报附注 OCR 等）。"""

    __tablename__ = "related_party_raw"
    __table_args__ = (Index("ix_rpr_symbol_year", "symbol", "report_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str] = mapped_column(String(64), nullable=False)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False)
    party_name: Mapped[str] = mapped_column(String(256), nullable=False)
    relationship: Mapped[Optional[str]] = mapped_column(String(64))
    transaction_type: Mapped[Optional[str]] = mapped_column(String(32))
    amount: Mapped[Optional[float]] = mapped_column(Float)
    percentage_of_total: Mapped[Optional[float]] = mapped_column(Float)
    pricing_method: Mapped[Optional[str]] = mapped_column(String(64))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_page_no: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FailedOcrPage(Base):
    """OCR 失败页记录。"""

    __tablename__ = "failed_ocr_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(512), nullable=False)
    error_reason: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TeacherDistill(Base):
    """Teacher 蒸馏（含人工 Verified）。step_03 扩展字段。

    [Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_03_Teacher蒸馏.md]
    """

    __tablename__ = "teacher_distill"
    __table_args__ = (
        UniqueConstraint(
            "engine_name",
            "symbol",
            "report_period",
            "case_hash",
            name="uq_td_eng_sym_rp_hash",
        ),
        Index("ix_td_engine_verified", "engine_name", "verified"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine_name: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    report_period: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    case_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    teacher_model: Mapped[str] = mapped_column(String(64), nullable=False, default="mock")
    teacher_latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    teacher_tokens_in: Mapped[Optional[int]] = mapped_column(Integer)
    teacher_tokens_out: Mapped[Optional[int]] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verifier: Mapped[Optional[str]] = mapped_column(String(32))
    verifier_decision: Mapped[Optional[str]] = mapped_column(String(16))
    verifier_notes: Mapped[Optional[str]] = mapped_column(Text)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class HoldoutCase(Base):
    __tablename__ = "holdout_cases"
    case_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    company_name: Mapped[str] = mapped_column(String(128))
    fraud_type: Mapped[str] = mapped_column(String(64))
    target_engine: Mapped[str] = mapped_column(String(32), index=True)
    fraud_start_year: Mapped[int] = mapped_column(Integer)
    exposure_date: Mapped[str] = mapped_column(String(10))
    ground_truth_decision: Mapped[str] = mapped_column(String(16))
    ground_truth_score: Mapped[float] = mapped_column(Float)
    evidence_json: Mapped[list] = mapped_column("evidence", JSON, default=list)
    raw_json: Mapped[dict] = mapped_column("raw", JSON, default=dict)
    sha256: Mapped[str] = mapped_column(String(64))
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    annotator: Mapped[Optional[str]] = mapped_column(String(64))
    annotation_date: Mapped[Optional[str]] = mapped_column(String(10))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "cryo_guard_audit_log"
    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(128))
    decision_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    final_decision: Mapped[str] = mapped_column(String(16))
    aggregation_reason: Mapped[str] = mapped_column(Text)
    engine_scores_json: Mapped[dict] = mapped_column("engine_scores", JSON)
    evidence_json: Mapped[list] = mapped_column("evidence", JSON, default=list)
    request_payload_json: Mapped[dict] = mapped_column("request_payload", JSON, default=dict)
    integrity_hash: Mapped[str] = mapped_column(String(64))
