"""Nautilus :class:`LiveExecutionClient` routed through ValidatedZmqAdapter.

Story 10.5c — strategies running on a per-account ``LiveNode`` submit
orders via Nautilus's standard execution path; this client is the
adapter that translates each ``SubmitOrder`` command into a call into
:class:`~src.execution.validated_adapter.ValidatedZmqAdapter` (rule
engine + 10.4 atomic exposure gate) and emits the appropriate Nautilus
event from the ``OrderResult`` returned by the bridge.

The dispatch pipeline lives in :mod:`submit_dispatcher` so it can be
unit-tested without standing up a Nautilus engine. This class is a
thin Nautilus-side shim that fulfils the ``LiveExecutionClient``
contract and forwards every accepted command to the dispatcher.

Story 10.5d/e will:

- mount this client onto the per-account ``LiveNode`` built by
  :class:`~src.engine.live_orchestrator.LiveOrchestrator`,
- attach the per-account ``PropFirmComplianceActor`` alongside it,
- wire the health surface so order submissions update
  ``last_order_sent_at``.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nautilus_trader.execution.messages import (
    BatchCancelOrders,
    CancelAllOrders,
    CancelOrder,
    ModifyOrder,
    SubmitOrder,
    SubmitOrderList,
)
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.enums import AccountType, OmsType
from nautilus_trader.model.identifiers import ClientId, Venue

from .submit_dispatcher import dispatch_submit_order

if TYPE_CHECKING:
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.common.config import NautilusConfig
    from nautilus_trader.common.providers import InstrumentProvider
    from nautilus_trader.model.objects import Currency

    from ...execution.validated_adapter import ValidatedZmqAdapter


class ZmqExecutionClient(LiveExecutionClient):
    """Live execution client wrapping :class:`ValidatedZmqAdapter`.

    Each instance routes orders for **one** account — the per-account
    :class:`~src.engine.account_session.LiveAccountSession` owns its
    own client so a node crash isolates to that account (story 10.5a
    AC8). The shared :class:`ValidatedZmqAdapter` carries the rule
    engine and the 10.4 atomic exposure gate; ``account_id`` is
    threaded through the internal ``Order`` so the gate scopes
    correctly.

    Parameters
    ----------
    loop : asyncio.AbstractEventLoop
        Engine event loop.
    client_id : ClientId
        Nautilus client identifier for the venue.
    venue : Venue
        Venue this client serves (``MT5`` for the production wiring).
    instrument_provider : InstrumentProvider
        Nautilus instrument provider for the venue.
    msgbus : MessageBus
        Engine message bus.
    cache : Cache
        Engine cache.
    clock : LiveClock
        Engine clock (used to stamp emitted events).
    account_id : str
        Sandboxed account this client routes to.
    validated_adapter : ValidatedZmqAdapter
        Validating adapter (rule engine + atomic exposure gate).
    account_type : AccountType, optional
        Defaults to :attr:`AccountType.MARGIN` (MT5 forex).
    base_currency : Currency | None, optional
        Base currency for the account. ``None`` ⇒ multi-currency.
    config : NautilusConfig | None, optional
        Optional Nautilus configuration.

    Notes
    -----
    Cancel / modify / batch-cancel commands are not yet supported —
    the production strategies in ``src/strategies/`` use bracket
    submissions only, and order modify/cancel mid-flight is
    explicitly Out of Scope per Epic 10 §"Out of Scope" (deferred to
    Epic 11+). Calling them raises ``NotImplementedError`` so a
    strategy that tries the unsupported path fails loudly.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        instrument_provider: "InstrumentProvider",
        msgbus: "MessageBus",
        cache: "Cache",
        clock: "LiveClock",
        account_id: str,
        validated_adapter: "ValidatedZmqAdapter",
        account_type: AccountType = AccountType.MARGIN,
        base_currency: "Currency | None" = None,
        config: "NautilusConfig | None" = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            oms_type=OmsType.NETTING,  # MT5 forex default
            account_type=account_type,
            base_currency=base_currency,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._account_id = account_id
        self._validated_adapter = validated_adapter

    @property
    def account_id(self) -> str:
        """Sandboxed account identifier this client is bound to."""
        return self._account_id

    @property
    def validated_adapter(self) -> "ValidatedZmqAdapter":
        return self._validated_adapter

    # ------------------------------------------------------------------
    # Connection plumbing — Nautilus expects async _connect/_disconnect
    # ------------------------------------------------------------------

    async def _connect(self) -> None:  # noqa: D401 — Nautilus contract
        # The underlying ZMQ socket is connected by the surrounding
        # engine wiring (story 10.5e). Nothing per-client to do.
        return

    async def _disconnect(self) -> None:
        return

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    async def _submit_order(self, command: SubmitOrder) -> None:
        await dispatch_submit_order(
            command.order,
            account_id=self._account_id,
            validated_adapter=self._validated_adapter,
            emitter=self,
            clock=self._clock,
        )

    # ------------------------------------------------------------------
    # Unsupported commands (deferred to Epic 11+)
    # ------------------------------------------------------------------

    async def _submit_order_list(self, command: SubmitOrderList) -> None:
        raise NotImplementedError(
            "ZmqExecutionClient does not support order lists; "
            "strategies should submit bracket orders one leg at a time."
        )

    async def _modify_order(self, command: ModifyOrder) -> None:
        raise NotImplementedError(
            "Order modify is Out of Scope for Epic 10 (deferred Epic 11+)."
        )

    async def _cancel_order(self, command: CancelOrder) -> None:
        raise NotImplementedError(
            "Order cancel is Out of Scope for Epic 10 (deferred Epic 11+)."
        )

    async def _cancel_all_orders(self, command: CancelAllOrders) -> None:
        raise NotImplementedError(
            "Cancel-all is Out of Scope for Epic 10 (deferred Epic 11+)."
        )

    async def _batch_cancel_orders(self, command: BatchCancelOrders) -> None:
        raise NotImplementedError(
            "Batch cancel is Out of Scope for Epic 10 (deferred Epic 11+)."
        )
