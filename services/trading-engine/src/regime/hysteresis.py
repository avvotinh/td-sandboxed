"""Hysteresis filter (Epic 11 story 11.4).

Wraps the pure :class:`RuleBasedRegimeClassifier` output in a
``confirmation_bars``-bar confirmation rule so a one-off classifier
flicker does not flip the regime that strategies subscribe to. Each
filter instance owns its own ``current``/``pending``/``bars_in_pending``
state — the bootstrap factory in story 11.7 constructs one filter per
``BarType`` so M5 and M15 streams of the same instrument never share
state.

Confidence emitted on each ``RegimeDecision`` combines two factors:

* **Stability** — 1.0 when there is no pending candidate, decaying
  linearly with ``bars_in_pending / confirmation_bars`` while a
  candidate is being confirmed against the current state.
* **Threshold margin** — how far the current bar's features sit past
  the threshold that defines the current state. ``adx_strong_trend`` is
  the saturation point for trending margins; the BB-width-high and
  realized-vol-high thresholds saturate the HIGH_VOLATILITY margin;
  ``bb_width_low_pct`` caps the RANGING margin.

State on restart is **not** persisted — see ``docs/research/regime-classifier-architecture.md``
§4 ("Hysteresis on restart"). First two bars after restart may flicker;
Phase 2 will persist this to Redis.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from src.config.firm_profile import RegimeThresholds
from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


class HysteresisSnapshot(TypedDict):
    current_state: RegimeState
    pending_state: RegimeState | None
    bars_in_pending: int
    confirmation_bars: int


def _clamp_unit(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class HysteresisFilter:
    """Per-``BarType`` 2-bar (configurable) regime confirmation filter.

    ``bar_type`` is bound at construction so a stream's filter cannot be
    accidentally fed bars from a different stream — the bootstrap factory
    in story 11.7 holds one filter per ``BarType`` and the binding makes
    that contract explicit.
    """

    def __init__(
        self,
        bar_type: str,
        confirmation_bars: int,
        thresholds: RegimeThresholds,
    ) -> None:
        if not bar_type:
            raise ValueError("HysteresisFilter.bar_type must be non-empty")
        if confirmation_bars <= 0:
            raise ValueError(
                "HysteresisFilter.confirmation_bars must be > 0, "
                f"got {confirmation_bars}"
            )
        self._bar_type = bar_type
        self._confirmation_bars = confirmation_bars
        self._thresholds = thresholds
        self._current: RegimeState = RegimeState.UNKNOWN
        self._pending: RegimeState | None = None
        self._bars_in_pending: int = 0

    @property
    def bar_type(self) -> str:
        return self._bar_type

    @property
    def confirmation_bars(self) -> int:
        return self._confirmation_bars

    @property
    def thresholds(self) -> RegimeThresholds:
        return self._thresholds

    def apply(
        self,
        raw: RegimeState,
        ts: datetime,
        features: RegimeFeatures,
    ) -> RegimeDecision:
        """Advance the state machine by one bar and emit a decision."""
        if raw == self._current:
            self._pending = None
            self._bars_in_pending = 0
        else:
            if raw == self._pending:
                self._bars_in_pending += 1
            else:
                self._pending = raw
                self._bars_in_pending = 1
            # Promote uniformly so ``confirmation_bars=1`` flips on the
            # first disagreeing bar (degenerate "no hysteresis" config).
            if self._bars_in_pending >= self._confirmation_bars:
                self._current = raw
                self._pending = None
                self._bars_in_pending = 0

        confidence = self._compute_confidence(features)
        return RegimeDecision(
            timestamp=ts,
            bar_type=self._bar_type,
            current_state=self._current,
            raw_state=raw,
            pending_state=self._pending,
            bars_in_pending=self._bars_in_pending,
            features=features,
            confidence=confidence,
        )

    def snapshot(self) -> HysteresisSnapshot:
        """Return a copy of the internal state for logging/debug.

        A ``confidence`` of 0.0 on a non-UNKNOWN current state is *not* a
        signal that the regime is wrong — it means the features have
        retreated past the defining threshold while a replacement is not
        yet confirmed. Downstream consumers should treat low confidence
        as "dampen exposure", not "ignore regime".
        """
        return {
            "current_state": self._current,
            "pending_state": self._pending,
            "bars_in_pending": self._bars_in_pending,
            "confirmation_bars": self._confirmation_bars,
        }

    # ------------------------------------------------------------------ #
    # Confidence helpers
    # ------------------------------------------------------------------ #

    def _compute_confidence(self, features: RegimeFeatures) -> float:
        if self._current == RegimeState.UNKNOWN:
            return 0.0
        stability = self._stability_factor()
        margin = self._state_margin(self._current, features)
        return _clamp_unit(stability * margin)

    def _stability_factor(self) -> float:
        if self._pending is None:
            return 1.0
        # Decay during transitions so risk consumers dampen exposure as
        # soon as the classifier disagrees, not only after promotion.
        return _clamp_unit(
            1.0 - (self._bars_in_pending / self._confirmation_bars)
        )

    def _state_margin(
        self, state: RegimeState, features: RegimeFeatures
    ) -> float:
        t = self._thresholds
        if state in (RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN):
            span = t.adx_strong_trend - t.adx_trend_min
            if span <= 0:
                return 1.0
            return _clamp_unit((features.adx - t.adx_trend_min) / span)
        if state == RegimeState.HIGH_VOLATILITY:
            bb_span = 1.0 - t.bb_width_high_pct
            bb_margin = (
                (features.bb_width_pct - t.bb_width_high_pct) / bb_span
                if bb_span > 0
                else 1.0
            )
            rv_margin = (
                (features.realized_vol - t.realized_vol_high)
                / t.realized_vol_high
                if t.realized_vol_high > 0
                else 1.0
            )
            return _clamp_unit(max(bb_margin, rv_margin))
        if state == RegimeState.RANGING:
            if t.bb_width_low_pct <= 0:
                return 1.0
            return _clamp_unit(
                1.0 - (features.bb_width_pct / t.bb_width_low_pct)
            )
        return 0.0


__all__ = ["HysteresisFilter", "HysteresisSnapshot"]
