"""Unit tests for ``HysteresisFilter`` (Epic 11 story 11.4).

The filter sits between the pure :class:`RuleBasedRegimeClassifier` and
the audit/router pipeline. It enforces a 2-bar confirmation rule (the
default ``confirmation_bars=2``) so a one-off classifier flicker does
not flip the regime that strategies subscribe to. State is per-instance
so the bootstrap factory in story 11.7 can construct one filter per
``BarType`` and keep M5 and M15 streams isolated.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.config.firm_profile import RegimeThresholds
from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.hysteresis import HysteresisFilter
from src.regime.states import RegimeState

BAR_TYPE = "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"


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
        adx=30.0,
        plus_di=30.0,
        minus_di=15.0,
        bb_width_pct=0.50,
        realized_vol=0.012,
        ema_slope=0.001,
        is_warmed_up=True,
    )
    base.update(overrides)
    return RegimeFeatures(**base)  # type: ignore[arg-type]


def _ts(minute: int = 0) -> datetime:
    return datetime(2026, 5, 1, 12, minute, tzinfo=timezone.utc)


@pytest.fixture
def filt() -> HysteresisFilter:
    return HysteresisFilter(
        bar_type=BAR_TYPE,
        confirmation_bars=2,
        thresholds=_thresholds(),
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_holds_bar_type_thresholds_and_confirmation_bars(self):
        t = _thresholds()
        f = HysteresisFilter(
            bar_type=BAR_TYPE, confirmation_bars=3, thresholds=t
        )
        assert f.bar_type == BAR_TYPE
        assert f.confirmation_bars == 3
        assert f.thresholds is t

    def test_initial_state_is_unknown(self, filt: HysteresisFilter):
        snap = filt.snapshot()
        assert snap["current_state"] is RegimeState.UNKNOWN
        assert snap["pending_state"] is None
        assert snap["bars_in_pending"] == 0

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_non_positive_confirmation_bars(self, bad: int):
        with pytest.raises(ValueError, match="confirmation_bars"):
            HysteresisFilter(
                bar_type=BAR_TYPE,
                confirmation_bars=bad,
                thresholds=_thresholds(),
            )

    def test_rejects_empty_bar_type(self):
        with pytest.raises(ValueError, match="bar_type"):
            HysteresisFilter(
                bar_type="",
                confirmation_bars=2,
                thresholds=_thresholds(),
            )


# ---------------------------------------------------------------------------
# Apply — state transitions
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def test_first_bar_same_as_current_emits_decision(
        self, filt: HysteresisFilter
    ):
        # current starts as UNKNOWN; raw=UNKNOWN keeps it stable.
        d = filt.apply(RegimeState.UNKNOWN, _ts(0), _features())
        assert isinstance(d, RegimeDecision)
        assert d.current_state is RegimeState.UNKNOWN
        assert d.raw_state is RegimeState.UNKNOWN
        assert d.pending_state is None
        assert d.bars_in_pending == 0

    def test_new_state_starts_pending_does_not_promote(
        self, filt: HysteresisFilter
    ):
        d = filt.apply(
            RegimeState.TRENDING_UP, _ts(0), _features()
        )
        assert d.current_state is RegimeState.UNKNOWN
        assert d.raw_state is RegimeState.TRENDING_UP
        assert d.pending_state is RegimeState.TRENDING_UP
        assert d.bars_in_pending == 1

    def test_two_consecutive_promote(self, filt: HysteresisFilter):
        filt.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        d = filt.apply(
            RegimeState.TRENDING_UP, _ts(5), _features()
        )
        assert d.current_state is RegimeState.TRENDING_UP
        assert d.pending_state is None
        assert d.bars_in_pending == 0

    def test_pending_resets_when_raw_matches_current(
        self, filt: HysteresisFilter
    ):
        # Current is UNKNOWN, raw flips to TRENDING_UP (pending=1), then
        # raw flips back to UNKNOWN — pending must drop, not promote.
        filt.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        d = filt.apply(
            RegimeState.UNKNOWN, _ts(5), _features(adx=15.0)
        )
        assert d.current_state is RegimeState.UNKNOWN
        assert d.pending_state is None
        assert d.bars_in_pending == 0

    def test_pending_swaps_to_new_candidate(self, filt: HysteresisFilter):
        # Pending is TRENDING_UP after first bar; classifier flips to
        # RANGING — pending must restart, not accumulate against the
        # original candidate.
        filt.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        d = filt.apply(
            RegimeState.RANGING,
            _ts(5),
            _features(adx=15.0, bb_width_pct=0.20),
        )
        assert d.current_state is RegimeState.UNKNOWN
        assert d.pending_state is RegimeState.RANGING
        assert d.bars_in_pending == 1

    def test_post_promotion_a_single_disagreement_does_not_revert(
        self, filt: HysteresisFilter
    ):
        # Promote to TRENDING_UP with two bars, then one HIGH_VOL bar — the
        # current state must hold (HIGH_VOL pending=1) so a single noisy
        # bar cannot override a confirmed regime.
        filt.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        filt.apply(RegimeState.TRENDING_UP, _ts(5), _features())
        d = filt.apply(
            RegimeState.HIGH_VOLATILITY,
            _ts(10),
            _features(bb_width_pct=0.95, realized_vol=0.03),
        )
        assert d.current_state is RegimeState.TRENDING_UP
        assert d.pending_state is RegimeState.HIGH_VOLATILITY
        assert d.bars_in_pending == 1

    def test_confirmation_bars_one_promotes_immediately(self):
        # ``confirmation_bars=1`` is a legal degenerate config that
        # disables hysteresis — a single bar flips the state.
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=1, thresholds=_thresholds())
        d = f.apply(RegimeState.RANGING, _ts(0), _features())
        assert d.current_state is RegimeState.RANGING
        assert d.pending_state is None
        assert d.bars_in_pending == 0


# ---------------------------------------------------------------------------
# Multi-instance isolation (story 11.7 AC5 prerequisite)
# ---------------------------------------------------------------------------


class TestMultiInstanceIsolation:
    def test_two_filters_keep_state_independently(self):
        m5 = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        m15 = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        m5.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        m5.apply(RegimeState.TRENDING_UP, _ts(5), _features())
        # m15 has not seen any bars — must still be UNKNOWN.
        assert m5.snapshot()["current_state"] is RegimeState.TRENDING_UP
        assert m15.snapshot()["current_state"] is RegimeState.UNKNOWN


# ---------------------------------------------------------------------------
# RegimeDecision shape (the audit + router contract)
# ---------------------------------------------------------------------------


class TestDecisionShape:
    def test_decision_carries_features_timestamp_bar_type(
        self, filt: HysteresisFilter
    ):
        f = _features(adx=30.0)
        ts = _ts(15)
        d = filt.apply(RegimeState.TRENDING_UP, ts, f)
        assert d.timestamp is ts
        assert d.bar_type == BAR_TYPE
        assert d.features is f

    def test_naive_timestamp_propagates_from_decision_validation(
        self, filt: HysteresisFilter
    ):
        # The filter does not re-validate the timestamp itself; it relies
        # on RegimeDecision.__post_init__ to reject naive timestamps.
        with pytest.raises(ValueError, match="timestamp"):
            filt.apply(
                RegimeState.TRENDING_UP,
                datetime(2026, 5, 1, 12, 0),
                _features(),
            )


# ---------------------------------------------------------------------------
# Confidence — stability × threshold-margin
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_unknown_current_state_has_zero_confidence(
        self, filt: HysteresisFilter
    ):
        d = filt.apply(RegimeState.UNKNOWN, _ts(0), _features())
        assert d.confidence == pytest.approx(0.0)

    def test_stable_strong_trend_saturates_to_one(self):
        # ADX at adx_strong_trend → margin saturates at 1.0; pending=None
        # → stability=1.0; confidence=1.0.
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        feat = _features(adx=40.0)
        f.apply(RegimeState.TRENDING_UP, _ts(0), feat)
        d = f.apply(RegimeState.TRENDING_UP, _ts(5), feat)
        assert d.current_state is RegimeState.TRENDING_UP
        assert d.confidence == pytest.approx(1.0)

    def test_mid_transition_reduces_confidence(self):
        # Promote TRENDING_UP, then one HIGH_VOL bar — current still
        # TRENDING_UP but pending=HIGH_VOL bars=1; stability halves so
        # confidence < the pre-disagreement value.
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        feat = _features(adx=40.0)
        f.apply(RegimeState.TRENDING_UP, _ts(0), feat)
        f.apply(RegimeState.TRENDING_UP, _ts(5), feat)
        d = f.apply(
            RegimeState.HIGH_VOLATILITY,
            _ts(10),
            _features(adx=40.0, bb_width_pct=0.95, realized_vol=0.03),
        )
        # Stable trending was 1.0; one bar of disagreement → stability=0.5;
        # margin still 1.0 because adx hasn't changed → confidence=0.5.
        assert d.current_state is RegimeState.TRENDING_UP
        assert d.confidence == pytest.approx(0.5)

    def test_high_vol_margin_uses_max_of_bb_width_and_realized_vol(self):
        # HIGH_VOL bb_width margin (0.95-0.80)/(1-0.80)=0.75; realized_vol
        # margin (0.05-0.025)/0.025=1.0 → max=1.0.
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        feat = _features(bb_width_pct=0.95, realized_vol=0.05)
        f.apply(RegimeState.HIGH_VOLATILITY, _ts(0), feat)
        d = f.apply(RegimeState.HIGH_VOLATILITY, _ts(5), feat)
        assert d.confidence == pytest.approx(1.0)

    def test_ranging_margin_grows_as_width_compresses(self):
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        # bb_width_pct=0.15, bb_width_low_pct=0.30 → margin=1-0.5=0.5
        feat = _features(adx=15.0, bb_width_pct=0.15, ema_slope=0.0)
        f.apply(RegimeState.RANGING, _ts(0), feat)
        d = f.apply(RegimeState.RANGING, _ts(5), feat)
        assert d.confidence == pytest.approx(0.5)

    def test_confidence_clamps_to_unit_interval(self):
        # Extreme realized vol must not push confidence above 1.
        f = HysteresisFilter(bar_type=BAR_TYPE, confirmation_bars=2, thresholds=_thresholds())
        feat = _features(bb_width_pct=0.99, realized_vol=10.0)
        f.apply(RegimeState.HIGH_VOLATILITY, _ts(0), feat)
        d = f.apply(RegimeState.HIGH_VOLATILITY, _ts(5), feat)
        assert 0.0 <= d.confidence <= 1.0

    def test_stale_regime_confidence_collapses_to_zero(self):
        # Confirm HIGH_VOLATILITY, then feed a bar whose features have
        # already retreated below both thresholds. Hysteresis still
        # reports current=HIGH_VOL (waiting for replacement to confirm)
        # but margin → 0, so confidence → 0. Downstream consumers must
        # treat this as "dampen exposure", not "regime is wrong".
        f = HysteresisFilter(
            bar_type=BAR_TYPE,
            confirmation_bars=2,
            thresholds=_thresholds(),
        )
        hot = _features(bb_width_pct=0.95, realized_vol=0.05)
        f.apply(RegimeState.HIGH_VOLATILITY, _ts(0), hot)
        f.apply(RegimeState.HIGH_VOLATILITY, _ts(5), hot)
        cool = _features(bb_width_pct=0.50, realized_vol=0.01)
        d = f.apply(RegimeState.HIGH_VOLATILITY, _ts(10), cool)
        assert d.current_state is RegimeState.HIGH_VOLATILITY
        assert d.confidence == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_returns_expected_keys(self, filt: HysteresisFilter):
        filt.apply(RegimeState.TRENDING_UP, _ts(0), _features())
        snap = filt.snapshot()
        assert set(snap) == {
            "current_state",
            "pending_state",
            "bars_in_pending",
            "confirmation_bars",
        }
        assert snap["current_state"] is RegimeState.UNKNOWN
        assert snap["pending_state"] is RegimeState.TRENDING_UP
        assert snap["bars_in_pending"] == 1
        assert snap["confirmation_bars"] == 2

    def test_snapshot_is_a_copy_not_live_state(
        self, filt: HysteresisFilter
    ):
        # Mutating the dict the caller receives must not corrupt internal
        # state — the audit/log path may stash the snapshot.
        snap = filt.snapshot()
        snap["current_state"] = RegimeState.HIGH_VOLATILITY
        assert filt.snapshot()["current_state"] is RegimeState.UNKNOWN
