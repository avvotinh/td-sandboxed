"""Unit tests for new BaseStrategy helpers (Story 8.0).

Tests the new helper methods on BaseStrategy added for Epic 8:
- _calculate_atr_stop  (delegates to ATRStopMixin)
- _in_session          (delegates to SessionFilterMixin)
- _build_bracket_args  (pure: computes order_factory.bracket kwargs)
- _submit_bracket_order (composes bracket + submit_order_list)

We deliberately do NOT instantiate Nautilus's TradingNode — instead the
helpers are tested via lightweight mocks of order_factory and
submit_order_list. This mirrors the testing pattern already used in
test_base_strategy.py for signal execution.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide, OrderType
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig


pytestmark = pytest.mark.unit


class _ConcreteStrategy(BaseStrategy):
    """Minimal concrete strategy for testing helpers."""

    def generate_signal(self, bar) -> SignalType:
        return SignalType.NONE


@pytest.fixture
def config() -> BaseStrategyConfig:
    return BaseStrategyConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        account_id="ftmo-main",
    )


@pytest.fixture
def strategy(config: BaseStrategyConfig) -> _ConcreteStrategy:
    s = _ConcreteStrategy(config)
    # Lightweight instrument with passthrough conversions.
    instrument = Mock()
    instrument.make_qty = lambda v: v
    instrument.make_price = lambda v: v
    s._instrument = instrument
    return s


class TestCalculateAtrStopHelper:
    """BaseStrategy._calculate_atr_stop delegates to ATRStopMixin."""

    def test_long_stop(self, strategy: _ConcreteStrategy) -> None:
        sl = strategy._calculate_atr_stop(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            multiplier=Decimal("1.5"),
        )
        assert sl == Decimal("2385")

    def test_short_stop(self, strategy: _ConcreteStrategy) -> None:
        sl = strategy._calculate_atr_stop(
            side=OrderSide.SELL,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            multiplier=Decimal("1.5"),
        )
        assert sl == Decimal("2415")


class TestInSessionHelper:
    """BaseStrategy._in_session delegates to SessionFilterMixin."""

    def test_in_session_london(self, strategy: _ConcreteStrategy) -> None:
        ts = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert strategy._in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )

    def test_outside_session(self, strategy: _ConcreteStrategy) -> None:
        ts = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
        assert not strategy._in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )


class TestBuildBracketArgs:
    """Pure: _build_bracket_args computes correct kwargs for OrderFactory.bracket."""

    def test_long_args(self, strategy: _ConcreteStrategy) -> None:
        args = strategy._build_bracket_args(
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            sl_price=Decimal("2390"),
            tp_price=Decimal("2420"),
        )
        assert args["order_side"] == OrderSide.BUY
        assert args["instrument_id"] == strategy.config.instrument_id
        assert args["sl_trigger_price"] == Decimal("2390")
        assert args["tp_price"] == Decimal("2420")
        assert args["entry_order_type"] == OrderType.MARKET
        assert args["sl_order_type"] == OrderType.STOP_MARKET
        assert args["tp_order_type"] == OrderType.LIMIT

    def test_short_args(self, strategy: _ConcreteStrategy) -> None:
        args = strategy._build_bracket_args(
            side=OrderSide.SELL,
            quantity=Decimal("1.0"),
            sl_price=Decimal("2410"),
            tp_price=Decimal("2380"),
        )
        assert args["order_side"] == OrderSide.SELL
        assert args["sl_trigger_price"] == Decimal("2410")
        assert args["tp_price"] == Decimal("2380")

    def test_validates_long_sl_below_entry_using_tp_above(
        self, strategy: _ConcreteStrategy
    ) -> None:
        """For LONG: SL must be below entry-implied (i.e. SL < TP). Wrong order raises."""
        with pytest.raises(ValueError, match="sl_price"):
            strategy._build_bracket_args(
                side=OrderSide.BUY,
                quantity=Decimal("1.0"),
                sl_price=Decimal("2420"),  # SL above TP — wrong for long
                tp_price=Decimal("2400"),
            )

    def test_validates_short_sl_above_entry(self, strategy: _ConcreteStrategy) -> None:
        with pytest.raises(ValueError, match="sl_price"):
            strategy._build_bracket_args(
                side=OrderSide.SELL,
                quantity=Decimal("1.0"),
                sl_price=Decimal("2380"),  # SL below TP — wrong for short
                tp_price=Decimal("2400"),
            )

    def test_zero_quantity_raises(self, strategy: _ConcreteStrategy) -> None:
        with pytest.raises(ValueError, match="quantity"):
            strategy._build_bracket_args(
                side=OrderSide.BUY,
                quantity=Decimal("0"),
                sl_price=Decimal("2390"),
                tp_price=Decimal("2420"),
            )


class TestSubmitBracketOrder:
    """End-to-end: _submit_bracket_order calls the factory seam then returns it.

    We patch ``_submit_bracket_via_factory`` (a regular Python method on
    ``BaseStrategy``) rather than Nautilus's Cython ``order_factory`` /
    ``submit_order_list`` which are read-only at runtime.
    """

    def test_submit_bracket_calls_factory_seam(
        self, strategy: _ConcreteStrategy
    ) -> None:
        mock_order_list = Mock(name="OrderList")
        strategy._submit_bracket_via_factory = Mock(return_value=mock_order_list)

        result = strategy._submit_bracket_order(
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            sl_price=Decimal("2390"),
            tp_price=Decimal("2420"),
        )

        strategy._submit_bracket_via_factory.assert_called_once()
        args_passed = strategy._submit_bracket_via_factory.call_args.args[0]
        assert args_passed["order_side"] == OrderSide.BUY
        assert args_passed["sl_trigger_price"] == Decimal("2390")
        assert args_passed["tp_price"] == Decimal("2420")
        assert result is mock_order_list

    def test_submit_bracket_skips_when_not_flat(
        self, strategy: _ConcreteStrategy
    ) -> None:
        from nautilus_trader.model.enums import PositionSide

        mock_position = Mock()
        mock_position.side = PositionSide.LONG
        strategy._position = mock_position

        strategy._submit_bracket_via_factory = Mock()

        result = strategy._submit_bracket_order(
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            sl_price=Decimal("2390"),
            tp_price=Decimal("2420"),
        )

        strategy._submit_bracket_via_factory.assert_not_called()
        assert result is None

    def test_submit_bracket_skips_when_qty_zero(
        self, strategy: _ConcreteStrategy
    ) -> None:
        """Sizer returning 0 must translate to a graceful skip — not a raise."""
        strategy._submit_bracket_via_factory = Mock()

        result = strategy._submit_bracket_order(
            side=OrderSide.BUY,
            quantity=Decimal("0"),
            sl_price=Decimal("2390"),
            tp_price=Decimal("2420"),
        )

        strategy._submit_bracket_via_factory.assert_not_called()
        assert result is None

    def test_submit_bracket_skips_when_qty_negative(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._submit_bracket_via_factory = Mock()

        result = strategy._submit_bracket_order(
            side=OrderSide.BUY,
            quantity=Decimal("-0.5"),
            sl_price=Decimal("2390"),
            tp_price=Decimal("2420"),
        )

        strategy._submit_bracket_via_factory.assert_not_called()
        assert result is None
