"""SLI 聚合器测试.

[Ref: 03_/03_维度三_持仓监控/stages/stage_1_启动期/steps/step_04_探针调度器与SLI聚合.md]
"""
from __future__ import annotations

from apps.state_watch.health.sli_aggregator import SLIDef, _score_one, aggregate


class TestScoreOne:
    def test_pass_full(self):
        sli = SLIDef("a", "x", 10.0, ">", current_value=15.0)
        d = _score_one(sli)
        assert d.score == 100

    def test_soft_pass_60(self):
        sli = SLIDef("a", "x", 10.0, ">", current_value=9.5)
        d = _score_one(sli)
        assert d.score == 60

    def test_weak_30(self):
        sli = SLIDef("a", "x", 10.0, ">", current_value=8.0)
        d = _score_one(sli)
        assert d.score == 30

    def test_fail_0(self):
        sli = SLIDef("a", "x", 10.0, ">", current_value=5.0)
        d = _score_one(sli)
        assert d.score == 0

    def test_no_data_50(self):
        sli = SLIDef("a", "x", 10.0, ">", current_value=None)
        d = _score_one(sli)
        assert d.score == 50

    def test_lt_operator(self):
        sli = SLIDef("a", "x", 60.0, "<", current_value=50.0)
        d = _score_one(sli)
        assert d.score == 100

    def test_eq_operator(self):
        sli = SLIDef("a", "x", 0.0, "==", current_value=0.0)
        d = _score_one(sli)
        assert d.score == 100


class TestAggregate:
    def test_empty_returns_100(self):
        s, _ = aggregate([])
        assert s == 100

    def test_uniform_weight_all_pass(self):
        slis = [
            SLIDef("a", "x", 10, ">", weight=1.0, current_value=15),
            SLIDef("b", "y", 10, ">", weight=1.0, current_value=15),
        ]
        s, d = aggregate(slis)
        assert s == 100
        assert len(d) == 2

    def test_weighted_score(self):
        slis = [
            SLIDef("a", "x", 10, ">", weight=1.0, current_value=15),
            SLIDef("b", "y", 10, ">", weight=3.0, current_value=5),
        ]
        s, _ = aggregate(slis)
        assert s == 25.0

    def test_zero_weight_falls_back_100(self):
        slis = [SLIDef("a", "x", 10, ">", weight=0, current_value=5)]
        s, _ = aggregate(slis)
        assert s == 100

    def test_mixed_no_data_and_pass(self):
        slis = [
            SLIDef("a", "x", 10, ">", weight=1, current_value=15),
            SLIDef("b", "y", 10, ">", weight=1, current_value=None),
        ]
        s, _ = aggregate(slis)
        assert s == 75.0
