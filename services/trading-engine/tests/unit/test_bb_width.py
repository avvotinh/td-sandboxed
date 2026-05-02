"""Unit tests for BollingerBandWidth indicator."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from nautilus_trader.indicators.base import Indicator
from nautilus_trader.model.data import Bar

from src.indicators.bb_width import BollingerBandWidth

pytestmark = pytest.mark.unit


class TestConstruction:
    def test_is_indicator_subclass(self) -> None:
        bbw = BollingerBandWidth(period=20, num_std=2.0, baseline_window=100)
        assert isinstance(bbw, Indicator)

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            BollingerBandWidth(period=0, num_std=2.0, baseline_window=100)
        with pytest.raises(ValueError, match="period"):
            BollingerBandWidth(period=-1, num_std=2.0, baseline_window=100)

    def test_invalid_num_std_raises(self) -> None:
        with pytest.raises(ValueError, match="num_std"):
            BollingerBandWidth(period=20, num_std=0.0, baseline_window=100)
        with pytest.raises(ValueError, match="num_std"):
            BollingerBandWidth(period=20, num_std=-2.0, baseline_window=100)

    def test_invalid_baseline_window_raises(self) -> None:
        with pytest.raises(ValueError, match="baseline_window"):
            BollingerBandWidth(period=20, num_std=2.0, baseline_window=0)

    def test_initial_state(self) -> None:
        bbw = BollingerBandWidth(period=20, num_std=2.0, baseline_window=100)
        assert bbw.initialized is False
        assert bbw.value is None
        assert bbw.percentile is None


class TestWarmup:
    def test_not_initialized_during_warmup(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=20, num_std=2.0, baseline_window=100)
        for i in range(10):
            bbw.handle_bar(make_bar(close=2400.0 + i))
        assert bbw.initialized is False
        assert bbw.value is None

    def test_initialized_after_period_bars(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=20, num_std=2.0, baseline_window=100)
        for i in range(20):
            bbw.handle_bar(make_bar(close=2400.0 + i))
        assert bbw.initialized is True
        assert bbw.value is not None
        assert bbw.value > 0
        # Percentile is defined as soon as baseline has at least one sample.
        assert bbw.percentile is not None


class TestRawWidth:
    def test_zero_width_on_constant_close(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=20)
        for _ in range(15):
            bbw.handle_bar(make_bar(close=2400.0))
        assert bbw.value == pytest.approx(0.0)

    def test_width_increases_with_dispersion(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=20)
        for _ in range(15):
            bbw.handle_bar(make_bar(close=2400.0))
        stable_w = bbw.value
        for i in range(15):
            close = 2400.0 + (i % 2) * 50.0
            bbw.handle_bar(make_bar(close=close))
        assert bbw.value > stable_w


class TestPercentile:
    def test_percentile_in_unit_interval(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=20)
        for i in range(40):
            bbw.handle_bar(make_bar(close=2400.0 + i * 0.5))
        assert 0.0 <= bbw.percentile <= 1.0

    def test_high_percentile_when_width_grows(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=30)
        # Fill baseline with low-width bars.
        for _ in range(35):
            bbw.handle_bar(make_bar(close=2400.0))
        # All baseline samples equal → mid-tie rank.
        assert bbw.percentile == pytest.approx(0.5)
        # Add high-width bars; current width should rise to near max.
        for i in range(15):
            close = 2400.0 + (i % 2) * 100.0
            bbw.handle_bar(make_bar(close=close))
        assert bbw.percentile > 0.7

    def test_low_percentile_when_width_shrinks(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=30)
        # Fill baseline with volatile bars to establish high baseline.
        for i in range(40):
            close = 2400.0 + (i % 2) * 50.0
            bbw.handle_bar(make_bar(close=close))
        # Then push many constant bars — width drops to near zero.
        for _ in range(30):
            bbw.handle_bar(make_bar(close=2400.0))
        assert bbw.percentile < 0.4

    def test_baseline_window_is_rolling(
        self, make_bar: Callable[..., Bar]
    ) -> None:
        """Old samples must be evicted once baseline_window is exceeded."""
        bbw = BollingerBandWidth(period=10, num_std=2.0, baseline_window=10)
        # Phase 1: high-volatility seeds baseline.
        for i in range(20):
            close = 2400.0 + (i % 2) * 50.0
            bbw.handle_bar(make_bar(close=close))
        # Phase 2: 30 const bars far exceeds baseline_window, fully evicting
        # the high-vol samples. With all-zero baseline + zero current width,
        # mid-tie semantics give percentile == 0.5.
        for _ in range(30):
            bbw.handle_bar(make_bar(close=2400.0))
        assert bbw.percentile == pytest.approx(0.5)


