"""Unit tests for RealizedVolatility indicator."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.indicators.realized_vol import RealizedVolatility

pytestmark = pytest.mark.unit


class TestConstruction:
    def test_is_indicator_subclass(self) -> None:
        rv = RealizedVolatility(window=20, annualisation_factor=1.0)
        assert isinstance(rv, Indicator)

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window"):
            RealizedVolatility(window=1, annualisation_factor=1.0)
        with pytest.raises(ValueError, match="window"):
            RealizedVolatility(window=0, annualisation_factor=1.0)

    def test_invalid_annualisation_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="annualisation_factor"):
            RealizedVolatility(window=20, annualisation_factor=0.0)
        with pytest.raises(ValueError, match="annualisation_factor"):
            RealizedVolatility(window=20, annualisation_factor=-2.0)

    def test_initial_state(self) -> None:
        rv = RealizedVolatility(window=20)
        assert rv.initialized is False
        assert rv.value is None


class TestWarmup:
    def test_not_initialized_during_warmup(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        rv = RealizedVolatility(window=10)
        for i in range(5):
            rv.handle_bar(make_bar(close=2400.0 + i))
        assert rv.initialized is False
        assert rv.value is None

    def test_initialized_after_window_returns(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        # Need window+1 bars to have window log returns.
        rv = RealizedVolatility(window=10)
        for i in range(11):
            rv.handle_bar(make_bar(close=2400.0 + i))
        assert rv.initialized is True
        assert rv.value is not None
        assert rv.value > 0.0


class TestVolatilityValue:
    def test_zero_volatility_on_constant_close(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        rv = RealizedVolatility(window=10)
        for _ in range(15):
            rv.handle_bar(make_bar(close=2400.0))
        assert rv.value == pytest.approx(0.0)

    def test_volatility_grows_with_dispersion(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        rv = RealizedVolatility(window=20)
        # Stable phase
        for _ in range(25):
            rv.handle_bar(make_bar(close=2400.0))
        stable = rv.value
        # Volatile phase
        for i in range(25):
            close = 2400.0 + (i % 2) * 50.0
            rv.handle_bar(make_bar(close=close))
        volatile = rv.value
        assert volatile > stable

    def test_known_log_return_stdev(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        """Closes that double then halve produce log returns ±ln(2)."""
        rv = RealizedVolatility(window=4, annualisation_factor=1.0)
        closes = [100.0, 200.0, 100.0, 200.0, 100.0]
        for c in closes:
            rv.handle_bar(make_bar(close=c))
        # log returns: ln(2), -ln(2), ln(2), -ln(2)
        # mean = 0, population variance = ln(2)^2, std = ln(2) ≈ 0.6931
        assert rv.value == pytest.approx(math.log(2.0), rel=1e-6)


class TestAnnualisation:
    def test_annualisation_factor_scales_value(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        raw = RealizedVolatility(window=4, annualisation_factor=1.0)
        scaled = RealizedVolatility(
            window=4, annualisation_factor=math.sqrt(252.0 * 288.0)
        )
        # Same input series.
        closes = [100.0, 105.0, 95.0, 110.0, 90.0]
        for c in closes:
            raw.handle_bar(make_bar(close=c))
            scaled.handle_bar(make_bar(close=c))
        assert raw.value is not None
        assert scaled.value is not None
        assert scaled.value == pytest.approx(
            raw.value * math.sqrt(252.0 * 288.0), rel=1e-6
        )


class TestRollingWindow:
    def test_window_drops_oldest_returns(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        rv = RealizedVolatility(window=5, annualisation_factor=1.0)
        # Phase 1: high vol, fill window plus extra.
        for i in range(10):
            close = 100.0 * (1.5 if i % 2 else 1.0)
            rv.handle_bar(make_bar(close=close))
        high = rv.value
        # Phase 2: long stretch of constant closes evicts high-vol returns.
        for _ in range(20):
            rv.handle_bar(make_bar(close=100.0))
        assert rv.value < high
        assert rv.value == pytest.approx(0.0, abs=1e-9)
