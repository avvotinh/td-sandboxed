"""Unit tests for the OrderGateway protocol (Epic 9 P0.12).

The protocol exists to keep the venue-side connection swappable: anything
the validator and the strategies use must come from this surface, never
from the concrete ``ZmqAdapter`` class. These tests pin the contract so
a future futures gateway only needs to satisfy the protocol.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus
from src.orders.order_gateway import OrderGateway


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestZmqAdapterIsOrderGateway:
    """ZmqAdapter must satisfy OrderGateway both structurally and at runtime."""

    def test_isinstance_runtime_check(self) -> None:
        adapter = ZmqAdapter()
        assert isinstance(adapter, OrderGateway)

    def test_carries_every_method_on_the_protocol(self) -> None:
        adapter = ZmqAdapter()
        for name in (
            "connect",
            "disconnect",
            "send_order",
            "send_order_and_wait",
            "get_pending_order_count",
        ):
            assert callable(getattr(adapter, name)), f"missing {name}"
        # is_connected is a property — read it to confirm it resolves.
        assert isinstance(adapter.is_connected, bool)


# ---------------------------------------------------------------------------
# Substitutability — a stub gateway can stand in for ZmqAdapter
# ---------------------------------------------------------------------------


class _StubOrderGateway:
    """Minimal OrderGateway implementation used to verify substitutability.

    Mirrors the shape a futures gateway (Rithmic, NinjaTrader) would
    expose. Records calls so tests can assert routing.
    """

    def __init__(self) -> None:
        self._connected = False
        self.sent: list[Order] = []
        self.awaited: list[Order] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_order(self, order: Order) -> None:
        if not self._connected:
            raise RuntimeError("Not connected")
        self.sent.append(order)

    async def send_order_and_wait(
        self, order: Order, timeout: float = 5.0
    ) -> OrderResult:
        if not self._connected:
            raise RuntimeError("Not connected")
        self.awaited.append(order)
        return OrderResult(
            order_id=order.order_id,
            status=OrderStatus.FILLED,
            account_id=order.account_id,
        )

    def get_pending_order_count(self) -> int:
        return 0


class TestStubGatewaySubstitutability:
    """A stub satisfies the protocol — proves the door is open for futures."""

    def test_stub_passes_isinstance_check(self) -> None:
        assert isinstance(_StubOrderGateway(), OrderGateway)

    @pytest.mark.asyncio
    async def test_stub_lifecycle(self) -> None:
        gw: OrderGateway = _StubOrderGateway()
        assert gw.is_connected is False
        await gw.connect()
        assert gw.is_connected is True
        await gw.disconnect()
        assert gw.is_connected is False

    @pytest.mark.asyncio
    async def test_stub_send_order_routes_through_protocol(self) -> None:
        gw = _StubOrderGateway()
        await gw.connect()
        order = Order(
            order_id="test-1",
            account_id="acct-1",
            symbol="EURUSD",
            action=OrderSide.BUY,
            volume=0.10,
            price=1.10,
        )
        await gw.send_order(order)
        assert gw.sent == [order]


# ---------------------------------------------------------------------------
# Negative path — partial implementations are NOT recognized
# ---------------------------------------------------------------------------


class TestPartialImplementationRejected:
    """A class missing any required method must fail the runtime check."""

    def test_missing_send_order_fails_isinstance(self) -> None:
        class Broken:
            @property
            def is_connected(self) -> bool:
                return False

            async def connect(self) -> None: ...
            async def disconnect(self) -> None: ...
            # send_order omitted on purpose

            async def send_order_and_wait(
                self, order: Order, timeout: float = 5.0
            ) -> OrderResult: ...

            def get_pending_order_count(self) -> int:
                return 0

        assert not isinstance(Broken(), OrderGateway)


# ---------------------------------------------------------------------------
# ValidatedZmqAdapter accepts any OrderGateway, not just ZmqAdapter
# ---------------------------------------------------------------------------


class _RecordingValidator:
    """Validator stub that always allows orders, recording the call."""

    def __init__(self) -> None:
        self.calls: list[tuple[Order, Any]] = []

    async def validate_order(self, order: Order, account_state: Any):  # noqa: ANN401
        from src.execution.order_validator import ValidationResult

        self.calls.append((order, account_state))
        return ValidationResult(
            allowed=True,
            warnings=[],
            evaluation_time_ms=0.1,
        )


class _RiskRegistryStub:
    """Risk registry stub that returns a minimal RiskState."""

    def get_risk_state(self, account_id: str) -> Any:  # noqa: ANN401
        from decimal import Decimal

        from src.accounts.risk_state import RiskState

        return RiskState(
            daily_pnl=Decimal("0"),
            daily_pnl_percent=Decimal("0"),
            current_equity=Decimal("10000"),
            peak_equity=Decimal("10000"),
            total_drawdown_percent=Decimal("0"),
            daily_starting_balance=Decimal("10000"),
        )


class TestValidatedAdapterAcceptsAnyGateway:
    """ValidatedZmqAdapter is typed against OrderGateway, not ZmqAdapter."""

    @pytest.mark.asyncio
    async def test_stub_gateway_routes_through_validation(self) -> None:
        from src.execution.validated_adapter import ValidatedZmqAdapter

        gw = _StubOrderGateway()
        await gw.connect()

        validated = ValidatedZmqAdapter(
            zmq_adapter=gw,  # not a real ZmqAdapter — the protocol is enough
            order_validator=_RecordingValidator(),
            risk_registry=_RiskRegistryStub(),
        )

        order = Order(
            order_id="proto-1",
            account_id="acct-9",
            symbol="EURUSD",
            action=OrderSide.SELL,
            volume=0.05,
            price=1.20,
        )
        await validated.send_order(order)

        # The validator approved; the order routed through the stub.
        assert gw.sent == [order]
