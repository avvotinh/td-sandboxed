"""Unit tests for DonchianBreakoutStrategy.

Signal logic tested with mocked Donchian + ATR indicators. The critical
invariant: breakouts compare close to the **prior** bar's band, not the
current bar's — otherwise the current bar always sits inside its own
channel and no signal ever fires.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.donchian_breakout import (
    DonchianBreakoutConfig,
    DonchianBreakoutStrategy,
)


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> DonchianBreakoutConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        channel_period=20,
        atr_period=14,
        sl_atr_mult=Decimal("2.0"),
        tp_atr_mult=Decimal("4.0"),
        risk_percent=Decimal("1.0"),
        pip_size=Decimal("0.01"),
        pip_value_per_lot=Decimal("1.0"),
    )
    defaults.update(overrides)
    return DonchianBreakoutConfig(**defaults)


def _make_strategy() -> DonchianBreakoutStrategy:
    return DonchianBreakoutStrategy(_make_config())


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


class TestConfigValidation:
    def test_channel_period_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(channel_period=0)

    def test_atr_period_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(atr_period=-1)


class TestSignalGeneration:
    def test_no_signal_until_initialised(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=False, upper=0, lower=0)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_no_signal_on_first_bar_seeds_prior(self) -> None:
        """First initialised bar just caches prior band — no signal yet."""
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = None
        strategy._prev_lower = None
        assert strategy.generate_signal(_mock_bar(2405)) == SignalType.NONE

    def test_breakout_up_triggers_buy(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2418.0
        strategy._prev_lower = 2380.0
        # Close 2420 > prior upper 2418 → breakout long
        assert strategy.generate_signal(_mock_bar(2420)) == SignalType.BUY

    def test_breakout_down_triggers_sell(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2378.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        # Close 2378 < prior lower 2380 → breakout short
        assert strategy.generate_signal(_mock_bar(2378)) == SignalType.SELL

    def test_inside_channel_no_signal(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_equal_to_prior_upper_does_not_trigger(self) -> None:
        """Strict > comparison — close == prior upper is inside, not out."""
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2420)) == SignalType.NONE

    def test_uses_prior_band_not_current(self) -> None:
        """Regression: if we use current upper, close can never exceed it."""
        strategy = _make_strategy()
        # Simulate: the current bar's close pushed the Donchian upper out.
        # Current upper = 2430 (includes the current bar). Prior = 2420.
        # Close = 2425. Should still signal BUY (above prior 2420).
        strategy._donchian = Mock(initialized=True, upper=2430.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY


class TestBracketParams:
    def test_long_bracket(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2420"),
            atr_value=Decimal("5"),
            account_balance=Decimal("100000"),
        )
        # sl = 2420 - 2.0 * 5 = 2410; tp = 2420 + 4.0 * 5 = 2440
        assert sl == Decimal("2410")
        assert tp == Decimal("2440")
        assert qty > 0

    def test_short_bracket(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.SELL,
            entry_price=Decimal("2378"),
            atr_value=Decimal("5"),
            account_balance=Decimal("100000"),
        )
        assert sl == Decimal("2388")
        assert tp == Decimal("2358")
        assert qty > 0


class TestAtrZeroGuard:
    """A flat-bar (H=L=C) collapses ATR to zero; the bracket helper must
    short-circuit rather than crash the bar-processing loop. Mirrors the
    Supertrend / Bollinger / RSI guard added under story 12.8.
    """

    @pytest.mark.parametrize("bad_atr", [0.0, None, -5.0, float("nan")])
    def test_unsafe_atr_skips_bracket_submission(self, bad_atr) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=bad_atr)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_positive_atr_still_submits(self) -> None:
        """Sanity: the guard does not over-trigger on healthy ATR."""
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_called_once()


# Registry verified by successful import (decorator registered at load).
