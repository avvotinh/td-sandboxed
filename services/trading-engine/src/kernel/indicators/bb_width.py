"""Bollinger band width indicator with rolling percentile.

Computes the normalised width of the Bollinger band envelope at each bar
plus its rank inside a longer rolling baseline. The percentile (0-1) is
what the regime classifier consumes — raw width is exposed for
debugging.

Width formula:
    middle = SMA(close, period)
    σ      = stdev(close, period)         # population (ddof=0)
    width  = (2 * num_std * σ) / middle   # normalised by middle to be
                                          # comparable across price levels

Percentile uses the standard "percent rank" formula
``(count_less + 0.5 * count_equal) / n`` so that ties resolve to the
midpoint rather than collapsing to either extreme — important when the
baseline contains long stretches of identical values (e.g. a market in a
zero-volatility lull). Range [0, 1].
"""

from __future__ import annotations

from collections import deque

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar


class BollingerBandWidth(Indicator):
    """Normalised Bollinger band width with rolling-baseline percentile.

    Attributes:
        period: SMA / stdev window for the bands.
        num_std: Number of standard deviations for the band envelope.
        baseline_window: Rolling window for the percentile baseline.
        value: Current normalised width (None until ``period`` bars seen).
        percentile: Percent rank of current width in the baseline
            window, in ``[0, 1]``. None until first width computed.
    """

    def __init__(self, period: int, num_std: float, baseline_window: int) -> None:
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        if num_std <= 0:
            raise ValueError(f"num_std must be positive, got {num_std}")
        if baseline_window <= 0:
            raise ValueError(
                f"baseline_window must be positive, got {baseline_window}"
            )
        super().__init__([period, num_std, baseline_window])
        self._period = period
        self._num_std = num_std
        self._baseline_window = baseline_window
        self._closes: deque[float] = deque(maxlen=period)
        self._baseline: deque[float] = deque(maxlen=baseline_window)
        self._value: float | None = None
        self._percentile: float | None = None

    @property
    def period(self) -> int:
        return self._period

    @property
    def num_std(self) -> float:
        return self._num_std

    @property
    def baseline_window(self) -> int:
        return self._baseline_window

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def percentile(self) -> float | None:
        return self._percentile

    def handle_bar(self, bar: Bar) -> None:
        close = bar.close.as_double()
        self._set_has_inputs(True)
        self._closes.append(close)
        if len(self._closes) < self._period:
            return

        mean = sum(self._closes) / self._period
        var = sum((c - mean) ** 2 for c in self._closes) / self._period
        std = var**0.5

        # Normalise by the middle band so width is comparable across price
        # levels. Defensive zero-guard for synthetic / pathological inputs.
        if mean == 0:
            self._value = 0.0
        else:
            self._value = (2.0 * self._num_std * std) / mean

        self._baseline.append(self._value)
        less = 0
        equal = 0
        for v in self._baseline:
            if v < self._value:
                less += 1
            elif v == self._value:
                equal += 1
        self._percentile = (less + 0.5 * equal) / len(self._baseline)
        if not self.initialized:
            self._set_initialized(True)

    def _reset(self) -> None:
        self._closes.clear()
        self._baseline.clear()
        self._value = None
        self._percentile = None
