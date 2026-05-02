"""Slope of an exponential moving average over a fixed lookback.

Reports the fractional change of the EMA over the last ``lookback`` bars:
``(ema[t] - ema[t - lookback]) / ema[t - lookback]``. The numerator is a
direction signal (positive for trend up, negative for trend down) and the
fractional form makes the magnitude comparable across price levels —
the regime classifier compares ``|slope|`` against a single threshold
regardless of whether the instrument trades at 1.20 or 2400.

Initialisation requires ``period + lookback`` bars: ``period`` to seed
the EMA via SMA, then ``lookback`` more so the past-EMA reference is
filled.
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class EMASlope(Indicator):
    """Fractional slope of an EMA over a fixed lookback window.

    Attributes:
        period: EMA span. The smoothing factor is ``2 / (period + 1)``.
        lookback: Number of bars between current EMA and the comparison
            EMA used for the slope numerator.
        value: Fractional slope (None until initialised).
    """

    def __init__(self, period: int, lookback: int) -> None:
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        if lookback <= 0:
            raise ValueError(f"lookback must be positive, got {lookback}")
        super().__init__([period, lookback])
        self._period = period
        self._lookback = lookback
        self._alpha = 2.0 / (period + 1.0)
        self._seed_closes: list[float] = []
        self._ema: float | None = None
        # Past EMA values; we need the value from ``lookback`` bars ago so
        # we keep at most ``lookback + 1`` entries and read from the left.
        self._ema_history: deque[float] = deque(maxlen=lookback + 1)
        self._value: float | None = None

    @property
    def period(self) -> int:
        return self._period

    @property
    def lookback(self) -> int:
        return self._lookback

    @property
    def value(self) -> float | None:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        close = bar.close.as_double()
        self._set_has_inputs(True)

        # Stage 1: seed EMA with SMA over the first ``period`` closes.
        if self._ema is None:
            self._seed_closes.append(close)
            if len(self._seed_closes) < self._period:
                return
            self._ema = sum(self._seed_closes) / self._period
            self._seed_closes = []
        else:
            self._ema = self._alpha * close + (1.0 - self._alpha) * self._ema

        self._ema_history.append(self._ema)

        if len(self._ema_history) < self._lookback + 1:
            return

        past = self._ema_history[0]
        if past == 0:
            self._value = 0.0
        else:
            self._value = (self._ema - past) / past
        if not self.initialized:
            self._set_initialized(True)

    def _reset(self) -> None:
        self._seed_closes.clear()
        self._ema = None
        self._ema_history.clear()
        self._value = None
