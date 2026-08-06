"""Average Directional Index (ADX) indicator — Wilder's algorithm.

Measures trend strength (0-100, direction-agnostic) via smoothed directional
movements. ADX > 25 is commonly treated as "trending", < 20 as "choppy".

Per-bar calculation:
    up_move   = high[t] - high[t-1]
    down_move = low[t-1] - low[t]
    +DM = up_move   if up_move > down_move and up_move > 0 else 0
    -DM = down_move if down_move > up_move and down_move > 0 else 0
    TR  = max(high - low, |high - close[t-1]|, |low - close[t-1]|)

Wilder smoothing for the absolute accumulators (+DM, -DM, TR):
    first N bars:  smoothed = sum(first N raw values)
    thereafter:    smoothed[t] = smoothed[t-1] - smoothed[t-1]/N + raw[t]

Directional indicators:
    +DI = 100 * smoothed_+DM / smoothed_TR
    -DI = 100 * smoothed_-DM / smoothed_TR
    DX  = 100 * |+DI - -DI| / (+DI + -DI)

ADX is a ratio (0-100), so it uses the **normalized** EMA form rather than
the absolute-accumulator Wilder form:
    first ADX:  mean(first N DX values)
    thereafter: ADX[t] = (ADX[t-1] * (N - 1) + DX[t]) / N

Both formulations are mathematically valid Wilder variants; the absolute
form is correct for sums, the normalized form is correct for ratios. Full
initialisation therefore needs ~2*N bars: N to seed DI, then N more to
seed ADX.
"""

from __future__ import annotations

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class ADX(Indicator):
    """Average Directional Index with +DI / -DI components.

    Attributes:
        period: Wilder smoothing period (standard = 14).
        value: Current ADX value (None until initialised).
        plus_di: Current +DI (None until DI-phase initialised).
        minus_di: Current -DI (None until DI-phase initialised).
    """

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        super().__init__([period])
        self._period = period
        self._prev_high: float | None = None
        self._prev_low: float | None = None
        self._prev_close: float | None = None

        # Warmup accumulators for the first-N Wilder seed.
        self._pdm_seed: list[float] = []
        self._mdm_seed: list[float] = []
        self._tr_seed: list[float] = []

        # Smoothed values (post-seed).
        self._pdm_smoothed: float | None = None
        self._mdm_smoothed: float | None = None
        self._tr_smoothed: float | None = None

        # DX warmup for ADX seed.
        self._dx_seed: list[float] = []
        self._adx: float | None = None

        self._plus_di: float | None = None
        self._minus_di: float | None = None

    @property
    def period(self) -> int:
        return self._period

    @property
    def value(self) -> float | None:
        return self._adx

    @property
    def plus_di(self) -> float | None:
        return self._plus_di

    @property
    def minus_di(self) -> float | None:
        return self._minus_di

    def handle_bar(self, bar: Bar) -> None:
        high = bar.high.as_double()
        low = bar.low.as_double()
        close = bar.close.as_double()
        self._set_has_inputs(True)

        if self._prev_high is None:
            self._prev_high = high
            self._prev_low = low
            self._prev_close = close
            return

        up_move = high - self._prev_high
        down_move = self._prev_low - low
        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr = max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )

        # Stage 1: accumulate first N raw values for Wilder seed.
        if self._tr_smoothed is None:
            self._pdm_seed.append(pdm)
            self._mdm_seed.append(mdm)
            self._tr_seed.append(tr)
            if len(self._tr_seed) == self._period:
                self._pdm_smoothed = sum(self._pdm_seed)
                self._mdm_smoothed = sum(self._mdm_seed)
                self._tr_smoothed = sum(self._tr_seed)
                self._update_di_and_dx()
        else:
            # Wilder recursive smoothing.
            self._pdm_smoothed = self._pdm_smoothed - self._pdm_smoothed / self._period + pdm
            self._mdm_smoothed = self._mdm_smoothed - self._mdm_smoothed / self._period + mdm
            self._tr_smoothed = self._tr_smoothed - self._tr_smoothed / self._period + tr
            self._update_di_and_dx()

        self._prev_high = high
        self._prev_low = low
        self._prev_close = close

    def _update_di_and_dx(self) -> None:
        """Compute +DI, -DI, DX and fold DX into ADX seed / smoothing."""
        if self._tr_smoothed == 0:
            self._plus_di = 0.0
            self._minus_di = 0.0
            dx = 0.0
        else:
            self._plus_di = 100.0 * self._pdm_smoothed / self._tr_smoothed
            self._minus_di = 100.0 * self._mdm_smoothed / self._tr_smoothed
            di_sum = self._plus_di + self._minus_di
            dx = (
                100.0 * abs(self._plus_di - self._minus_di) / di_sum
                if di_sum > 0
                else 0.0
            )

        if self._adx is None:
            self._dx_seed.append(dx)
            if len(self._dx_seed) == self._period:
                self._adx = sum(self._dx_seed) / self._period
                self._set_initialized(True)
        else:
            self._adx = (self._adx * (self._period - 1) + dx) / self._period

    def _reset(self) -> None:
        self._prev_high = None
        self._prev_low = None
        self._prev_close = None
        self._pdm_seed = []
        self._mdm_seed = []
        self._tr_seed = []
        self._pdm_smoothed = None
        self._mdm_smoothed = None
        self._tr_smoothed = None
        self._dx_seed = []
        self._adx = None
        self._plus_di = None
        self._minus_di = None
