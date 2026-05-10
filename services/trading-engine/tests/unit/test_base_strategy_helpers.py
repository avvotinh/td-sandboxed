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
from decimal import ROUND_HALF_UP, Decimal
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

    def test_tick_rounding_delegated_to_instrument(
        self, strategy: _ConcreteStrategy
    ) -> None:
        """Story 12.8: SL/TP prices must flow through ``instrument.make_price``
        so Nautilus rounds them to the venue's tick size before they hit
        the broker. Skipping make_price would let an off-tick price reach
        the order book — most venues reject those, some round silently
        (which can stop the SL outside its intended ATR band).

        Replace the identity make_price with a quantising one and assert
        the bracket args carry the rounded values, not the raw decimals.
        """
        # Quantise to the nearest 0.05 — chosen because it falsifies
        # both 2390.13 (→ 2390.15) and 2420.07 (→ 2420.05).
        tick = Decimal("0.05")
        def round_to_tick(v: Decimal) -> Decimal:
            return (Decimal(str(v)) / tick).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            ) * tick

        strategy._instrument.make_price = round_to_tick

        args = strategy._build_bracket_args(
            side=OrderSide.BUY,
            quantity=Decimal("1.0"),
            sl_price=Decimal("2390.13"),
            tp_price=Decimal("2420.07"),
        )
        assert args["sl_trigger_price"] == Decimal("2390.15")
        assert args["tp_price"] == Decimal("2420.05")


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


# ---------------------------------------------------------------------------
# Story 13.3 — _close_partial + _modify_sl helpers
# ---------------------------------------------------------------------------


def _stub_position(qty_value: float, side) -> Mock:
    """Build a position mock matching Nautilus Position.quantity/side surface."""
    qty = Mock()
    qty.as_double = Mock(return_value=qty_value)
    pos = Mock()
    pos.quantity = qty
    pos.side = side
    return pos


def _stub_size_increment(strategy: _ConcreteStrategy, lot_step: float) -> None:
    """Inject size_increment into the test instrument stub."""
    inc = Mock()
    inc.as_double = Mock(return_value=lot_step)
    strategy._instrument.size_increment = inc


class TestClosePartial:
    """_close_partial — reduce-only market with defensive cap."""

    def test_flat_returns_none(self, strategy: _ConcreteStrategy) -> None:
        strategy._submit_market_reduce_only_via_factory = Mock()
        result = strategy._close_partial(Decimal("0.5"))
        assert result is None
        strategy._submit_market_reduce_only_via_factory.assert_not_called()

    @pytest.mark.parametrize(
        "bad", [Decimal("0"), Decimal("1"), Decimal("-0.1"), Decimal("1.5")]
    )
    def test_fraction_must_be_strict_open_unit(
        self, strategy: _ConcreteStrategy, bad: Decimal
    ) -> None:
        with pytest.raises(ValueError, match="fraction"):
            strategy._close_partial(bad)

    def test_long_position_emits_reduce_only_sell(
        self, strategy: _ConcreteStrategy
    ) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy._position = _stub_position(1.0, PositionSide.LONG)
        _stub_size_increment(strategy, 0.01)
        sentinel = Mock(name="MarketOrder")
        strategy._submit_market_reduce_only_via_factory = Mock(
            return_value=sentinel
        )

        result = strategy._close_partial(Decimal("0.5"))

        assert result is sentinel
        strategy._submit_market_reduce_only_via_factory.assert_called_once()
        kwargs = strategy._submit_market_reduce_only_via_factory.call_args.kwargs
        assert kwargs["side"] == OrderSide.SELL
        # 1.0 * 0.5 = 0.5 ; cap = 1.0 − 0.01 = 0.99 ; min = 0.5
        assert kwargs["quantity"] == Decimal("0.5")

    def test_short_position_emits_reduce_only_buy(
        self, strategy: _ConcreteStrategy
    ) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy._position = _stub_position(2.0, PositionSide.SHORT)
        _stub_size_increment(strategy, 0.01)
        strategy._submit_market_reduce_only_via_factory = Mock()

        strategy._close_partial(Decimal("0.5"))

        kwargs = strategy._submit_market_reduce_only_via_factory.call_args.kwargs
        assert kwargs["side"] == OrderSide.BUY
        assert kwargs["quantity"] == Decimal("1.0")

    def test_defensive_cap_kicks_in_when_target_exceeds_qty_minus_step(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # qty=1.0, lot_step=0.01, fraction=0.999 → target=0.999, cap=0.99
        # → close exactly 0.99 (cap), leaving 0.01 still open.
        from nautilus_trader.model.enums import PositionSide

        strategy._position = _stub_position(1.0, PositionSide.LONG)
        _stub_size_increment(strategy, 0.01)
        strategy._submit_market_reduce_only_via_factory = Mock()

        strategy._close_partial(Decimal("0.999"))

        kwargs = strategy._submit_market_reduce_only_via_factory.call_args.kwargs
        assert kwargs["quantity"] == Decimal("0.99")

    def test_defensive_cap_short_side_symmetric(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Cap math is side-agnostic; this test pins that symmetry so a
        # later refactor can't break SHORT cap behaviour while LONG passes.
        from nautilus_trader.model.enums import PositionSide

        strategy._position = _stub_position(1.0, PositionSide.SHORT)
        _stub_size_increment(strategy, 0.01)
        strategy._submit_market_reduce_only_via_factory = Mock()

        strategy._close_partial(Decimal("0.999"))

        kwargs = strategy._submit_market_reduce_only_via_factory.call_args.kwargs
        assert kwargs["side"] == OrderSide.BUY
        assert kwargs["quantity"] == Decimal("0.99")

    def test_skips_when_position_too_small_for_cap(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # qty == lot_step: cap = 0, no room to partial-close without
        # over-closing. Expected: no-op + warning + return None.
        from nautilus_trader.model.enums import PositionSide

        strategy._position = _stub_position(0.01, PositionSide.LONG)
        _stub_size_increment(strategy, 0.01)
        strategy._submit_market_reduce_only_via_factory = Mock()

        result = strategy._close_partial(Decimal("0.5"))

        assert result is None
        strategy._submit_market_reduce_only_via_factory.assert_not_called()


class TestFindActiveSlOrder:
    """_find_active_sl_order — pure filter over cache.orders_open."""

    def test_returns_first_stop_market(
        self, strategy: _ConcreteStrategy
    ) -> None:
        sl_order = Mock(name="SL")
        sl_order.order_type = OrderType.STOP_MARKET
        tp_order = Mock(name="TP")
        tp_order.order_type = OrderType.LIMIT

        # Order matters: helper takes the first STOP_MARKET it sees.
        strategy._query_open_orders = Mock(return_value=[tp_order, sl_order])

        assert strategy._find_active_sl_order() is sl_order

    def test_returns_none_when_no_stop_market(
        self, strategy: _ConcreteStrategy
    ) -> None:
        # Bracket TP only present — must NOT pick up a LIMIT order.
        tp_order = Mock()
        tp_order.order_type = OrderType.LIMIT
        strategy._query_open_orders = Mock(return_value=[tp_order])

        assert strategy._find_active_sl_order() is None

    def test_returns_none_when_no_open_orders(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._query_open_orders = Mock(return_value=[])

        assert strategy._find_active_sl_order() is None


class TestModifySl:
    """_modify_sl — atomic via Strategy.modify_order public API."""

    def test_no_active_sl_returns_false(
        self, strategy: _ConcreteStrategy
    ) -> None:
        strategy._find_active_sl_order = Mock(return_value=None)
        strategy._modify_sl_order_via_strategy = Mock()

        result = strategy._modify_sl(Decimal("2400"))

        assert result is False
        strategy._modify_sl_order_via_strategy.assert_not_called()

    def test_active_sl_calls_modify(
        self, strategy: _ConcreteStrategy
    ) -> None:
        sl_order = Mock(name="SL")
        strategy._find_active_sl_order = Mock(return_value=sl_order)
        strategy._modify_sl_order_via_strategy = Mock()

        result = strategy._modify_sl(Decimal("2400"))

        assert result is True
        strategy._modify_sl_order_via_strategy.assert_called_once()
        call_args = strategy._modify_sl_order_via_strategy.call_args
        assert call_args.kwargs["sl_order"] is sl_order
        # make_price is identity in the fixture, so the trigger_price
        # arrives as the raw Decimal we passed in.
        assert call_args.kwargs["trigger_price"] == Decimal("2400")
