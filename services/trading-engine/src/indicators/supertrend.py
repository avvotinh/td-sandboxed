"""Supertrend indicator.

Trend-following indicator built on ATR:
    basic_upper = (high + low) / 2 + multiplier * ATR
    basic_lower = (high + low) / 2 - multiplier * ATR

Final bands carry forward unless a new basic band tightens the channel or
the previous close has already pierced the prior final band:
    final_upper[t] = basic_upper[t]           if basic_upper[t] < final_upper[t-1]
                                              or close[t-1] > final_upper[t-1]
                     else final_upper[t-1]
    final_lower[t] = basic_lower[t]           if basic_lower[t] > final_lower[t-1]
                                              or close[t-1] < final_lower[t-1]
                     else final_lower[t-1]

Supertrend line flips:
    uptrend (trend=+1):   line = final_lower
    downtrend (trend=-1): line = final_upper

Not initialised until the internal ATR is initialised. Strategies should
guard signal generation on ``.initialized``.
"""

from __future__ import annotations

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar


class Supertrend(Indicator):
    """Supertrend indicator composing an internal ATR.

    Attributes:
        period: ATR period.
        multiplier: ATR multiplier for band width.
        value: Current supertrend line value (None until initialised).
        trend: +1 in uptrend, -1 in downtrend, 0 before initialisation.
    """

    def __init__(self, period: int, multiplier: float) -> None:
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        if multiplier <= 0:
            raise ValueError(f"multiplier must be positive, got {multiplier}")
        super().__init__([period, multiplier])
        self._period = period
        self._multiplier = float(multiplier)
        self._atr = AverageTrueRange(period)
        self._prev_close: float | None = None
        self._prev_final_upper: float | None = None
        self._prev_final_lower: float | None = None
        self._value: float | None = None
        self._trend: int = 0

    @property
    def period(self) -> int:
        return self._period

    @property
    def multiplier(self) -> float:
        return self._multiplier

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def trend(self) -> int:
        return self._trend

    def handle_bar(self, bar: Bar) -> None:
        high = bar.high.as_double()
        low = bar.low.as_double()
        close = bar.close.as_double()
        self._atr.handle_bar(bar)
        self._set_has_inputs(True)

        if not self._atr.initialized:
            self._prev_close = close
            return

        hl2 = (high + low) / 2.0
        atr = self._atr.value
        basic_upper = hl2 + self._multiplier * atr
        basic_lower = hl2 - self._multiplier * atr

        prev_final_upper = self._prev_final_upper
        prev_final_lower = self._prev_final_lower
        # _prev_close is always set during ATR warm-up, so by the time ATR
        # is initialised it is non-None.
        prev_close = self._prev_close

        if prev_final_upper is None or basic_upper < prev_final_upper or prev_close > prev_final_upper:
            final_upper = basic_upper
        else:
            final_upper = prev_final_upper

        if prev_final_lower is None or basic_lower > prev_final_lower or prev_close < prev_final_lower:
            final_lower = basic_lower
        else:
            final_lower = prev_final_lower

        # Determine trend / line.
        if self._value is None:
            # First initialised bar — default to uptrend (Pine Script
            # convention: nz(direction[1], 1)). Only seed -1 when close has
            # already pierced the lower band; otherwise start long-biased.
            if close < final_lower:
                self._trend = -1
                self._value = final_upper
            else:
                self._trend = 1
                self._value = final_lower
        elif self._trend == 1:
            if close < final_lower:
                self._trend = -1
                self._value = final_upper
            else:
                self._value = final_lower
        else:  # trend == -1
            if close > final_upper:
                self._trend = 1
                self._value = final_lower
            else:
                self._value = final_upper

        self._prev_final_upper = final_upper
        self._prev_final_lower = final_lower
        self._prev_close = close
        self._set_initialized(True)

    def _reset(self) -> None:
        self._atr.reset()
        self._prev_close = None
        self._prev_final_upper = None
        self._prev_final_lower = None
        self._value = None
        self._trend = 0
