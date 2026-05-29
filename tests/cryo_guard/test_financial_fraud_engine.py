"""D1 step_04 财务测谎引擎骨架测试。

覆盖：N1 字段抽取 / N2 特征计算（6 类公式）/ N3 时序对比 / N4 同行对比 / N5 降级模式 / 整引擎无 DB 骨架

[Ref: 03_/01_维度一/stages/stage_1_启动期/steps/step_04_财务测谎引擎LoRA §3.5.2]
"""
import pytest

from apps.cryo_guard.engines.financial_fraud.engine import FinancialFraudEngine
from apps.cryo_guard.engines.financial_fraud.feature_calculator import compute_features
from apps.cryo_guard.engines.financial_fraud.field_extractor import extract_fields, REQUIRED_FIELDS
from apps.cryo_guard.engines.financial_fraud.llm_interrogator import interrogate
from apps.cryo_guard.engines.financial_fraud.peer_comparator import compare_with_peers
from apps.cryo_guard.engines.financial_fraud.schemas import FraudLabel, RiskLevel
from apps.cryo_guard.engines.financial_fraud.time_series_comparator import compare_time_series


# ---------------------------------------------------------------------------
# N1 field_extractor
# ---------------------------------------------------------------------------

class TestFieldExtractor:
    def test_no_db_returns_all_missing(self):
        result = extract_fields("300750", "2023-12-31", db_session=None)
        assert result["symbol"] == "300750"
        assert result["report_period"] == "2023-12-31"
        assert len(result["missing_fields"]) == len(REQUIRED_FIELDS)
        for f in REQUIRED_FIELDS:
            assert result[f] is None

    def test_all_required_fields_present_in_keys(self):
        result = extract_fields("300750", "2023-12-31")
        for f in REQUIRED_FIELDS:
            assert f in result, f"字段 {f} 不在 result 中"


# ---------------------------------------------------------------------------
# N2 feature_calculator
# ---------------------------------------------------------------------------

class TestFeatureCalculator:
    def _base_fields(self, **overrides):
        fields = {
            "cash": 5.0, "total_assets": 10.0, "total_debt": 4.0,
            "accounts_receivable": 2.0, "inventory": 1.5,
            "rd_capitalized": 0.3, "gross_margin": 0.25,
            "operating_cash_flow": 1.0, "net_profit": 3.0,
            "revenue": 8.0, "industry": "electronics",
            "missing_fields": [],
        }
        fields.update(overrides)
        return fields

    def test_returns_six_categories(self):
        features = compute_features(self._base_fields())
        assert len(features) == 6
        expected_keys = {"double_high", "cash_flow_divergence", "ar_abnormal",
                         "inventory_bloat", "rd_cap_surge", "gross_margin_anomaly"}
        assert set(features.keys()) == expected_keys

    def test_double_high_triggered_when_both_ratios_exceed(self):
        # cash/assets=0.5 > 0.3, debt/assets=0.4 > 0.3 → triggered
        fields = self._base_fields(cash=5.0, total_assets=10.0, total_debt=4.0)
        features = compute_features(fields)
        assert features["double_high"]["triggered"] is True

    def test_double_high_not_triggered_when_debt_low(self):
        # debt/assets=0.1 < 0.3 → not triggered
        fields = self._base_fields(total_debt=1.0, total_assets=10.0)
        features = compute_features(fields)
        assert features["double_high"]["triggered"] is False

    def test_cash_flow_divergence_triggered_when_ocf_low(self):
        # OCF=0.5 / NetProfit=3.0 = 0.167 < 0.5 → triggered
        fields = self._base_fields(operating_cash_flow=0.5, net_profit=3.0)
        features = compute_features(fields)
        assert features["cash_flow_divergence"]["triggered"] is True

    def test_cash_flow_divergence_not_triggered_when_ocf_high(self):
        # OCF=2.5 / NetProfit=3.0 = 0.83 > 0.5 → not triggered
        fields = self._base_fields(operating_cash_flow=2.5, net_profit=3.0)
        features = compute_features(fields)
        assert features["cash_flow_divergence"]["triggered"] is False

    def test_ar_abnormal_needs_prev_fields(self):
        fields = self._base_fields()
        features = compute_features(fields)
        assert features["ar_abnormal"]["triggered"] is False  # 无上期数据

    def test_ar_abnormal_triggered_with_prev_fields(self):
        curr = self._base_fields(accounts_receivable=4.0, revenue=8.0)
        prev = self._base_fields(accounts_receivable=1.0, revenue=7.5)
        # AR_yoy = (4-1)/1 = 3.0; revenue_yoy = (8-7.5)/7.5 = 0.067; 3.0 > 0.067*1.5 → triggered
        features = compute_features(curr, prev_fields=prev)
        assert features["ar_abnormal"]["triggered"] is True

    def test_inventory_bloat_triggered_with_industry_median(self):
        # inv_ratio = 1.5/8 = 0.1875; median=0.05; 0.1875 > 0.05*1.5=0.075 → triggered
        fields = self._base_fields(inventory=1.5, revenue=8.0)
        features = compute_features(fields, industry_median_inventory_ratio=0.05)
        assert features["inventory_bloat"]["triggered"] is True

    def test_rd_cap_surge_triggered_with_prev(self):
        curr = self._base_fields(rd_capitalized=1.0)
        prev = self._base_fields(rd_capitalized=0.5)
        # (1.0-0.5)/0.5 = 1.0 > 0.3 → triggered
        features = compute_features(curr, prev_fields=prev)
        assert features["rd_cap_surge"]["triggered"] is True

    def test_gross_margin_anomaly_triggered(self):
        curr = self._base_fields(gross_margin=0.15)
        prev = self._base_fields(gross_margin=0.25)
        # 0.15-0.25 = -0.10 < -0.05 → triggered
        features = compute_features(curr, prev_fields=prev)
        assert features["gross_margin_anomaly"]["triggered"] is True

    def test_all_normal_scenario(self):
        curr = self._base_fields(
            cash=1.0, total_assets=10.0, total_debt=2.0,
            operating_cash_flow=2.0, net_profit=2.5,
            gross_margin=0.26,
        )
        prev = self._base_fields(gross_margin=0.25, rd_capitalized=0.29)
        features = compute_features(curr, prev_fields=prev)
        assert features["double_high"]["triggered"] is False
        assert features["cash_flow_divergence"]["triggered"] is False
        assert features["gross_margin_anomaly"]["triggered"] is False


# ---------------------------------------------------------------------------
# N3 time_series_comparator
# ---------------------------------------------------------------------------

class TestTimeSeriesComparator:
    def test_no_db_returns_insufficient(self):
        result = compare_time_series("300750", "2023-12-31", db_session=None)
        assert result["insufficient"] is True
        assert result["symbol"] == "300750"
        assert result["periods"] == []


# ---------------------------------------------------------------------------
# N4 peer_comparator
# ---------------------------------------------------------------------------

class TestPeerComparator:
    def test_no_db_returns_fallback(self):
        result = compare_with_peers("300750", "电子", {}, db_session=None)
        assert result["peer_fallback"] == "no_db"
        assert result["peer_count"] == 0


# ---------------------------------------------------------------------------
# N5 llm_interrogator（降级模式）
# ---------------------------------------------------------------------------

class TestLLMInterrogator:
    def test_no_vllm_returns_degraded(self):
        out = interrogate("300750", "2023-12-31", {}, {}, {}, vllm_url=None)
        assert out.lora_loaded is False
        assert out.confidence == 0.5
        assert out.label == FraudLabel.NORMAL

    def test_no_vllm_reason_not_empty(self):
        out = interrogate("300750", "2023-12-31", {}, {}, {}, vllm_url=None)
        assert len(out.reason_zh) > 5


# ---------------------------------------------------------------------------
# 整引擎（无 DB / 无 vLLM → 全降级）
# ---------------------------------------------------------------------------

class TestFinancialFraudEngine:
    def test_engine_runs_without_db(self):
        engine = FinancialFraudEngine(db_session=None, vllm_url=None)
        report = engine.analyze("300750", "2023-12-31")
        assert report.symbol == "300750"
        assert report.report_period == "2023-12-31"
        assert report.label in (FraudLabel.FRAUD, FraudLabel.NORMAL)
        assert 0.0 <= report.confidence <= 1.0
        assert report.lora_loaded is False  # vLLM 未连接 → 降级

    def test_engine_missing_fields_when_no_db(self):
        engine = FinancialFraudEngine(db_session=None, vllm_url=None)
        report = engine.analyze("600312", "2023-12-31")
        assert len(report.missing_fields) > 0

    def test_engine_history_insufficient_when_no_db(self):
        engine = FinancialFraudEngine(db_session=None, vllm_url=None)
        report = engine.analyze("002837", "2023-06-30")
        assert report.history_insufficient is True

    def test_engine_peer_fallback_when_no_db(self):
        engine = FinancialFraudEngine(db_session=None, vllm_url=None)
        report = engine.analyze("300499", "2023-12-31")
        assert report.peer_fallback == "no_db"

    def test_engine_report_schema_valid(self):
        from apps.cryo_guard.engines.financial_fraud.schemas import FinancialFraudReport
        engine = FinancialFraudEngine(db_session=None, vllm_url=None)
        report = engine.analyze("300750", "2023-12-31")
        # Pydantic 验证（能转 dict 就说明 schema 合法）
        d = report.model_dump()
        assert "symbol" in d
        assert "label" in d
        assert "confidence" in d
