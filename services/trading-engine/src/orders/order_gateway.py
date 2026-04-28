"""Order gateway protocol — design-only abstraction for the broker boundary.

Epic 9 P0.12. The engine currently sends orders through ``ZmqAdapter`` to
the MT5 bridge. Adding futures support later (e.g. Rithmic, NinjaTrader)
means swapping the transport without touching the rule engine, the
validator, or strategy code. This protocol pins the contract every
gateway must satisfy so callers can depend on the shape rather than the
concrete ``ZmqAdapter`` class.

No new gateway is implemented here — the protocol is purely a typing
boundary. ``ZmqAdapter`` already exposes every method below and so
satisfies it structurally; ``isinstance`` works at runtime via
``@runtime_checkable``.

See ``docs/epic-9-context.md`` (Architectural Decision 6) for the broader
"design door open, do not implement" rationale.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..adapters.zmq_models import Order, OrderResult


@runtime_checkable
class OrderGateway(Protocol):
    """Broker-side connection that ferries :class:`Order` to/from the venue.

    Implementations own the wire format and the connection lifecycle. The
    rule engine and the validator depend only on the methods declared
    here; substituting a different broker (futures, FIX, REST) is a
    matter of providing a new class that satisfies this protocol.

    A few notes on the shape:

    * ``send_order`` is fire-and-forget — useful for low-latency strategies
      where the strategy doesn't need to await fill status synchronously.
    * ``send_order_and_wait`` returns the venue's ack/fill payload and is
      the path the validator uses for trades that must update P&L.
    * ``get_pending_order_count`` is read by the graceful-shutdown service
      to decide whether to drain or fail open.

    Note: ``@runtime_checkable`` only checks method *presence*, not
    signatures. A future implementation with mismatched parameter types
    will pass ``isinstance`` but fail at call time. Run mypy on new
    gateways to catch signature drift early.
    """

    @property
    def is_connected(self) -> bool:
        """Whether the gateway has an active session with the venue."""
        ...

    async def connect(self) -> None:
        """Open the broker session. Idempotent on already-open gateways."""
        ...

    async def disconnect(self) -> None:
        """Close the broker session and release sockets/handles."""
        ...

    async def send_order(self, order: Order) -> None:
        """Submit ``order`` to the venue without waiting for the result.

        Raises:
            RuntimeError: If the gateway is not connected.
        """
        ...

    async def send_order_and_wait(
        self,
        order: Order,
        timeout: float = 5.0,
    ) -> OrderResult:
        """Submit ``order`` and await the venue's :class:`OrderResult`.

        Raises:
            asyncio.TimeoutError: If no result arrives within ``timeout``.
            RuntimeError: If the gateway is not connected.
        """
        ...

    def get_pending_order_count(self) -> int:
        """Return the number of orders awaiting venue acknowledgement."""
        ...


__all__ = ["OrderGateway"]
