"""Unit tests for RSIMeanReversionStrategy."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.rsi_mean_reversion import (
    RSIMeanReversionConfig,
    RSIMeanReversionStrategy,
)


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> RSIMeanReversionConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        rsi_period=14,
        oversold=0.3,
        overbought=0.7,
        exit_neutral=0.5,
        atr_period=14,
    )
    defaults.update(overrides)
    return RSIMeanReversionConfig(**defaults)


def _make_strategy() -> RSIMeanReversionStrategy:
    return RSIMeanReversionStrategy(_make_config())


def _mock_bar(close: float = 2400.0) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


class TestConfigValidation:
    def test_thresholds_ordered(self) -> None:
        with pytest.raises(ValueError):
            _make_config(oversold=0.5, overbought=0.4)
        with pytest.raises(ValueError):
            _make_config(exit_neutral=0.2, oversold=0.3)

    def test_rsi_period_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(rsi_period=0)


class TestSignalGeneration:
    def test_no_signal_before_init(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=False, value=0.5)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(_mock_bar()) == SignalType.NONE

    def test_first_initialised_bar_seeds_prev(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.25)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = None
        assert strategy.generate_signal(_mock_bar()) == SignalType.NONE

    def test_oversold_cross_up_triggers_buy(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.35)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.25  # prev ≤ oversold, now > → cross-up
        assert strategy.generate_signal(_mock_bar()) == SignalType.BUY

    def test_overbought_cross_down_triggers_sell(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.65)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.75
        assert strategy.generate_signal(_mock_bar()) == SignalType.SELL

    def test_inside_neutral_zone_no_signal(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.5)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.45
        assert strategy.generate_signal(_mock_bar()) == SignalType.NONE

    def test_long_closed_on_neutral_cross_up(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.55)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.40
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        assert strategy.generate_signal(_mock_bar()) == SignalType.CLOSE

    def test_short_closed_on_neutral_cross_down(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.45)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.60
        position = Mock()
        position.side = PositionSide.SHORT
        strategy._position = position
        assert strategy.generate_signal(_mock_bar()) == SignalType.CLOSE

    def test_no_new_entry_while_position_open(self) -> None:
        strategy = _make_strategy()
        strategy._rsi = Mock(initialized=True, value=0.35)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_rsi = 0.25  # Would be BUY signal if flat
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        # Already long & RSI still below neutral — no new signal.
        assert strategy.generate_signal(_mock_bar()) == SignalType.NONE


class TestRegistry:
    def test_registered(self) -> None:
        from src.strategies.registry import StrategyRegistry
        assert StrategyRegistry.is_registered("rsi_mean_reversion")
