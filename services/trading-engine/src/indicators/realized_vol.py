"""Realized volatility — annualised standard deviation of log returns.

Computes population stdev of log returns over a rolling window. The
annualisation factor is applied as a multiplier (typically
``sqrt(periods_per_year)``) so callers can express volatility on whatever
horizon their thresholds are calibrated for.

Per-bar update:
    r_t   = ln(close_t / close_{t-1})
    σ²    = mean((r - mean(r))²)        over the last ``window`` returns
    value = sqrt(σ²) * annualisation_factor

The window stores returns, not closes — one return per closed bar after
the first. Initialisation requires ``window + 1`` bars (the first bar
seeds the previous-close reference, then ``window`` returns accumulate).
"""

from __future__ import annotations

from collections import deque
from math import log

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class RealizedVolatility(Indicator):
    """Realized volatility from log-return stdev.

    Attributes:
        window: Number of log returns in the stdev window. Must be ≥ 2.
        annualisation_factor: Multiplier applied to raw stdev. For an
            unannualised value pass ``1.0``; for daily-bar annualisation
            in a 252-day year, pass ``sqrt(252)``.
        value: Current annualised stdev (None until ``window + 1`` bars
            have been observed).
    """

    def __init__(
        self, window: int, annualisation_factor: float = 1.0
    ) -> None:
        if window < 2:
            raise ValueError(f"window must be >= 2, got {window}")
        if annualisation_factor <= 0:
            raise ValueError(
                "annualisation_factor must be positive, got "
                f"{annualisation_factor}"
            )
        super().__init__([window, annualisation_factor])
        self._window = window
        self._annualisation_factor = annualisation_factor
        self._returns: deque[float] = deque(maxlen=window)
        self._prev_close: float | None = None
        self._value: float | None = None

    @property
    def window(self) -> int:
        return self._window

    @property
    def annualisation_factor(self) -> float:
        return self._annualisation_factor

    @property
    def value(self) -> float | None:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        close = bar.close.as_double()
        self._set_has_inputs(True)

        if self._prev_close is None:
            self._prev_close = close
            return

        # Defensive: log requires positive ratio.
        if self._prev_close > 0 and close > 0:
            self._returns.append(log(close / self._prev_close))
        self._prev_close = close

        if len(self._returns) < self._window:
            return

        mean = sum(self._returns) / self._window
        var = sum((r - mean) ** 2 for r in self._returns) / self._window
        self._value = (var**0.5) * self._annualisation_factor
        if not self.initialized:
            self._set_initialized(True)

    def _reset(self) -> None:
        self._returns.clear()
        self._prev_close = None
        self._value = None
