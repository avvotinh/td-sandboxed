"""Opening Range Breakout (ORB) strategy.

Intraday breakout: track the high/low of the first ``opening_range_minutes``
bars of a configured trading session. After the opening range closes:

- BUY when a bar closes above the OR-high (one entry per session)
- SELL when a bar closes below the OR-low (one entry per session)

All positions are force-closed at session end (or on first bar after).
Uses :class:`SessionFilterMixin` for DST-safe session windowing.

Designed for intraday FTMO strategies — London 08:00-16:30 or New York
08:30-15:00 local time. Not for 24h markets (crypto).
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

from nautilus_trader.indicators.volatility import AverageTrueRange
from nautilus_trader.model.data import Bar

from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.bracket_strategy import (
    BracketStrategyConfig,
    BracketStrategyMixin,
)
from src.strategies.mixins.atr_stop_mixin import ATRStopMixin
from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.mixins.session_filter_mixin import SessionFilterMixin
from src.strategies.registry import register_strategy
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


class ORBConfig(BracketStrategyConfig, frozen=True, kw_only=True):
    session_open_hour: int = 8  # e.g. London open 08:00
    session_open_minute: int = 0
    session_close_hour: int = 16  # e.g. London close 16:30
    session_close_minute: int = 30
    session_tz: str = "Europe/London"
    opening_range_minutes: int = 30

    # ORB-specific ATR defaults (tighter than trend-follower bracket)
    sl_atr_mult: Decimal = Decimal("1.0")
    tp_atr_mult: Decimal = Decimal("2.0")

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 <= self.session_open_hour <= 23:
            raise ValueError("session_open_hour must be in 0..23")
        if not 0 <= self.session_close_hour <= 23:
            raise ValueError("session_close_hour must be in 0..23")
        if not 0 <= self.session_open_minute <= 59:
            raise ValueError("session_open_minute must be in 0..59")
        if not 0 <= self.session_close_minute <= 59:
            raise ValueError("session_close_minute must be in 0..59")
        if self.opening_range_minutes <= 0:
            raise ValueError("opening_range_minutes must be positive")
        # ORB is documented as intraday-only; an open >= close minute-of-
        # day silently creates an overnight window that downstream
        # SessionFilterMixin would happily process. Wall-clock integers
        # only — DST handling is deferred to SessionFilterMixin at run
        # time (config-time has no tz context).
        open_mod = self.session_open_hour * 60 + self.session_open_minute
        close_mod = self.session_close_hour * 60 + self.session_close_minute
        if open_mod >= close_mod:
            raise ValueError(
                "session_open must be earlier than session_close (intraday-only); "
                f"got open={self.session_open_hour:02d}:{self.session_open_minute:02d} "
                f"close={self.session_close_hour:02d}:{self.session_close_minute:02d}"
            )
        # Opening-range cannot exceed total session length, otherwise the
        # OR phase swallows the entire trading day and no breakout fires.
        session_minutes = close_mod - open_mod
        if self.opening_range_minutes >= session_minutes:
            raise ValueError(
                f"opening_range_minutes ({self.opening_range_minutes}) must be "
                f"< session length ({session_minutes} minutes)"
            )


# Phase 1: ORB opts out of regime routing (regimes=[]). Phase 2 will
# wire it to HIGH_VOLATILITY once a volatility-targeted strategy clears
# validation.
@register_strategy("orb", regimes=[])
class ORBStrategy(
    BaseStrategy,
    ATRStopMixin,
    RiskSizedMixin,
    SessionFilterMixin,
    BracketStrategyMixin,
):
    """Opening Range Breakout — one entry per session, force-close at end."""

    def __init__(self, config: ORBConfig) -> None:
        super().__init__(config)
        self._atr = AverageTrueRange(config.atr_period)
        self.set_position_sizer(
            RiskBasedPositionSizer(
                RiskBasedSizerConfig(risk_percent=config.risk_percent)
            )
        )
        # Per-session state
        self._current_session_id: str | None = None
        self._or_high: float | None = None
        self._or_low: float | None = None
        self._or_open_ts: datetime | None = None
        self._or_complete: bool = False
        self._entered_this_session: bool = False

    def on_start(self) -> None:
        super().on_start()
        self.register_indicator_for_bars(self.config.bar_type, self._atr)

    def on_reset(self) -> None:
        self._atr.reset()
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        self._or_high = None
        self._or_low = None
        self._or_open_ts = None
        self._or_complete = False
        self._entered_this_session = False

    def _bar_timestamp(self, bar: Bar) -> datetime:
        return datetime.fromtimestamp(bar.ts_init // 1_000_000_000, tz=UTC)

    def generate_signal(self, bar: Bar) -> SignalType:
        if not self._atr.initialized:
            return SignalType.NONE

        ts = self._bar_timestamp(bar)
        session_open = time(
            self.config.session_open_hour, self.config.session_open_minute
        )
        session_close = time(
            self.config.session_close_hour, self.config.session_close_minute
        )

        in_session = self.in_session(
            ts, session_start=session_open, session_end=session_close,
            tz=self.config.session_tz,
        )

        # Out-of-session: force-flatten then return.
        if not in_session:
            if not self.is_flat:
                return SignalType.CLOSE
            # Also reset session state so we're fresh for next session.
            if self._current_session_id is not None:
                self._reset_session_state()
                self._current_session_id = None
            return SignalType.NONE

        # In-session: detect new day.
        session_id = self.session_id(ts, tz=self.config.session_tz)
        if session_id != self._current_session_id:
            self._current_session_id = session_id
            self._reset_session_state()
            self._or_open_ts = ts

        # Opening-range accumulation — half-open window
        # [session_open, session_open + opening_range_minutes). A bar at
        # exactly elapsed == opening_range_minutes is past the window: do
        # NOT contribute its H/L; mark OR complete and let the breakout
        # logic below evaluate it normally.
        if not self._or_complete and self._or_open_ts is not None:
            elapsed_minutes = (ts - self._or_open_ts).total_seconds() / 60
            if elapsed_minutes >= self.config.opening_range_minutes:
                self._or_complete = True
                # Fall through to breakout evaluation.
            else:
                high = bar.high.as_double()
                low = bar.low.as_double()
                self._or_high = (
                    high if self._or_high is None else max(self._or_high, high)
                )
                self._or_low = (
                    low if self._or_low is None else min(self._or_low, low)
                )
                # No signals while the OR is still forming.
                return SignalType.NONE

        # OR complete — watch for breakout. One entry per session.
        if self._entered_this_session or not self.is_flat:
            return SignalType.NONE

        close = bar.close.as_double()
        if self._or_high is not None and close > self._or_high:
            self._entered_this_session = True
            return SignalType.BUY
        if self._or_low is not None and close < self._or_low:
            self._entered_this_session = True
            return SignalType.SELL
        return SignalType.NONE

    def _execute_signal(self, signal: SignalType) -> None:
        if signal == SignalType.CLOSE:
            self._close_position()
            return
        atr_value = Decimal(str(self._atr.value))
        self._submit_bracket_for_entry(signal, atr_value)
