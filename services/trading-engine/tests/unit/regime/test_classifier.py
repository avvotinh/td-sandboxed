"""Unit tests for the rule-based regime classifier (Epic 11 story 11.3).

The classifier is a pure function of ``RegimeFeatures`` plus a
``RegimeThresholds`` value object: same inputs always produce the same
``RegimeState``. These tests pin the priority order — warmup gate first,
then HIGH_VOLATILITY (kill-switch), then TRENDING (with slope/DI
agreement), then RANGING, with UNKNOWN as the residual.
"""

from __future__ import annotations

import pytest

from src.config.firm_profile import RegimeThresholds
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thresholds(**overrides: float) -> RegimeThresholds:
    base: dict[str, float] = dict(
        adx_trend_min=25.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.30,
        bb_width_high_pct=0.80,
        realized_vol_high=0.025,
        ema_slope_trend_threshold=0.0005,
    )
    base.update(overrides)
    return RegimeThresholds(**base)


def _features(**overrides: object) -> RegimeFeatures:
    base: dict[str, object] = dict(
        adx=15.0,
        plus_di=20.0,
        minus_di=20.0,
        bb_width_pct=0.50,
        realized_vol=0.010,
        ema_slope=0.0,
        is_warmed_up=True,
    )
    base.update(overrides)
    return RegimeFeatures(**base)  # type: ignore[arg-type]


@pytest.fixture
def classifier() -> RuleBasedRegimeClassifier:
    return RuleBasedRegimeClassifier(_thresholds())


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestClassifierConstruction:
    def test_holds_thresholds(self):
        t = _thresholds()
        c = RuleBasedRegimeClassifier(t)
        assert c.thresholds is t

    def test_thresholds_required(self):
        with pytest.raises(TypeError):
            RuleBasedRegimeClassifier()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Warmup gate
# ---------------------------------------------------------------------------


class TestWarmupGate:
    def test_unknown_when_not_warmed_up(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # Even features that would trigger HIGH_VOLATILITY must yield UNKNOWN
        # before the extractor reports warmed-up — protects the kill-switch
        # from acting on undefined indicator state.
        f = _features(
            is_warmed_up=False, bb_width_pct=0.99, realized_vol=0.10
        )
        assert classifier.decide(f) is RegimeState.UNKNOWN


# ---------------------------------------------------------------------------
# HIGH_VOLATILITY (priority 1 — kill-switch)
# ---------------------------------------------------------------------------


class TestHighVolatilityPriority:
    def test_bb_width_at_high_threshold_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # >= boundary: equality must trigger so operators tuning the YAML
        # observe the threshold acting at the documented value.
        f = _features(bb_width_pct=0.80)
        assert classifier.decide(f) is RegimeState.HIGH_VOLATILITY

    def test_bb_width_above_high_threshold_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(bb_width_pct=0.95)
        assert classifier.decide(f) is RegimeState.HIGH_VOLATILITY

    def test_realized_vol_at_high_threshold_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(realized_vol=0.025)
        assert classifier.decide(f) is RegimeState.HIGH_VOLATILITY

    def test_high_vol_overrides_strong_trend(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # Strong trend signature (high ADX + slope + DI agreement) must be
        # masked when realized vol blows out — kill-switch wins.
        f = _features(
            adx=45.0,
            plus_di=40.0,
            minus_di=10.0,
            ema_slope=0.005,
            bb_width_pct=0.50,
            realized_vol=0.030,
        )
        assert classifier.decide(f) is RegimeState.HIGH_VOLATILITY


# ---------------------------------------------------------------------------
# TRENDING (priority 3 — slope and DI must agree)
# ---------------------------------------------------------------------------


class TestTrendingUp:
    def test_classic_uptrend(self, classifier: RuleBasedRegimeClassifier):
        f = _features(
            adx=30.0, plus_di=30.0, minus_di=15.0, ema_slope=0.001
        )
        assert classifier.decide(f) is RegimeState.TRENDING_UP

    def test_adx_at_trend_min_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # >= boundary on ADX.
        f = _features(
            adx=25.0, plus_di=30.0, minus_di=15.0, ema_slope=0.001
        )
        assert classifier.decide(f) is RegimeState.TRENDING_UP

    def test_slope_at_threshold_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(
            adx=30.0, plus_di=30.0, minus_di=15.0, ema_slope=0.0005
        )
        assert classifier.decide(f) is RegimeState.TRENDING_UP


class TestTrendingDown:
    def test_classic_downtrend(self, classifier: RuleBasedRegimeClassifier):
        f = _features(
            adx=30.0, plus_di=12.0, minus_di=28.0, ema_slope=-0.001
        )
        assert classifier.decide(f) is RegimeState.TRENDING_DOWN

    def test_slope_at_negative_threshold_triggers(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(
            adx=30.0, plus_di=12.0, minus_di=28.0, ema_slope=-0.0005
        )
        assert classifier.decide(f) is RegimeState.TRENDING_DOWN


class TestTrendingDisagreement:
    def test_high_adx_but_di_disagrees_with_slope_is_unknown(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # Whipsaw: ADX strong, slope up, but -DI > +DI. No clean direction.
        f = _features(
            adx=30.0, plus_di=15.0, minus_di=25.0, ema_slope=0.001
        )
        assert classifier.decide(f) is RegimeState.UNKNOWN

    def test_high_adx_but_slope_flat_is_unknown(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(
            adx=30.0, plus_di=30.0, minus_di=15.0, ema_slope=0.0001
        )
        assert classifier.decide(f) is RegimeState.UNKNOWN


# ---------------------------------------------------------------------------
# RANGING (priority 4 — both BB width LOW and ADX LOW)
# ---------------------------------------------------------------------------


class TestRanging:
    def test_classic_ranging(self, classifier: RuleBasedRegimeClassifier):
        f = _features(
            adx=15.0,
            plus_di=20.0,
            minus_di=20.0,
            bb_width_pct=0.20,
            ema_slope=0.0,
        )
        assert classifier.decide(f) is RegimeState.RANGING

    def test_bb_width_at_low_threshold_does_not_trigger(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # < boundary on BB width: equality is the start of "not low",
        # mirrors how the high-vol guard uses >=.
        f = _features(adx=15.0, bb_width_pct=0.30)
        assert classifier.decide(f) is RegimeState.UNKNOWN

    def test_low_bb_width_but_high_adx_is_not_ranging(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # ADX above the trend-min floor disqualifies ranging even if width
        # is compressed — protects RSI/Bollinger MR strategies from
        # entering during a tight-range breakout setup.
        f = _features(
            adx=30.0,
            plus_di=30.0,
            minus_di=15.0,
            bb_width_pct=0.10,
            ema_slope=0.001,
        )
        # This is actually a clean trending up case, since slope and DI agree.
        assert classifier.decide(f) is RegimeState.TRENDING_UP

    def test_low_bb_width_high_adx_no_trend_agreement_is_unknown(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # Compressed width + high ADX but ambiguous direction → not ranging
        # and not trending → UNKNOWN.
        f = _features(
            adx=30.0,
            plus_di=15.0,
            minus_di=25.0,
            bb_width_pct=0.10,
            ema_slope=0.001,  # slope up but -DI dominates
        )
        assert classifier.decide(f) is RegimeState.UNKNOWN


# ---------------------------------------------------------------------------
# Determinism / purity
# ---------------------------------------------------------------------------


class TestPurity:
    def test_same_features_yield_same_state(
        self, classifier: RuleBasedRegimeClassifier
    ):
        f = _features(
            adx=30.0, plus_di=30.0, minus_di=15.0, ema_slope=0.001
        )
        results = {classifier.decide(f) for _ in range(10)}
        assert results == {RegimeState.TRENDING_UP}

    def test_classifier_holds_no_mutable_state(
        self, classifier: RuleBasedRegimeClassifier
    ):
        # Probe with high-vol features then ranging features — the second
        # call must not be coloured by the first.
        classifier.decide(_features(bb_width_pct=0.99))
        f = _features(adx=15.0, bb_width_pct=0.20)
        assert classifier.decide(f) is RegimeState.RANGING


# ---------------------------------------------------------------------------
# NaN rejection (defence-in-depth: caught at RegimeFeatures construction)
# ---------------------------------------------------------------------------


class TestNaNRejection:
    @pytest.mark.parametrize(
        "field",
        [
            "adx",
            "plus_di",
            "minus_di",
            "bb_width_pct",
            "realized_vol",
            "ema_slope",
        ],
    )
    def test_nan_in_any_feature_raises_at_construction(self, field: str):
        # NaN comparisons silently evaluate False, which would let a glitched
        # indicator value bypass the HIGH_VOLATILITY kill-switch. Catch at
        # construction so the classifier never sees NaN.
        with pytest.raises(ValueError, match=field):
            _features(**{field: float("nan")})
