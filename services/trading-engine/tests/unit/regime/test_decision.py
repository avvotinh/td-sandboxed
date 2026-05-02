"""Unit tests for ``RegimeDecision`` dataclass (Epic 11 story 11.3).

``RegimeDecision`` is the value object the hysteresis filter (story 11.4)
emits and the audit adapter / router (stories 11.5 / 11.7) consume. It is
constructed in this story so downstream stories have a stable shape to
target.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


def _features(**overrides: object) -> RegimeFeatures:
    base: dict[str, object] = dict(
        adx=20.0,
        plus_di=22.0,
        minus_di=18.0,
        bb_width_pct=0.4,
        realized_vol=0.012,
        ema_slope=0.0001,
        is_warmed_up=True,
    )
    base.update(overrides)
    return RegimeFeatures(**base)  # type: ignore[arg-type]


def _decision(**overrides: object) -> RegimeDecision:
    base: dict[str, object] = dict(
        timestamp=datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc),
        bar_type="XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL",
        current_state=RegimeState.TRENDING_UP,
        raw_state=RegimeState.TRENDING_UP,
        pending_state=None,
        bars_in_pending=0,
        features=_features(),
        confidence=1.0,
    )
    base.update(overrides)
    return RegimeDecision(**base)  # type: ignore[arg-type]


class TestRegimeDecision:
    def test_minimal_construction(self):
        d = _decision()
        assert d.current_state is RegimeState.TRENDING_UP
        assert d.raw_state is RegimeState.TRENDING_UP
        assert d.pending_state is None
        assert d.bars_in_pending == 0
        assert d.confidence == pytest.approx(1.0)

    def test_is_frozen(self):
        d = _decision()
        with pytest.raises(FrozenInstanceError):
            d.current_state = RegimeState.RANGING  # type: ignore[misc]

    def test_features_round_trip(self):
        f = _features(adx=33.0)
        d = _decision(features=f)
        assert d.features is f

    def test_empty_bar_type_rejected(self):
        with pytest.raises(ValueError, match="bar_type"):
            _decision(bar_type="")

    def test_naive_timestamp_rejected(self):
        # Audit logs are global, so timestamps must carry timezone info to
        # avoid silent UTC vs local-zone drift.
        with pytest.raises(ValueError, match="timestamp"):
            _decision(timestamp=datetime(2026, 5, 1, 12, 30))

    def test_pending_state_must_differ_from_current(self):
        # A "pending" identical to current is meaningless and would let
        # the hysteresis filter loop on no-op transitions.
        with pytest.raises(ValueError, match="pending_state"):
            _decision(
                current_state=RegimeState.TRENDING_UP,
                pending_state=RegimeState.TRENDING_UP,
                bars_in_pending=1,
            )

    def test_bars_in_pending_must_be_zero_when_no_pending(self):
        with pytest.raises(ValueError, match="bars_in_pending"):
            _decision(pending_state=None, bars_in_pending=2)

    def test_bars_in_pending_must_be_positive_when_pending_set(self):
        with pytest.raises(ValueError, match="bars_in_pending"):
            _decision(
                current_state=RegimeState.TRENDING_UP,
                pending_state=RegimeState.RANGING,
                bars_in_pending=0,
            )

    def test_negative_bars_in_pending_rejected(self):
        with pytest.raises(ValueError, match="bars_in_pending"):
            _decision(bars_in_pending=-1)

    @pytest.mark.parametrize("bad_confidence", [-0.01, 1.01, 2.0, -1.0])
    def test_confidence_must_be_in_unit_interval(
        self, bad_confidence: float
    ):
        with pytest.raises(ValueError, match="confidence"):
            _decision(confidence=bad_confidence)

    @pytest.mark.parametrize("ok_confidence", [0.0, 0.5, 1.0])
    def test_confidence_unit_interval_boundaries_allowed(
        self, ok_confidence: float
    ):
        d = _decision(confidence=ok_confidence)
        assert d.confidence == pytest.approx(ok_confidence)

    def test_raw_state_may_differ_from_current_state(self):
        # Mid-hysteresis: classifier emits a new candidate (raw_state)
        # while the router still consumes the stable current_state.
        d = _decision(
            current_state=RegimeState.TRENDING_UP,
            raw_state=RegimeState.RANGING,
            pending_state=RegimeState.RANGING,
            bars_in_pending=2,
        )
        assert d.raw_state is RegimeState.RANGING
        assert d.current_state is RegimeState.TRENDING_UP

    def test_unknown_state_with_pending_is_legal(self):
        # Mid-warmup transition: classifier is still emitting UNKNOWN but
        # hysteresis is tracking a candidate. Must construct cleanly.
        d = _decision(
            current_state=RegimeState.UNKNOWN,
            pending_state=RegimeState.TRENDING_UP,
            bars_in_pending=1,
            confidence=0.5,
        )
        assert d.pending_state is RegimeState.TRENDING_UP
