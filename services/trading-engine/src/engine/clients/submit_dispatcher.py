"""Submit-order dispatch pipeline for the live execution path.

Story 10.5c — extracts the validate→send→emit logic out of
:class:`ZmqExecutionClient` so we can test it without standing up a
Nautilus engine. The dispatcher takes:

- a Nautilus :class:`Order` from the strategy,
- a :class:`ValidatedZmqAdapter` (rule engine + 10.4 atomic gate),
- an :class:`OrderEventEmitter` (Protocol satisfied by Nautilus's
  ``LiveExecutionClient`` *and* by test fakes),

and translates the outcome into the appropriate Nautilus event
(``order_submitted`` + ``order_filled`` / ``order_rejected`` /
``order_denied``).

Event-mapping contract:

- ``OrderBlockedError`` (rule engine or atomic-gate rejection)
  → ``OrderDenied`` (client-side denial; the order never reached MT5).
- ``UnsupportedOrderError`` (e.g. LIMIT order in the 10.5c MVP)
  → ``OrderDenied``.
- ``asyncio.TimeoutError`` (ZMQ round-trip exceeded)
  → ``OrderRejected``.
- Any other ``Exception`` from the adapter
  → ``OrderRejected`` with ``send failed: <repr>`` reason.
- ``OrderResult.is_filled``
  → ``OrderSubmitted`` then ``OrderFilled``.
- ``OrderResult.is_rejected``
  → ``OrderSubmitted`` then ``OrderRejected``.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ...adapters.zmq_models import OrderResult, OrderSide as InternalOrderSide
from ...execution.exceptions import OrderBlockedError
from .order_translator import UnsupportedOrderError, to_internal_order

if TYPE_CHECKING:
    from nautilus_trader.model.enums import OrderSide as NautilusOrderSide
    from nautilus_trader.model.identifiers import (
        ClientOrderId,
        InstrumentId,
        StrategyId,
    )
    from nautilus_trader.model.orders import Order as NautilusOrder

    from ...execution.validated_adapter import ValidatedZmqAdapter

logger = logging.getLogger(__name__)


@runtime_checkable
class OrderEventEmitter(Protocol):
    """Subset of Nautilus :class:`~nautilus_trader.execution.client.ExecutionClient`
    we depend on. Implemented by both the live execution client and by
    test fakes.
    """

    def generate_order_submitted(
        self,
        strategy_id: "StrategyId",
        instrument_id: "InstrumentId",
        client_order_id: "ClientOrderId",
        ts_event: int,
    ) -> None: ...

    def generate_order_filled(
        self,
        strategy_id: "StrategyId",
        instrument_id: "InstrumentId",
        client_order_id: "ClientOrderId",
        venue_order_id: object,
        venue_position_id: object | None,
        trade_id: object,
        order_side: "NautilusOrderSide",
        order_type: object,
        last_qty: object,
        last_px: object,
        quote_currency: object,
        commission: object,
        liquidity_side: object,
        ts_event: int,
        info: object | None = None,
    ) -> None: ...

    def generate_order_rejected(
        self,
        strategy_id: "StrategyId",
        instrument_id: "InstrumentId",
        client_order_id: "ClientOrderId",
        reason: str,
        ts_event: int,
        due_post_only: bool = False,
    ) -> None: ...

    def generate_order_denied(
        self,
        strategy_id: "StrategyId",
        instrument_id: "InstrumentId",
        client_order_id: "ClientOrderId",
        reason: str,
        ts_event: int,
    ) -> None: ...


@runtime_checkable
class TimestampClock(Protocol):
    """Subset of :class:`~nautilus_trader.common.component.LiveClock`
    used by the dispatcher — only ``timestamp_ns()``.
    """

    def timestamp_ns(self) -> int: ...


async def dispatch_submit_order(
    nautilus_order: "NautilusOrder",
    *,
    account_id: str,
    validated_adapter: "ValidatedZmqAdapter",
    emitter: OrderEventEmitter,
    clock: TimestampClock,
) -> None:
    """Validate, send, and translate a single SubmitOrder command.

    The function never raises — every error path lands in an emitted
    Nautilus event so the engine state stays consistent.
    """
    strategy_id = nautilus_order.strategy_id
    instrument_id = nautilus_order.instrument_id
    client_order_id = nautilus_order.client_order_id

    # 1. Translate to internal Order DTO. Translation failures are
    # client-side denials.
    try:
        internal_order = to_internal_order(
            nautilus_order, account_id=account_id
        )
    except UnsupportedOrderError as exc:
        ts = clock.timestamp_ns()
        emitter.generate_order_denied(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            reason=str(exc),
            ts_event=ts,
        )
        return

    # 2. Validate and send.
    try:
        result: OrderResult = await validated_adapter.send_order_and_wait(
            internal_order
        )
    except OrderBlockedError as exc:
        ts = clock.timestamp_ns()
        emitter.generate_order_denied(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            reason=exc.reason or "Blocked by compliance rules",
            ts_event=ts,
        )
        return
    except asyncio.TimeoutError:
        ts = clock.timestamp_ns()
        emitter.generate_order_rejected(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            reason="MT5 send timeout",
            ts_event=ts,
        )
        return
    except Exception as exc:  # broad on purpose — engine must not crash
        logger.exception(
            "ZmqExecutionClient send failed for %s",
            client_order_id,
        )
        ts = clock.timestamp_ns()
        emitter.generate_order_rejected(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            reason=f"send failed: {exc!r}",
            ts_event=ts,
        )
        return

    # 3. Translate the OrderResult into Nautilus events.
    ts = clock.timestamp_ns()
    emitter.generate_order_submitted(
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        client_order_id=client_order_id,
        ts_event=ts,
    )

    if result.is_filled:
        if result.fill_price is None:
            # Defensive: a FILLED status without a fill price would
            # cause us to emit a zero-price ``OrderFilled``, corrupting
            # downstream P&L bookkeeping. Treat it as a rejection so
            # the strategy can react cleanly.
            emitter.generate_order_rejected(
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                client_order_id=client_order_id,
                reason="MT5 returned FILLED with no fill price",
                ts_event=ts,
            )
        else:
            _emit_fill(
                emitter=emitter,
                nautilus_order=nautilus_order,
                internal_side=internal_order.action,
                result=result,
                ts_event=ts,
            )
    else:
        emitter.generate_order_rejected(
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            client_order_id=client_order_id,
            reason=result.error or f"MT5 status {result.status.value}",
            ts_event=ts,
        )


def _emit_fill(
    *,
    emitter: OrderEventEmitter,
    nautilus_order: "NautilusOrder",
    internal_side: InternalOrderSide,
    result: OrderResult,
    ts_event: int,
) -> None:
    """Emit an ``OrderFilled`` event from an MT5 ``OrderResult``.

    Several Nautilus fill fields require richer venue context (currency,
    commission, liquidity side). Story 10.5c populates them with safe
    defaults; story 10.5d/e will plumb venue-specific values through.
    """
    # Lazy imports — these pull in compiled Nautilus modules; keeping
    # them out of the dispatcher's import path lets tests stub the
    # emitter without forcing every test to depend on Nautilus model
    # objects.
    from nautilus_trader.model.enums import (
        LiquiditySide,
        OrderSide as NautilusOrderSide,
    )
    from nautilus_trader.model.identifiers import TradeId, VenueOrderId
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.model.currencies import USD

    if result.fill_price is None:
        # Caller already guards this in dispatch_submit_order; defensive
        # second check so _emit_fill can never produce a zero-price event.
        raise ValueError(
            "_emit_fill requires a non-None fill_price — caller must "
            "redirect FILLED results without a fill price to "
            "OrderRejected"
        )
    fill_price = result.fill_price
    nautilus_side = (
        NautilusOrderSide.BUY
        if internal_side is InternalOrderSide.BUY
        else NautilusOrderSide.SELL
    )

    venue_order_id = VenueOrderId(result.order_id)
    trade_id = TradeId(uuid.uuid4().hex[:16])

    emitter.generate_order_filled(
        strategy_id=nautilus_order.strategy_id,
        instrument_id=nautilus_order.instrument_id,
        client_order_id=nautilus_order.client_order_id,
        venue_order_id=venue_order_id,
        venue_position_id=None,
        trade_id=trade_id,
        order_side=nautilus_side,
        order_type=nautilus_order.order_type,
        last_qty=Quantity.from_str(str(nautilus_order.quantity)),
        last_px=Price.from_str(f"{fill_price:.5f}"),
        quote_currency=USD,
        commission=Money(0, USD),
        liquidity_side=LiquiditySide.NO_LIQUIDITY_SIDE,
        ts_event=ts_event,
    )
