"""Per-bar feature extraction for the regime classifier.

``FeatureExtractor`` owns the four indicators required by the rule-based
classifier (ADX, Bollinger band width, realized volatility, EMA slope)
plus a bars-seen counter for the warmup gate. Each instance is scoped to
a single ``BarType`` (e.g. ``XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL``);
the router constructs one per stream so M5 and M15 do not share state.

Indicators are injected so callers wire them from the YAML config and
tests substitute trivially-warmable instances. The extractor only emits
``RegimeFeatures`` once **every** indicator has produced at least one
value AND ``warmup_bars`` total bars have been seen — the latter guards
against the classifier acting on a freshly-initialised but still
statistically thin window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nautilus_trader.model.data import Bar

from src.indicators.adx import ADX
from src.indicators.bb_width import BollingerBandWidth
from src.indicators.ema_slope import EMASlope
from src.indicators.realized_vol import RealizedVolatility


@dataclass(frozen=True)
class RegimeFeatures:
    """Snapshot of regime-relevant indicators at one bar boundary.

    All fields are floats except ``is_warmed_up``. Tests construct
    instances with ``is_warmed_up=False`` to exercise the classifier's
    UNKNOWN-during-warmup branch; the extractor itself only emits
    instances with ``is_warmed_up=True``.
    """

    adx: float
    plus_di: float
    minus_di: float
    bb_width_pct: float
    realized_vol: float
    ema_slope: float
    is_warmed_up: bool

    def __post_init__(self) -> None:
        # NaN reaching the classifier silently bypasses every threshold
        # comparison (NaN >= x is always False) — that would let an upstream
        # indicator glitch leak past the HIGH_VOLATILITY kill-switch on a
        # financial-decision path. Reject at construction so the failure is
        # loud and caught at the extractor boundary.
        for field_name in (
            "adx",
            "plus_di",
            "minus_di",
            "bb_width_pct",
            "realized_vol",
            "ema_slope",
        ):
            value = getattr(self, field_name)
            if math.isnan(value):
                raise ValueError(
                    f"RegimeFeatures.{field_name} must not be NaN"
                )


class FeatureExtractor:
    """Coordinates the four regime indicators for one bar stream."""

    def __init__(
        self,
        bar_type: str,
        adx: ADX,
        bb_width: BollingerBandWidth,
        realized_vol: RealizedVolatility,
        ema_slope: EMASlope,
        warmup_bars: int,
    ) -> None:
        if not bar_type:
            raise ValueError("bar_type must be a non-empty string")
        if warmup_bars <= 0:
            raise ValueError(f"warmup_bars must be positive, got {warmup_bars}")
        self._bar_type = bar_type
        self._adx = adx
        self._bb_width = bb_width
        self._realized_vol = realized_vol
        self._ema_slope = ema_slope
        self._warmup_bars = warmup_bars
        self._bars_seen = 0

    @property
    def bar_type(self) -> str:
        return self._bar_type

    @property
    def warmup_bars(self) -> int:
        return self._warmup_bars

    @property
    def warmup_progress(self) -> float:
        return min(1.0, self._bars_seen / self._warmup_bars)

    def update(self, bar: Bar) -> RegimeFeatures | None:
        """Feed ``bar`` to all indicators and return features when ready.

        Returns ``None`` while either the bars-seen counter is below
        ``warmup_bars`` or any underlying indicator has not yet produced
        its first value.
        """
        self._bars_seen += 1
        self._adx.handle_bar(bar)
        self._bb_width.handle_bar(bar)
        self._realized_vol.handle_bar(bar)
        self._ema_slope.handle_bar(bar)

        if self._bars_seen < self._warmup_bars:
            return None
        if not (
            self._adx.initialized
            and self._bb_width.initialized
            and self._realized_vol.initialized
            and self._ema_slope.initialized
        ):
            return None
        # Once .initialized is true every indicator must report a value;
        # asserting surfaces an upstream NautilusTrader regression loudly
        # rather than swallowing it as a silent UNKNOWN regime.
        adx_value = self._adx.value
        plus_di = self._adx.plus_di
        minus_di = self._adx.minus_di
        bb_pct = self._bb_width.percentile
        rv = self._realized_vol.value
        slope = self._ema_slope.value
        assert adx_value is not None
        assert plus_di is not None
        assert minus_di is not None
        assert bb_pct is not None
        assert rv is not None
        assert slope is not None
        return RegimeFeatures(
            adx=adx_value,
            plus_di=plus_di,
            minus_di=minus_di,
            bb_width_pct=bb_pct,
            realized_vol=rv,
            ema_slope=slope,
            is_warmed_up=True,
        )
