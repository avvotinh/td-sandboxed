"""Build a flat-position close :class:`Order` from an :class:`MT5Position`.

Story 10.7 — emergency-stop kill-switch closes every open position by
sending an opposite-side market order with the same volume to
``mt5-bridge``. Extracted as a pure function so the orchestrator
(:class:`EmergencyStopHandler`) and tests share the exact same
contract.

Lock-step with how the position was opened: a BUY position closes via
SELL with identical volume; SHORT closes via BUY. ``current_price`` is
copied into the close order's ``price`` field as the "requested"
market reference — mt5-bridge ignores the price on MARKET orders, but
the internal :class:`Order` schema requires ``price > 0``.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from ..adapters.zmq_models import Order, OrderSide

if TYPE_CHECKING:
    from ..adapters.zmq_models import MT5Position


_OPPOSITE_SIDE: dict[str, OrderSide] = {
    "BUY": OrderSide.SELL,
    "SELL": OrderSide.BUY,
}


def build_close_order(
    position: "MT5Position",
    *,
    account_id: str,
    order_id: str | None = None,
) -> Order:
    """Construct an opposite-side market order that flats ``position``.

    Args:
        position: The MT5 position to close.
        account_id: Account scope. Threaded into the order so the
            validated adapter routes the close to the correct account.
        order_id: Optional caller-provided identifier (e.g. for
            correlation against the emergency-stop audit row). Auto-
            generates a ``flat-{uuid8}`` id when omitted.

    Raises:
        ValueError: If the position's side is neither BUY nor SELL, or
            volume is non-positive (a position with zero volume cannot
            be a real position; refuse to send an invalid order).
    """
    side = _OPPOSITE_SIDE.get(position.side.upper())
    if side is None:
        raise ValueError(
            f"Cannot build close order: unsupported position side "
            f"{position.side!r} (expected 'BUY' or 'SELL')"
        )

    volume = float(position.volume)
    if volume <= 0:
        raise ValueError(
            f"Cannot build close order: position volume must be > 0, got {volume}"
        )

    # mt5-bridge ignores price on MARKET orders, but our internal
    # Order schema enforces ``price > 0``. Use current_price when
    # available; fall back to entry_price; final fallback to 1.0
    # which the bridge silently ignores.
    price = float(position.current_price) or float(position.entry_price) or 1.0

    return Order(
        order_id=order_id or f"flat-{uuid.uuid4().hex[:8]}",
        account_id=account_id,
        action=side,
        symbol=position.symbol,
        volume=volume,
        price=price,
    )
