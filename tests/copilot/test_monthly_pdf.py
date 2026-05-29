"""月报 PDF 测试（含中文 + WeasyPrint 集成）。

[Ref: 03_/00_维度零/stages/stage_1_启动期/steps/step_08]
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from apps.copilot.db.models import ThesisCard
from apps.copilot.services.ledger.models import AttributionRecord
from apps.copilot.services.reports.monthly import MonthlyReportGenerator
from apps.copilot.services.reports.pdf import WeasyPDFRenderer


class _StubLedger:
    async def snapshot_scs(self, u, d):
        _ = u, d
        return 65.0

    async def compute_avoided_loss(self, u, s, e):
        _ = u, s, e
        return 100.0

    async def compute_earned(self, u, s, e):
        _ = u, s, e
        return 50.0


@pytest.fixture
async def seeded_month(db_session):
    today = date.today().replace(day=1)
    ts = datetime.combine(today, time.min, tzinfo=timezone.utc)
    for i, (oct_, pnl) in enumerate(
        [("A", 5000), ("A", 3000), ("B", -200), ("C", 1500), ("D", -800), ("F", 200)]
    ):
        db_session.add(
            AttributionRecord(
                response_id=i,
                user_id="u1",
                symbol="600519",
                octant=oct_,
                system_advice="buy" if oct_ in {"A", "B"} else "sell",
                user_action="buy" if oct_ in {"A", "B"} else "sell",
                result_pnl=pnl,
                attribution_text=f"测试-{oct_}",
                created_at=ts,
            )
        )
    db_session.add(
        ThesisCard(
            thesis_id="t1",
            symbol="600519",
            name="贵州茅台",
            thesis_summary="高端白酒龙头",
            evidence_chain=["a", "b", "c"],
            risks=["x"],
            valuation_anchor={"target": 2100},
            action="buy",
            proposed_at=ts.replace(tzinfo=None),
        )
    )
    await db_session.commit()
    yield db_session


@pytest.mark.asyncio
async def test_monthly_aggregates_octants(seeded_month):
    gen = MonthlyReportGenerator(seeded_month, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    assert ctx.payload["octants"]["total"] == 6
    assert ctx.payload["octants"]["counts"]["A"]["count"] == 2
    assert ctx.payload["octants"]["counts"]["A"]["pnl"] == pytest.approx(8000.0)
    assert ctx.payload["top_success"][0]["pnl"] == pytest.approx(5000.0)
    assert ctx.payload["top_failure"][0]["pnl"] == pytest.approx(-800.0)


def _skip_if_weasyprint_unavailable() -> None:
    try:
        from weasyprint import HTML

        HTML(string="<p>.</p>").write_pdf()
    except OSError:
        pytest.skip("WeasyPrint 缺少系统库（见 L3 step_08 §3.2；CI/Docker 镜像可用）")


@pytest.mark.asyncio
async def test_monthly_pdf_render(tmp_path, seeded_month):
    _skip_if_weasyprint_unavailable()
    gen = MonthlyReportGenerator(seeded_month, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    out = tmp_path / "monthly_test.pdf"
    WeasyPDFRenderer().render(ctx, out)
    assert out.exists()
    content = out.read_bytes()
    assert content.startswith(b"%PDF"), "应为合法 PDF"
    assert len(content) > 5000, "PDF 体积过小，可能缺章节"


@pytest.mark.asyncio
async def test_monthly_pdf_contains_chinese_glyph(tmp_path, seeded_month):
    pytest.importorskip("pdfminer.high_level", reason="optional: pdfminer.six")
    _skip_if_weasyprint_unavailable()
    from pdfminer.high_level import extract_text

    gen = MonthlyReportGenerator(seeded_month, _StubLedger())
    ctx = await gen.aggregate("u1", date.today())
    out = tmp_path / "monthly_zh.pdf"
    WeasyPDFRenderer().render(ctx, out)
    text = extract_text(str(out))
    assert "月度报告" in text
    assert "象限" in text
