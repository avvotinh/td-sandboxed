"""Rule-based regime classifier (Epic 11 story 11.3).

Pure function of :class:`RegimeFeatures` plus a
:class:`RegimeThresholds` value object. Decision priority, in order:

1. **Warmup gate** — return ``UNKNOWN`` if features are not warmed up.
2. **HIGH_VOLATILITY** — bb_width_pct or realized_vol crosses the high
   threshold. Acts as a global kill-switch (FTMO daily-loss protection).
3. **TRENDING_UP / TRENDING_DOWN** — ADX strong AND EMA slope and DI
   direction agree. Disagreement collapses to ``UNKNOWN`` rather than
   forcing a directional call.
4. **RANGING** — both BB width compressed AND ADX below the trend floor.
5. **UNKNOWN** — residual / no clean signal.

The HIGH_VOLATILITY branch is checked first so an exploding-vol bar
cannot leak through under a coincidentally-rising EMA. The TRENDING vs
RANGING ordering does not matter at the boundary because they are
mutually exclusive (TRENDING needs ADX ≥ trend_min, RANGING needs ADX
< trend_min).
"""

from __future__ import annotations

from src.config.firm_profile import RegimeThresholds
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState


class RuleBasedRegimeClassifier:
    """Stateless classifier — same features in, same state out.

    Note: ``thresholds.adx_strong_trend`` is wired through the YAML and
    validated upstream but is not consumed by ``decide``. It is reserved
    for the hysteresis-side confidence score in story 11.4 (saturation
    point at which a trend is "fully confident") — keeping it on
    :class:`RegimeThresholds` now avoids a YAML migration when 11.4 lands.
    """

    def __init__(self, thresholds: RegimeThresholds) -> None:
        self._thresholds = thresholds

    @property
    def thresholds(self) -> RegimeThresholds:
        return self._thresholds

    def decide(self, features: RegimeFeatures) -> RegimeState:
        """Return the regime state for a single bar's features."""
        if not features.is_warmed_up:
            return RegimeState.UNKNOWN

        t = self._thresholds

        if (
            features.bb_width_pct >= t.bb_width_high_pct
            or features.realized_vol >= t.realized_vol_high
        ):
            return RegimeState.HIGH_VOLATILITY

        if features.adx >= t.adx_trend_min:
            slope = features.ema_slope
            if (
                slope >= t.ema_slope_trend_threshold
                and features.plus_di > features.minus_di
            ):
                return RegimeState.TRENDING_UP
            if (
                slope <= -t.ema_slope_trend_threshold
                and features.minus_di > features.plus_di
            ):
                return RegimeState.TRENDING_DOWN
            return RegimeState.UNKNOWN

        if features.bb_width_pct < t.bb_width_low_pct:
            return RegimeState.RANGING

        return RegimeState.UNKNOWN


__all__ = ["RuleBasedRegimeClassifier"]
