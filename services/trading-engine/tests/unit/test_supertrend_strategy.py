"""Unit tests for SupertrendStrategy.

We test the pure signal logic (``generate_signal`` against mocked
indicator state) and the bracket-parameter computation helper. Full
portfolio / order-factory interaction is exercised by the backtest smoke
test.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.supertrend import SupertrendConfig, SupertrendStrategy


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> SupertrendConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        period=10,
        multiplier=3.0,
        atr_period=14,
        sl_atr_mult=Decimal("1.5"),
        tp_atr_mult=Decimal("3.0"),
        risk_percent=Decimal("1.0"),
        pip_size=Decimal("0.01"),
        pip_value_per_lot=Decimal("1.0"),
    )
    defaults.update(overrides)
    return SupertrendConfig(**defaults)


def _make_strategy(**overrides) -> SupertrendStrategy:
    return SupertrendStrategy(_make_config(**overrides))


class TestConfigValidation:
    def test_slow_period_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(period=0)

    def test_multiplier_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(multiplier=0)

    def test_atr_multipliers_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(sl_atr_mult=Decimal("0"))
        with pytest.raises(ValueError):
            _make_config(tp_atr_mult=Decimal("-1"))


class TestSignalGeneration:
    """``generate_signal`` with mocked indicators."""

    def test_no_signal_when_uninitialised(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=False, trend=0)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_no_signal_on_first_initialised_bar(self) -> None:
        """First bar after warmup seeds prev_trend — no signal yet."""
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = None
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_buy_on_trend_flip_up(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = -1  # Was downtrend
        assert strategy.generate_signal(Mock()) == SignalType.BUY

    def test_sell_on_trend_flip_down(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=-1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = 1
        assert strategy.generate_signal(Mock()) == SignalType.SELL

    def test_no_signal_when_trend_unchanged(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = 1
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_prev_trend_updated_after_signal(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = -1
        strategy.generate_signal(Mock())
        assert strategy._prev_trend == 1


class TestBracketParams:
    """``_compute_bracket_params`` is pure — tested with Decimal inputs."""

    def test_long_bracket_sl_below_tp_above(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        # SL = 2400 - 1.5 * 10 = 2385; TP = 2400 + 3.0 * 10 = 2430
        assert sl == Decimal("2385")
        assert tp == Decimal("2430")
        assert qty > 0

    def test_short_bracket_sl_above_tp_below(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.SELL,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        assert sl == Decimal("2415")
        assert tp == Decimal("2370")
        assert qty > 0

    def test_qty_scales_with_balance(self) -> None:
        strategy = _make_strategy()
        _, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        qty_big, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("200000"),
        )
        qty_small, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("50000"),
        )
        assert qty_big > qty_small


# Registry assertion removed — test_strategy_registry.py's autouse
# `clear_registry` fixture wipes the registry before/after its own tests,
# which would leave our strategies unregistered by the time this test
# runs in the full suite. Import-time registration is exercised by the
# decorator itself: if the module imports, `@register_strategy` ran.
