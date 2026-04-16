"""Session-anchored Volume-Weighted Average Price.

Nautilus's built-in ``VolumeWeightedAveragePrice`` cumulates from the start
of the stream and never resets. For prop-firm strategies (ORB, intraday
mean reversion) we need VWAP that anchors at the start of each trading
session. This indicator resets its cumulative state whenever a bar crosses
a session boundary in the configured timezone.

Typical price convention:
    typical = (high + low + close) / 3
    vwap    = Σ(typical * volume) / Σ(volume)

Session boundary:
    A new local-tz YYYY-MM-DD opens a new session (uses
    ``SessionFilterMixin.session_id`` for consistency with ORB strategies).

Zero-volume bars are tolerated — the cumulative stays unchanged and
``.value`` preserves the last positive-volume VWAP within the session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.strategies.mixins.session_filter_mixin import SessionFilterMixin


class SessionVWAP(Indicator):
    """Session-anchored VWAP, reset each local trading day.

    Attributes:
        tz: IANA timezone name defining the session boundary.
        value: Current VWAP (None until first positive-volume bar in session).
    """

    def __init__(self, tz: str = "UTC") -> None:
        try:
            ZoneInfo(tz)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Invalid tz: {tz}") from exc
        super().__init__([tz])
        self._tz = tz
        self._current_session_id: str | None = None
        self._cum_pv: float = 0.0
        self._cum_v: float = 0.0
        self._value: float | None = None

    @property
    def tz(self) -> str:
        return self._tz

    @property
    def value(self) -> float | None:
        return self._value

    def handle_bar(self, bar: Bar) -> None:
        self._set_has_inputs(True)
        # Integer division avoids float rounding on sub-minute timestamps
        # (e.g. 23:59:59.999_999_999 becoming 00:00:00 the next day).
        ts_s = bar.ts_init // 1_000_000_000
        ts_dt = datetime.fromtimestamp(ts_s, tz=UTC)
        session_id = SessionFilterMixin.session_id(ts_dt, self._tz)

        if session_id != self._current_session_id:
            self._current_session_id = session_id
            self._cum_pv = 0.0
            self._cum_v = 0.0
            self._value = None
            # Clear initialized so callers never see value=None while
            # initialized=True — e.g. first bar of new session has zero volume.
            self._set_initialized(False)

        high = bar.high.as_double()
        low = bar.low.as_double()
        close = bar.close.as_double()
        volume = bar.volume.as_double()

        if volume <= 0:
            return

        typical = (high + low + close) / 3.0
        self._cum_pv += typical * volume
        self._cum_v += volume
        self._value = self._cum_pv / self._cum_v
        self._set_initialized(True)

    def _reset(self) -> None:
        self._current_session_id = None
        self._cum_pv = 0.0
        self._cum_v = 0.0
        self._value = None
