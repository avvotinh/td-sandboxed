"""Unit tests for ADX (Average Directional Index) indicator."""

from __future__ import annotations

import pytest
from nautilus_trader.indicators.base import Indicator

from src.indicators.adx import ADX


pytestmark = pytest.mark.unit


class TestADXConstruction:
    def test_is_indicator_subclass(self) -> None:
        adx = ADX(period=14)
        assert isinstance(adx, Indicator)

    def test_initial_state_not_initialized(self) -> None:
        adx = ADX(period=14)
        assert adx.initialized is False

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="period"):
            ADX(period=0)
        with pytest.raises(ValueError, match="period"):
            ADX(period=-5)


class TestADXWarmup:
    """ADX needs 2*period bars (period for DI smoothing, period for DX smoothing)."""

    def test_not_initialized_before_2x_period(self, make_bar) -> None:
        adx = ADX(period=14)
        # Feed 20 bars — not enough for full ADX smoothing
        for i in range(20):
            adx.handle_bar(
                make_bar(open=2400, high=2401, low=2399, close=2400)
            )
        assert adx.initialized is False

    def test_initialized_at_2x_period(self, make_bar) -> None:
        adx = ADX(period=14)
        # Feed 2*period bars with trending data
        for i in range(28):
            close = 2400 + i * 0.5
            adx.handle_bar(
                make_bar(
                    open=close - 0.2,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                )
            )
        assert adx.initialized is True
        assert adx.value is not None
        assert 0 <= adx.value <= 100


class TestADXTrendDetection:
    """Core contract: high ADX on trending data, low ADX on choppy data."""

    def test_strong_trend_above_25(self, make_bar) -> None:
        adx = ADX(period=14)
        # Very strong uptrend — consecutive higher highs & higher lows
        for i in range(50):
            close = 2400 + i * 3.0
            adx.handle_bar(
                make_bar(
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                )
            )
        assert adx.initialized is True
        assert adx.value > 25, f"Strong trend must yield ADX > 25, got {adx.value}"

    def test_choppy_market_below_25(self, make_bar) -> None:
        adx = ADX(period=14)
        # Choppy / ranging — oscillating closes
        for i in range(50):
            # sawtooth pattern
            close = 2400 + (i % 4) * 0.5 - 1.0
            adx.handle_bar(
                make_bar(
                    open=close,
                    high=close + 0.3,
                    low=close - 0.3,
                    close=close,
                )
            )
        assert adx.initialized is True
        assert adx.value < 25, f"Choppy market must yield ADX < 25, got {adx.value}"


class TestADXDirectionalIndicators:
    """+DI and -DI should reflect directional dominance."""

    def test_uptrend_plus_di_above_minus_di(self, make_bar) -> None:
        adx = ADX(period=14)
        for i in range(40):
            close = 2400 + i * 1.5
            adx.handle_bar(
                make_bar(
                    open=close - 0.2,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                )
            )
        assert adx.plus_di > adx.minus_di

    def test_downtrend_minus_di_above_plus_di(self, make_bar) -> None:
        adx = ADX(period=14)
        for i in range(40):
            close = 2500 - i * 1.5
            adx.handle_bar(
                make_bar(
                    open=close + 0.2,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                )
            )
        assert adx.minus_di > adx.plus_di


class TestADXReset:
    def test_reset_clears_state(self, make_bar) -> None:
        adx = ADX(period=14)
        for i in range(30):
            adx.handle_bar(
                make_bar(close=2400 + i, high=2401 + i, low=2399 + i)
            )
        assert adx.initialized is True
        adx.reset()
        assert adx.initialized is False
        assert adx.value is None

    def test_reset_then_feed_same_bars_same_value(self, make_bar) -> None:
        bars = [
            make_bar(
                open=2400 + i * 0.5,
                high=2401 + i * 0.5,
                low=2399 + i * 0.5,
                close=2400 + i * 0.5 + 0.3,
            )
            for i in range(40)
        ]
        adx = ADX(period=14)
        for b in bars:
            adx.handle_bar(b)
        val_first = adx.value
        plus_di_first = adx.plus_di
        minus_di_first = adx.minus_di

        adx.reset()
        for b in bars:
            adx.handle_bar(b)
        assert adx.value == pytest.approx(val_first)
        assert adx.plus_di == pytest.approx(plus_di_first)
        assert adx.minus_di == pytest.approx(minus_di_first)
