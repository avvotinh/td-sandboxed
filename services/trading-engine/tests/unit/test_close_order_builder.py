"""Unit tests for :func:`build_close_order` (story 10.7)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.adapters.zmq_models import MT5Position, OrderSide
from src.orders.close_order_builder import build_close_order


def _position(
    *,
    side: str = "BUY",
    volume: Decimal = Decimal("0.5"),
    symbol: str = "XAUUSD",
    current_price: Decimal = Decimal("1850.0"),
    entry_price: Decimal = Decimal("1845.0"),
    ticket: int = 12345,
) -> MT5Position:
    return MT5Position(
        ticket=ticket,
        symbol=symbol,
        side=side,
        volume=volume,
        entry_price=entry_price,
        entry_time="2026-05-01T10:00:00Z",
        current_price=current_price,
        profit=Decimal("0"),
        swap=Decimal("0"),
        commission=Decimal("0"),
    )


class TestSideFlip:
    def test_buy_position_closes_with_sell(self) -> None:
        order = build_close_order(_position(side="BUY"), account_id="acct-1")
        assert order.action is OrderSide.SELL

    def test_sell_position_closes_with_buy(self) -> None:
        order = build_close_order(_position(side="SELL"), account_id="acct-1")
        assert order.action is OrderSide.BUY

    def test_lowercase_side_normalised(self) -> None:
        order = build_close_order(_position(side="buy"), account_id="acct-1")
        assert order.action is OrderSide.SELL

    def test_unknown_side_raises(self) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            build_close_order(_position(side="HOLD"), account_id="acct-1")


class TestPreservesIdentity:
    def test_volume_matches_position(self) -> None:
        order = build_close_order(
            _position(volume=Decimal("1.25")), account_id="acct-1"
        )
        assert order.volume == 1.25

    def test_symbol_matches_position(self) -> None:
        order = build_close_order(
            _position(symbol="EURUSD"), account_id="acct-1"
        )
        assert order.symbol == "EURUSD"

    def test_account_id_threads_through(self) -> None:
        order = build_close_order(_position(), account_id="ftmo-gold-001")
        assert order.account_id == "ftmo-gold-001"


class TestVolumeGuards:
    def test_zero_volume_rejected(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            build_close_order(
                _position(volume=Decimal("0")), account_id="acct-1"
            )

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            build_close_order(
                _position(volume=Decimal("-0.1")), account_id="acct-1"
            )


class TestPriceFallback:
    def test_uses_current_price_when_set(self) -> None:
        order = build_close_order(
            _position(current_price=Decimal("1900.0")), account_id="acct-1"
        )
        assert order.price == 1900.0

    def test_falls_back_to_entry_price_when_current_zero(self) -> None:
        order = build_close_order(
            _position(
                current_price=Decimal("0"),
                entry_price=Decimal("1850.0"),
            ),
            account_id="acct-1",
        )
        assert order.price == 1850.0

    def test_final_fallback_keeps_price_positive(self) -> None:
        order = build_close_order(
            _position(
                current_price=Decimal("0"),
                entry_price=Decimal("0"),
            ),
            account_id="acct-1",
        )
        # Pydantic Order validator requires price > 0; sentinel 1.0 satisfies it
        assert order.price > 0


class TestOrderId:
    def test_default_order_id_uses_flat_prefix(self) -> None:
        order = build_close_order(_position(), account_id="acct-1")
        assert order.order_id.startswith("flat-")
        assert len(order.order_id) > len("flat-")  # has the uuid suffix

    def test_explicit_order_id_overrides(self) -> None:
        order = build_close_order(
            _position(),
            account_id="acct-1",
            order_id="emergency-stop-corr-id-001",
        )
        assert order.order_id == "emergency-stop-corr-id-001"


class TestRoundTripPydantic:
    """The built Order must satisfy ValidatedZmqAdapter / mt5-bridge schema."""

    def test_serialises_via_pydantic(self) -> None:
        order = build_close_order(_position(), account_id="acct-1")
        restored = type(order).model_validate(order.model_dump())
        assert restored.action is order.action
        assert restored.volume == order.volume
        assert restored.symbol == order.symbol
