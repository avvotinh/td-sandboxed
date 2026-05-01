"""Tests for the live execution dispatcher (story 10.5c)."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
from nautilus_trader.model.objects import Price

from src.adapters.zmq_models import OrderResult, OrderStatus
from src.engine.clients.submit_dispatcher import dispatch_submit_order
from src.execution.exceptions import OrderBlockedError


VENUE = Venue("MT5")
INSTRUMENT_ID = InstrumentId(Symbol("XAUUSD"), VENUE)
TRADER_ID = TraderId("TRADER-001")
STRATEGY_ID = StrategyId("S-test")


def _market_order(quantity: float = 0.5) -> MarketOrder:
    return MarketOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=INSTRUMENT_ID,
        client_order_id=ClientOrderId(f"O-{quantity}"),
        order_side=OrderSide.BUY,
        quantity=Quantity.from_str(f"{quantity}"),
        init_id=UUID4(),
        ts_init=0,
        time_in_force=TimeInForce.GTC,
    )


class _FakeEmitter:
    """Records every generate_* call so tests can assert on them.

    Uses ``**kwargs`` rather than the exact Protocol signatures so a
    Protocol drift in :mod:`submit_dispatcher` shows up here as a clear
    AttributeError on the missing kwarg, not a silent mismatch.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate_order_submitted(self, **kwargs: Any) -> None:
        self.calls.append(("submitted", kwargs))

    def generate_order_filled(self, **kwargs: Any) -> None:
        self.calls.append(("filled", kwargs))

    def generate_order_rejected(self, **kwargs: Any) -> None:
        self.calls.append(("rejected", kwargs))

    def generate_order_denied(self, **kwargs: Any) -> None:
        self.calls.append(("denied", kwargs))

    @property
    def event_names(self) -> list[str]:
        return [name for name, _ in self.calls]


class _FakeClock:
    def __init__(self) -> None:
        self._counter = 0

    def timestamp_ns(self) -> int:
        self._counter += 1
        return self._counter


def _validated_adapter(*, returns: OrderResult | None = None, raises: Exception | None = None) -> MagicMock:
    adapter = MagicMock()
    if raises is not None:
        adapter.send_order_and_wait = AsyncMock(side_effect=raises)
    else:
        adapter.send_order_and_wait = AsyncMock(return_value=returns)
    return adapter


# -------------------------------------------------------------------------
# Happy path
# -------------------------------------------------------------------------


class TestFilledOrder:
    @pytest.mark.asyncio
    async def test_filled_emits_submitted_then_filled(self) -> None:
        emitter = _FakeEmitter()
        clock = _FakeClock()
        result = OrderResult(
            order_id="MT5-12345",
            status=OrderStatus.FILLED,
            fill_price=1850.45,
            slippage=0.0,
        )
        adapter = _validated_adapter(returns=result)

        await dispatch_submit_order(
            _market_order(),
            account_id="ftmo-001",
            validated_adapter=adapter,
            emitter=emitter,
            clock=clock,
        )

        assert emitter.event_names == ["submitted", "filled"]
        adapter.send_order_and_wait.assert_awaited_once()
        # Validate the internal Order was passed through with the right account
        sent = adapter.send_order_and_wait.call_args.args[0]
        assert sent.account_id == "ftmo-001"


class TestFilledWithNoFillPrice:
    """Defensive: FILLED status without fill_price must NOT emit a zero
    price OrderFilled — that would corrupt downstream P&L bookkeeping."""

    @pytest.mark.asyncio
    async def test_filled_without_fill_price_emits_rejected(self) -> None:
        emitter = _FakeEmitter()
        result = OrderResult(
            order_id="MT5-bad",
            status=OrderStatus.FILLED,
            fill_price=None,  # bridge bug — should never happen on real MT5
        )
        adapter = _validated_adapter(returns=result)

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["submitted", "rejected"]
        rejected = next(c for n, c in emitter.calls if n == "rejected")
        assert "no fill price" in rejected["reason"].lower()


class TestRejectedByMT5:
    @pytest.mark.asyncio
    async def test_mt5_rejection_emits_submitted_then_rejected(self) -> None:
        emitter = _FakeEmitter()
        result = OrderResult(
            order_id="MT5-rej",
            status=OrderStatus.REJECTED,
            error="market closed",
        )
        adapter = _validated_adapter(returns=result)

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["submitted", "rejected"]
        rejected = next(c for n, c in emitter.calls if n == "rejected")
        assert "market closed" in rejected["reason"]


# -------------------------------------------------------------------------
# Pre-send failure paths
# -------------------------------------------------------------------------


class TestBlockedByValidator:
    @pytest.mark.asyncio
    async def test_blocked_emits_denied_without_send(self) -> None:
        emitter = _FakeEmitter()
        adapter = _validated_adapter(
            raises=OrderBlockedError(
                reason="daily loss exceeded",
                blocked_by_rule="daily_loss_limit",
                current_value=5.5,
                threshold_value=5.0,
            )
        )

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["denied"]
        denied = emitter.calls[0][1]
        assert "daily loss" in denied["reason"]

    @pytest.mark.asyncio
    async def test_atomic_gate_rejection_emits_denied(self) -> None:
        emitter = _FakeEmitter()
        adapter = _validated_adapter(
            raises=OrderBlockedError(
                reason="Atomic exposure gate rejected",
                blocked_by_rule="atomic_exposure_reservation",
            )
        )

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["denied"]


class TestUnsupportedOrderType:
    @pytest.mark.asyncio
    async def test_limit_order_emits_denied(self) -> None:
        limit = LimitOrder(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=INSTRUMENT_ID,
            client_order_id=ClientOrderId("O-LIM-1"),
            order_side=OrderSide.BUY,
            quantity=Quantity.from_str("0.5"),
            price=Price.from_str("1850.00"),
            init_id=UUID4(),
            ts_init=0,
            time_in_force=TimeInForce.GTC,
        )
        emitter = _FakeEmitter()
        adapter = _validated_adapter(returns=None)  # never called

        await dispatch_submit_order(
            limit,
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["denied"]
        adapter.send_order_and_wait.assert_not_called()


# -------------------------------------------------------------------------
# Send failure paths
# -------------------------------------------------------------------------


class TestSendFailures:
    @pytest.mark.asyncio
    async def test_timeout_emits_rejected(self) -> None:
        emitter = _FakeEmitter()
        adapter = _validated_adapter(raises=asyncio.TimeoutError())

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["rejected"]
        rej = emitter.calls[0][1]
        assert "timeout" in rej["reason"].lower()

    @pytest.mark.asyncio
    async def test_unexpected_exception_emits_rejected(self) -> None:
        emitter = _FakeEmitter()
        adapter = _validated_adapter(raises=RuntimeError("zmq down"))

        await dispatch_submit_order(
            _market_order(),
            account_id="acct-1",
            validated_adapter=adapter,
            emitter=emitter,
            clock=_FakeClock(),
        )

        assert emitter.event_names == ["rejected"]
        rej = emitter.calls[0][1]
        assert "send failed" in rej["reason"]
        assert "zmq down" in rej["reason"]


# -------------------------------------------------------------------------
# Contract: no exceptions ever leak out
# -------------------------------------------------------------------------


class TestNeverRaises:
    @pytest.mark.asyncio
    async def test_clock_failure_does_not_propagate(self) -> None:
        # Clock raises after first call — second call would happen if dispatcher
        # tries to emit a follow-up event. Verify the dispatcher is robust.
        class _BrokenClock:
            def __init__(self) -> None:
                self.calls = 0

            def timestamp_ns(self) -> int:
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("clock dead")
                return 1

        emitter = _FakeEmitter()
        adapter = _validated_adapter(raises=OrderBlockedError(reason="blocked"))

        # Even with a flaky clock, dispatcher should not raise
        try:
            await dispatch_submit_order(
                _market_order(),
                account_id="acct-1",
                validated_adapter=adapter,
                emitter=emitter,
                clock=_BrokenClock(),
            )
        except Exception:
            pytest.fail("Dispatcher must not raise — engine state would diverge")
