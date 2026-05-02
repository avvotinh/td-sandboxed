"""Unit tests for Supertrend indicator."""

from __future__ import annotations

import pytest
from nautilus_trader.indicators.base import Indicator

from src.indicators.supertrend import Supertrend


pytestmark = pytest.mark.unit


class TestSupertrendConstruction:
    """Basic instantiation and lifecycle."""

    def test_is_indicator_subclass(self) -> None:
        st = Supertrend(period=10, multiplier=3.0)
        assert isinstance(st, Indicator)

    def test_initial_state_not_initialized(self) -> None:
        st = Supertrend(period=10, multiplier=3.0)
        assert st.initialized is False
        assert st.has_inputs is False

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            Supertrend(period=0, multiplier=3.0)

    def test_invalid_multiplier_raises(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            Supertrend(period=10, multiplier=0)
        with pytest.raises(ValueError, match="multiplier"):
            Supertrend(period=10, multiplier=-1.0)


class TestSupertrendWarmup:
    """Initialized only after ``period`` bars."""

    def test_not_initialized_before_period(self, make_bar) -> None:
        st = Supertrend(period=10, multiplier=3.0)
        for i in range(9):
            st.handle_bar(make_bar(open=2400, high=2401, low=2399, close=2400))
        assert st.initialized is False

    def test_initialized_at_period(self, make_bar) -> None:
        st = Supertrend(period=10, multiplier=3.0)
        for i in range(10):
            st.handle_bar(
                make_bar(
                    open=2400 + i * 0.1,
                    high=2400 + i * 0.1 + 1,
                    low=2400 + i * 0.1 - 1,
                    close=2400 + i * 0.1,
                )
            )
        assert st.initialized is True
        assert st.value is not None
        assert st.trend in (1, -1)


class TestSupertrendTrendFlip:
    """Trend signal flips on sustained price reversal."""

    def test_strong_uptrend_yields_positive_trend(
        self, make_bar
    ) -> None:
        st = Supertrend(period=10, multiplier=2.0)
        # Strong uptrend: close rises from 2400 to 2450 over 30 bars
        for i in range(30):
            close = 2400 + i * 2.0
            st.handle_bar(
                make_bar(open=close - 0.5, high=close + 1.0, low=close - 1.5, close=close)
            )
        assert st.initialized is True
        assert st.trend == 1
        assert st.value < 2400 + 29 * 2.0  # line is below price

    def test_strong_downtrend_yields_negative_trend(
        self, make_bar
    ) -> None:
        st = Supertrend(period=10, multiplier=2.0)
        for i in range(30):
            close = 2500 - i * 2.0
            st.handle_bar(
                make_bar(open=close + 0.5, high=close + 1.5, low=close - 1.0, close=close)
            )
        assert st.initialized is True
        assert st.trend == -1
        assert st.value > 2500 - 29 * 2.0  # line is above price

    def test_trend_flips_on_reversal(self, make_bar) -> None:
        st = Supertrend(period=10, multiplier=2.0)
        # Phase 1: strong uptrend → trend +1
        for i in range(20):
            close = 2400 + i * 3.0
            st.handle_bar(
                make_bar(open=close - 0.5, high=close + 1.5, low=close - 1.5, close=close)
            )
        trend_before = st.trend
        assert trend_before == 1

        # Phase 2: strong reversal down
        final_close = 2400 + 19 * 3.0
        for i in range(20):
            close = final_close - i * 5.0  # sharp decline
            st.handle_bar(
                make_bar(open=close + 0.5, high=close + 1.5, low=close - 1.5, close=close)
            )
        assert st.trend == -1, "trend must flip from +1 to -1 on strong reversal"


class TestSupertrendReset:
    """Reset clears all indicator state."""

    def test_reset_uninitializes(self, make_bar) -> None:
        st = Supertrend(period=10, multiplier=3.0)
        for i in range(20):
            st.handle_bar(make_bar(close=2400 + i, high=2401 + i, low=2399 + i))
        assert st.initialized is True

        st.reset()
        assert st.initialized is False
        assert st.has_inputs is False
        assert st.value is None

    def test_reset_then_feed_same_bars_same_value(self, make_bar) -> None:
        """Feed → reset → feed-same must produce identical indicator value."""
        bars = [
            make_bar(
                open=2400 + i * 0.5,
                high=2401 + i * 0.5,
                low=2399 + i * 0.5,
                close=2400 + i * 0.5 + 0.2,
            )
            for i in range(25)
        ]
        st1 = Supertrend(period=10, multiplier=3.0)
        for b in bars:
            st1.handle_bar(b)
        value_first = st1.value
        trend_first = st1.trend

        st1.reset()
        for b in bars:
            st1.handle_bar(b)
        assert st1.value == value_first
        assert st1.trend == trend_first


class TestSupertrendIdempotency:
    """Two independent instances with the same inputs produce the same output."""

    def test_two_instances_deterministic(self, make_bar) -> None:
        bars = [
            make_bar(close=2400 + i * 0.5, high=2401 + i * 0.5, low=2399 + i * 0.5)
            for i in range(20)
        ]
        st_a = Supertrend(period=10, multiplier=3.0)
        st_b = Supertrend(period=10, multiplier=3.0)
        for b in bars:
            st_a.handle_bar(b)
            st_b.handle_bar(b)
        assert st_a.value == st_b.value
        assert st_a.trend == st_b.trend
