"""Unit tests for EMASlope indicator."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.indicators.ema_slope import EMASlope

pytestmark = pytest.mark.unit


class TestConstruction:
    def test_is_indicator_subclass(self) -> None:
        es = EMASlope(period=20, lookback=10)
        assert isinstance(es, Indicator)

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            EMASlope(period=0, lookback=10)
        with pytest.raises(ValueError, match="period"):
            EMASlope(period=-1, lookback=10)

    def test_invalid_lookback_raises(self) -> None:
        with pytest.raises(ValueError, match="lookback"):
            EMASlope(period=20, lookback=0)
        with pytest.raises(ValueError, match="lookback"):
            EMASlope(period=20, lookback=-5)

    def test_initial_state(self) -> None:
        es = EMASlope(period=20, lookback=10)
        assert es.initialized is False
        assert es.value is None


class TestWarmup:
    def test_not_initialized_during_warmup(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        es = EMASlope(period=10, lookback=5)
        for i in range(8):
            es.handle_bar(make_bar(close=2400.0 + i))
        assert es.initialized is False
        assert es.value is None

    def test_initialized_when_enough_bars(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        # Need period bars for EMA seed + lookback bars for slope.
        es = EMASlope(period=10, lookback=5)
        for i in range(20):
            es.handle_bar(make_bar(close=2400.0 + i))
        assert es.initialized is True
        assert es.value is not None


class TestSlopeDirection:
    def test_positive_slope_on_uptrend(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        es = EMASlope(period=10, lookback=5)
        for i in range(40):
            es.handle_bar(make_bar(close=2400.0 + i * 1.0))
        assert es.value is not None
        assert es.value > 0

    def test_negative_slope_on_downtrend(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        es = EMASlope(period=10, lookback=5)
        for i in range(40):
            es.handle_bar(make_bar(close=2400.0 - i * 1.0))
        assert es.value is not None
        assert es.value < 0

    def test_near_zero_slope_on_flat(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        es = EMASlope(period=10, lookback=5)
        for _ in range(40):
            es.handle_bar(make_bar(close=2400.0))
        assert es.value is not None
        assert es.value == pytest.approx(0.0, abs=1e-9)


class TestSlopeMagnitude:
    def test_steeper_trend_yields_larger_slope(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        slow = EMASlope(period=10, lookback=5)
        fast = EMASlope(period=10, lookback=5)
        for i in range(40):
            slow.handle_bar(make_bar(close=2400.0 + i * 0.1))  # slow rise
            fast.handle_bar(make_bar(close=2400.0 + i * 2.0))  # fast rise
        assert slow.value is not None and fast.value is not None
        assert fast.value > slow.value


class TestRollingHistory:
    def test_lookback_uses_correct_past_ema(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        """Slope numerator must reference the EMA from exactly ``lookback``
        bars ago, not the EMA from the start of the stream."""
        es = EMASlope(period=5, lookback=3)
        # Long history of one regime then a sharp transition.
        for _ in range(20):
            es.handle_bar(make_bar(close=2400.0))
        es.handle_bar(make_bar(close=2410.0))
        es.handle_bar(make_bar(close=2420.0))
        es.handle_bar(make_bar(close=2430.0))
        # After 3 bars of new regime + lookback=3, slope reflects the new
        # regime only, not the long flat preamble.
        assert es.value is not None
        assert es.value > 0
