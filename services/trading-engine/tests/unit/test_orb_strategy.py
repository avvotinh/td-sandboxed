"""Unit tests for ORBStrategy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.orb import ORBConfig, ORBStrategy


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> ORBConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        session_open_hour=8,
        session_open_minute=0,
        session_close_hour=16,
        session_close_minute=30,
        session_tz="Europe/London",
        opening_range_minutes=30,
        atr_period=14,
    )
    defaults.update(overrides)
    return ORBConfig(**defaults)


def _make_strategy(**overrides) -> ORBStrategy:
    return ORBStrategy(_make_config(**overrides))


def _mock_bar(ts: datetime, high: float = 2410, low: float = 2390, close: float = 2400):
    bar = Mock()
    bar.ts_init = int(ts.timestamp() * 1_000_000_000)
    bar.high = Mock()
    bar.high.as_double = Mock(return_value=high)
    bar.low = Mock()
    bar.low.as_double = Mock(return_value=low)
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


class TestConfigValidation:
    def test_hour_bounds(self) -> None:
        with pytest.raises(ValueError):
            _make_config(session_open_hour=25)
        with pytest.raises(ValueError):
            _make_config(session_close_hour=-1)

    def test_opening_range_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(opening_range_minutes=0)


class TestSessionBoundary:
    def test_no_signal_before_atr_init(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=False, value=0)
        bar = _mock_bar(datetime(2026, 4, 17, 10, 0, tzinfo=UTC))
        assert strategy.generate_signal(bar) == SignalType.NONE

    def test_outside_session_no_signal_when_flat(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        # 18:00 UTC = 19:00 BST (London) — past 16:30 close
        bar = _mock_bar(datetime(2026, 4, 17, 18, 0, tzinfo=UTC))
        assert strategy.generate_signal(bar) == SignalType.NONE

    def test_outside_session_forces_close_when_long(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        bar = _mock_bar(datetime(2026, 4, 17, 18, 0, tzinfo=UTC))
        assert strategy.generate_signal(bar) == SignalType.CLOSE


class TestOpeningRangeAccumulation:
    def test_or_accumulated_during_first_30min(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        # Bar 1 at 08:00 BST = 07:00 UTC
        ts1 = datetime(2026, 4, 17, 7, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts1, high=2410, low=2390))
        # Bar 2 at 08:15 BST — still in OR window
        ts2 = datetime(2026, 4, 17, 7, 15, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts2, high=2415, low=2395))
        assert strategy._or_high == 2415
        assert strategy._or_low == 2390
        assert strategy._or_complete is False

    def test_or_complete_after_window(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        ts1 = datetime(2026, 4, 17, 7, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts1, high=2410, low=2390))
        # 31 minutes later — OR window closed
        ts2 = datetime(2026, 4, 17, 7, 31, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts2, high=2412, low=2388))
        assert strategy._or_complete is True


class TestBreakoutSignal:
    def _primed_strategy(self) -> ORBStrategy:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        # Prime OR with 2390-2410 range.
        ts1 = datetime(2026, 4, 17, 7, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts1, high=2410, low=2390))
        ts2 = datetime(2026, 4, 17, 7, 31, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts2, high=2409, low=2391, close=2400))
        return strategy

    def test_buy_on_breakout_above_or_high(self) -> None:
        strategy = self._primed_strategy()
        ts = datetime(2026, 4, 17, 8, 0, tzinfo=UTC)  # 09:00 BST
        signal = strategy.generate_signal(_mock_bar(ts, high=2415, low=2395, close=2412))
        assert signal == SignalType.BUY
        assert strategy._entered_this_session is True

    def test_sell_on_breakout_below_or_low(self) -> None:
        strategy = self._primed_strategy()
        ts = datetime(2026, 4, 17, 8, 0, tzinfo=UTC)
        signal = strategy.generate_signal(_mock_bar(ts, high=2395, low=2385, close=2388))
        assert signal == SignalType.SELL

    def test_no_re_entry_after_entered(self) -> None:
        strategy = self._primed_strategy()
        ts = datetime(2026, 4, 17, 8, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts, close=2412))  # BUY
        ts2 = datetime(2026, 4, 17, 8, 5, tzinfo=UTC)
        signal = strategy.generate_signal(_mock_bar(ts2, close=2420))
        assert signal == SignalType.NONE

    def test_no_signal_inside_or_range(self) -> None:
        strategy = self._primed_strategy()
        ts = datetime(2026, 4, 17, 8, 0, tzinfo=UTC)
        signal = strategy.generate_signal(_mock_bar(ts, high=2408, low=2392, close=2400))
        assert signal == SignalType.NONE


class TestSessionReset:
    def test_new_session_resets_or_state(self) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        # Day 1 session
        ts_d1 = datetime(2026, 4, 17, 7, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts_d1, high=2410, low=2390))
        assert strategy._or_high == 2410
        # Day 2 session — OR resets
        ts_d2 = datetime(2026, 4, 18, 7, 0, tzinfo=UTC)
        strategy.generate_signal(_mock_bar(ts_d2, high=2500, low=2480))
        assert strategy._or_high == 2500
        assert strategy._or_low == 2480


# Registry verified by successful import (decorator registered at load).
