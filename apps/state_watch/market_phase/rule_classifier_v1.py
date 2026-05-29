"""启动期纯规则分类器 · 判定顺序 exhaustion → realization → expectation → concept.

[Ref: 03_/.../step_09 §3.5.1]
"""
from __future__ import annotations

from typing import Any

from apps.state_watch.market_phase.rules_config import load_rules
from apps.state_watch.market_phase.schemas import ClassificationResult, MarketPhase, PhaseSignals


def _t(cfg: dict[str, Any], *keys: str, default: float) -> float:
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    try:
        return float(cur)
    except (TypeError, ValueError):
        return default


def classify(signals: PhaseSignals, *, rules: dict[str, Any] | None = None) -> ClassificationResult:
    rules = rules or load_rules()
    th = rules.get("thresholds") or {}
    conf = rules.get("confidence") or {}
    version = str(rules.get("classifier_version") or "rule_v1")
    tags: list[str] = []
    missing = 0

    def _ok(val: float | None) -> bool:
        return val is not None

    # --- exhaustion (优先) ---
    ex = th.get("exhaustion") or {}
    if not signals.insufficient_price:
        c60 = signals.pct_chg_60d
        vr = signals.volume_ratio_5d or 1.0
        c5 = signals.pct_chg_5d
        if (
            _ok(c60)
            and c60 > _t(th, "exhaustion", "pct_chg_60d_min", default=0.80)
            and vr > _t(th, "exhaustion", "volume_ratio_5d_min", default=2.5)
            and _ok(c5)
            and c5 < _t(th, "exhaustion", "pct_chg_5d_max", default=0.0)
        ):
            tags.append("exhaustion_vol_price_divergence")
            return _result(signals, MarketPhase.EXHAUSTION, conf, tags, version, missing)

        c3 = signals.pct_chg_3d
        media_min = int(_t(th, "exhaustion", "media_news_count_7d_min", default=30))
        if (
            signals.media_news_count_7d > media_min
            and _ok(c3)
            and c3 < _t(th, "exhaustion", "pct_chg_3d_max", default=0.0)
            and signals.price_below_ma10
        ):
            tags.append("exhaustion_media_climax")
            return _result(signals, MarketPhase.EXHAUSTION, conf, tags, version, missing)

    # --- realization ---
    if (
        signals.has_q_report_released
        or signals.has_pre_announce_released
        or signals.has_major_contract
    ):
        tags.append("realization_announcement_window")
        return _result(signals, MarketPhase.REALIZATION, conf, tags, version, missing)

    # --- expectation ---
    exp = th.get("expectation") or {}
    phys_ok = signals.phys_probe_alerts_active >= 1
    c30 = signals.pct_chg_30d
    vr = signals.volume_ratio_5d or 0.0
    no_ann = signals.no_announcement_positive
    if no_ann and vr > _t(th, "expectation", "volume_ratio_5d_min", default=1.5):
        if phys_ok:
            tags.append("expectation_phys_probe")
            if "phys_probe_absent" in signals.tags:
                missing += 1
            return _result(
                signals,
                MarketPhase.EXPECTATION,
                conf,
                tags,
                version,
                missing,
                cap_conf=0.65 if "phys_probe_absent" in signals.tags else None,
            )
        if _ok(c30) and c30 > _t(th, "expectation", "pct_chg_30d_min", default=0.30):
            tags.append("expectation_momentum_30d")
            return _result(signals, MarketPhase.EXPECTATION, conf, tags, version, missing)

    # --- concept (默认) ---
    if signals.insufficient_price:
        tags.append("insufficient_input")
        return _result(
            signals,
            MarketPhase.CONCEPT,
            conf,
            tags,
            version,
            missing,
            force_conf=float(conf.get("degraded", 0.45)),
        )
    tags.append("concept_default")
    return _result(signals, MarketPhase.CONCEPT, conf, tags, version, missing)


def _result(
    signals: PhaseSignals,
    phase: MarketPhase,
    conf: dict[str, Any],
    tags: list[str],
    version: str,
    missing: int,
    *,
    cap_conf: float | None = None,
    force_conf: float | None = None,
) -> ClassificationResult:
    if force_conf is not None:
        confidence = force_conf
    elif missing >= 2:
        confidence = float(conf.get("degraded", 0.45))
    elif missing == 1:
        confidence = float(conf.get("partial", 0.65))
    else:
        confidence = float(conf.get("full", 0.85))
    if cap_conf is not None:
        confidence = min(confidence, cap_conf)
    return ClassificationResult(
        symbol=signals.symbol,
        market_phase=phase,
        confidence=confidence,
        reasoning_tags=tags,
        rule_signals=signals.to_dict(),
        classifier_version=version,
    )
