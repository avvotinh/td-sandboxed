"""Unit tests for Nautilus → internal Order translation (story 10.5c)."""
from __future__ import annotations

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import (
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.orders import LimitOrder, MarketOrder

from src.adapters.zmq_models import OrderSide as InternalOrderSide
from src.engine.clients.order_translator import (
    UnsupportedOrderError,
    to_internal_order,
)


VENUE = Venue("MT5")
INSTRUMENT_ID = InstrumentId(Symbol("XAUUSD"), VENUE)
TRADER_ID = TraderId("TRADER-001")
STRATEGY_ID = StrategyId("S-test")


def _market_order(*, side: OrderSide, quantity: float = 0.5) -> MarketOrder:
    return MarketOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=INSTRUMENT_ID,
        client_order_id=ClientOrderId(f"O-{quantity}-{side.name}"),
        order_side=side,
        quantity=Quantity.from_str(f"{quantity}"),
        init_id=UUID4(),
        ts_init=0,
        time_in_force=TimeInForce.GTC,
    )


class TestHappyPath:
    def test_buy_market_order_translated(self) -> None:
        nautilus = _market_order(side=OrderSide.BUY, quantity=0.5)
        internal = to_internal_order(nautilus, account_id="ftmo-001")

        assert internal.account_id == "ftmo-001"
        assert internal.action is InternalOrderSide.BUY
        assert internal.symbol == "XAUUSD"
        assert internal.volume == 0.5
        assert internal.order_id == "O-0.5-BUY"
        assert internal.price > 0  # Internal Order requires positive price

    def test_sell_market_order_translated(self) -> None:
        nautilus = _market_order(side=OrderSide.SELL, quantity=0.25)
        internal = to_internal_order(nautilus, account_id="the5ers-002")

        assert internal.account_id == "the5ers-002"
        assert internal.action is InternalOrderSide.SELL
        assert internal.volume == 0.25


class TestUnsupportedOrders:
    def test_limit_order_rejected_with_clear_message(self) -> None:
        limit = LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=INSTRUMENT_ID,
            client_order_id=ClientOrderId("O-LIM-1"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str("0.5"),
            price=__import__(
                "nautilus_trader.model.objects", fromlist=["Price"]
            ).Price.from_str("1850.00"),
            init_id=UUID4(),
            ts_init=0,
            time_in_force=TimeInForce.GTC,
        )
        with pytest.raises(UnsupportedOrderError, match="MARKET"):
            to_internal_order(limit, account_id="acct-1")


class TestPriceFallback:
    """MARKET orders carry no price; translator falls back to a positive sentinel."""

    def test_market_order_gets_positive_default_price(self) -> None:
        nautilus = _market_order(side=OrderSide.BUY)
        internal = to_internal_order(nautilus, account_id="acct-1")
        assert internal.price > 0  # Pydantic validator requires this


class TestRoundTripUsableByAdapter:
    """The translated Order must satisfy ValidatedZmqAdapter's contract.

    Min sanity: account_id + symbol + volume + order_id are non-empty,
    volume > 0 (so MaxPositionSizeRule has something to check against),
    and the model is a fully-validated Pydantic instance (raises on
    construction otherwise).
    """

    def test_translated_order_passes_pydantic_validation(self) -> None:
        nautilus = _market_order(side=OrderSide.BUY, quantity=1.0)
        internal = to_internal_order(nautilus, account_id="acct-1")

        # Round-trip via dict/restore proves all required fields are set.
        restored = type(internal).model_validate(internal.model_dump())
        assert restored.volume == 1.0
        assert restored.action is InternalOrderSide.BUY
