"""Smoke tests for indicator re-exports from ``src.indicators``.

Verifies:
- ATR, RSI, Bollinger, Donchian re-export Nautilus classes
- Each is a subclass of Nautilus ``Indicator``
- Basic handle_bar + .value / .upper / .lower APIs reachable
- Custom indicators (Supertrend, ADX, SessionVWAP) are also exported
"""

from __future__ import annotations

import pytest
from nautilus_trader.indicators.base import Indicator

from src.indicators import (
    ADX,
    ATR,
    RSI,
    Bollinger,
    Donchian,
    SessionVWAP,
    Supertrend,
)


pytestmark = pytest.mark.unit


class TestReexportsSubclassIndicator:
    """All exported indicators must be Nautilus Indicator subclasses."""

    @pytest.mark.parametrize(
        "cls",
        [ATR, RSI, Bollinger, Donchian, Supertrend, ADX, SessionVWAP],
    )
    def test_is_indicator_subclass(self, cls: type) -> None:
        assert issubclass(cls, Indicator), (
            f"{cls.__name__} must subclass nautilus_trader.indicators.base.Indicator"
        )


class TestNautilusReexports:
    """Nautilus-backed indicators accept the expected ctor args + expose API."""

    def test_atr_period_and_value(self, make_bar) -> None:
        atr = ATR(period=14)
        assert atr.period == 14
        assert atr.initialized is False
        # Feed 14 bars to initialize
        for i in range(20):
            atr.handle_bar(make_bar(open=2400 + i, close=2400 + i + 0.5, high=2401 + i, low=2399 + i))
        assert atr.initialized is True
        assert atr.value > 0

    def test_rsi_period_and_value(self, make_bar) -> None:
        rsi = RSI(period=14)
        assert rsi.period == 14
        # Feed 20 bars with uptrend
        for i in range(20):
            rsi.handle_bar(make_bar(close=2400 + i))
        assert rsi.initialized is True
        # Nautilus RSI uses 0–1 scale, not 0–100. Uptrend → > 0.5.
        assert rsi.value > 0.5

    def test_bollinger_upper_middle_lower(self, make_bar) -> None:
        bb = Bollinger(period=20, k=2.0)
        for i in range(25):
            bb.handle_bar(make_bar(close=2400 + (i % 5)))
        assert bb.initialized is True
        assert bb.lower < bb.middle < bb.upper

    def test_donchian_upper_middle_lower(self, make_bar) -> None:
        dc = Donchian(period=20)
        closes = [2400 + i for i in range(25)]
        for i, c in enumerate(closes):
            dc.handle_bar(make_bar(open=c, high=c + 1, low=c - 1, close=c))
        assert dc.initialized is True
        # Upper should be near recent max high, lower near recent min low
        assert dc.upper >= dc.middle >= dc.lower


class TestResetClearsState:
    """All indicators must reset cleanly."""

    def test_atr_reset(self, make_bar) -> None:
        atr = ATR(period=14)
        for i in range(20):
            atr.handle_bar(make_bar(close=2400 + i, high=2401 + i, low=2399 + i))
        assert atr.initialized is True
        atr.reset()
        assert atr.initialized is False
