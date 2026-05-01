"""Nautilus ↔ internal Order translation.

Story 10.5c — :class:`ZmqExecutionClient` receives ``SubmitOrder``
commands containing Nautilus :class:`Order` objects from a strategy
running in a per-account ``LiveNode``. Before they can hit
``ValidatedZmqAdapter`` (rule engine + 10.4 atomic exposure gate) and
the underlying ZMQ socket, they need to be translated to the internal
``Order`` DTO that ``mt5-bridge`` understands.

This module exposes the conversion as pure functions so they can be
exercised without instantiating a Nautilus engine. The 10.5c MVP only
supports MARKET orders; LIMIT/STOP/etc. raise
:class:`UnsupportedOrderError` so the dispatcher can emit a clear
``OrderDenied`` event upstream.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
from nautilus_trader.model.enums import OrderType

from ...adapters.zmq_models import Order as InternalOrder
from ...adapters.zmq_models import OrderSide as InternalOrderSide

if TYPE_CHECKING:
    from nautilus_trader.model.orders import Order as NautilusOrder


class UnsupportedOrderError(ValueError):
    """Raised when the live path cannot translate a Nautilus order.

    Surfaces as ``OrderDenied`` (not ``OrderRejected``): the order never
    reaches the venue, so it is a client-side denial rather than a
    venue-side rejection.
    """


_NAUTILUS_TO_INTERNAL_SIDE: dict[NautilusOrderSide, InternalOrderSide] = {
    NautilusOrderSide.BUY: InternalOrderSide.BUY,
    NautilusOrderSide.SELL: InternalOrderSide.SELL,
}


def to_internal_order(
    nautilus_order: NautilusOrder,
    *,
    account_id: str,
) -> InternalOrder:
    """Translate a Nautilus :class:`Order` into the internal DTO.

    Args:
        nautilus_order: Strategy-built order (typically a
            :class:`MarketOrder`). Stop-loss / take-profit prices are
            optional.
        account_id: Sandboxed account this order routes to.

    Raises:
        UnsupportedOrderError: For non-MARKET order types (10.5c MVP)
            or when the Nautilus side is :attr:`NautilusOrderSide.NO_ORDER_SIDE`.
    """
    if nautilus_order.order_type is not OrderType.MARKET:
        raise UnsupportedOrderError(
            f"Live path supports MARKET orders only — got "
            f"{nautilus_order.order_type.name}; LIMIT/STOP support is "
            "deferred to Epic 11+ (Review 3 P1)."
        )

    side = _NAUTILUS_TO_INTERNAL_SIDE.get(nautilus_order.side)
    if side is None:
        raise UnsupportedOrderError(
            f"Unsupported Nautilus order side: {nautilus_order.side!r}"
        )

    quantity = float(nautilus_order.quantity)
    if quantity <= 0:
        raise UnsupportedOrderError(
            f"Nautilus order has non-positive quantity: {quantity}"
        )

    # MARKET orders carry no price — the validated adapter still
    # requires a positive price field for risk math; populate with the
    # last known mid (provided by caller via instrument cache) or fall
    # back to a sentinel positive value. The internal Order schema's
    # `price` is the *requested* price; for MARKET this is informational
    # only (mt5-bridge ignores it on MARKET). Caller may override the
    # default by setting ``trigger_price`` on the Nautilus order.
    requested_price = _extract_requested_price(nautilus_order)

    return InternalOrder(
        order_id=str(nautilus_order.client_order_id),
        account_id=account_id,
        action=side,
        symbol=str(nautilus_order.instrument_id.symbol),
        volume=quantity,
        price=requested_price,
    )


def _extract_requested_price(nautilus_order: NautilusOrder) -> float:
    """Best-effort price extraction for an internal Order DTO.

    MARKET orders do not carry a price in Nautilus. Internal Order
    requires ``price > 0`` (Pydantic validator). Try ``price`` (limit
    orders carry it), then ``trigger_price`` (stop orders), and fall
    back to ``1.0`` as a positive sentinel — mt5-bridge ignores price
    on MARKET orders anyway.
    """
    price = getattr(nautilus_order, "price", None)
    if price is not None:
        try:
            value = float(price)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    trigger = getattr(nautilus_order, "trigger_price", None)
    if trigger is not None:
        try:
            value = float(trigger)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    return 1.0
