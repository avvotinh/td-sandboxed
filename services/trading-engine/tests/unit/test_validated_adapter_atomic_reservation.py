"""Unit tests for ValidatedZmqAdapter's atomic exposure reservation gate.

Story 10.4 — verify the integration between :class:`ValidatedZmqAdapter`
and :class:`ExposureReservation`. Focus on the contract:

- Reservation is consulted only when both ``exposure_reservation`` and
  ``max_lots_provider`` are wired.
- A rejected reservation raises :class:`OrderBlockedError` and the order
  is never sent.
- Release happens on every terminal path (filled, rejected by MT5,
  raised exception, cancellation).
- Release runs AFTER the PnL tracker is updated so subsequent
  reservations see the realized lots.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus
from src.execution.exceptions import OrderBlockedError
from src.execution.exposure_reservation import ReservationResult
from src.execution.validated_adapter import ValidatedZmqAdapter


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_order(volume: float = 0.5, account_id: str = "acct-1") -> Order:
    return Order(
        order_id=f"order-{volume}-{account_id}",
        account_id=account_id,
        action=OrderSide.BUY,
        symbol="XAUUSD",
        volume=volume,
        price=1850.0,
    )


def _make_order_result(filled: bool = True) -> OrderResult:
    return OrderResult(
        order_id="mock-order-id",
        status=OrderStatus.FILLED if filled else OrderStatus.REJECTED,
        fill_price=1850.0 if filled else None,
        slippage=0.0,
    )


def _make_validation_pass() -> MagicMock:
    """Pre-built validator returning an ALLOW result."""
    result = MagicMock()
    result.is_blocked = False
    result.has_warnings = False
    result.evaluation_time_ms = 1.5
    validator = MagicMock()
    validator.validate_order = AsyncMock(return_value=result)
    return validator


def _make_zmq_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.send_order = AsyncMock()
    adapter.send_order_and_wait = AsyncMock(return_value=_make_order_result(filled=True))
    adapter.is_connected = True
    adapter.get_pending_order_count = MagicMock(return_value=0)
    adapter.connect = AsyncMock()
    adapter.disconnect = AsyncMock()
    return adapter


def _make_risk_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=None)  # minimal state
    return registry


def _make_reservation(*, accepted: bool = True) -> MagicMock:
    reservation = MagicMock()
    reservation.reserve = AsyncMock(
        return_value=ReservationResult(
            accepted=accepted,
            new_reserved=Decimal("0.5") if accepted else Decimal("0"),
            previous_reserved=Decimal("0"),
        )
    )
    reservation.release = AsyncMock(return_value=Decimal("0"))
    return reservation


# --------------------------------------------------------------------------
# Behaviour
# --------------------------------------------------------------------------


class TestGateDisabled:
    """Reservation skipped when either dep is missing — backwards compat."""

    @pytest.mark.asyncio
    async def test_no_reservation_when_neither_dep_set(self) -> None:
        zmq = _make_zmq_adapter()
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
        )
        await adapter.send_order_and_wait(_make_order())
        zmq.send_order_and_wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_reservation_when_only_provider_set(self) -> None:
        zmq = _make_zmq_adapter()
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )
        await adapter.send_order_and_wait(_make_order())
        zmq.send_order_and_wait.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_reservation_when_only_reservation_set(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation()
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
        )
        await adapter.send_order_and_wait(_make_order())
        reservation.reserve.assert_not_called()

    @pytest.mark.asyncio
    async def test_provider_returning_none_skips_gate(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation()
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: None,
        )
        await adapter.send_order_and_wait(_make_order())
        reservation.reserve.assert_not_called()
        reservation.release.assert_not_called()


class TestGateAccept:
    """Happy path — reservation accepted, order sent, release called."""

    @pytest.mark.asyncio
    async def test_reserve_then_send_then_release(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=True)
        order = _make_order(volume=0.5)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )
        await adapter.send_order_and_wait(order)

        reservation.reserve.assert_awaited_once()
        zmq.send_order_and_wait.assert_awaited_once()
        reservation.release.assert_awaited_once_with("acct-1", Decimal("0.5"))

    @pytest.mark.asyncio
    async def test_reserve_max_total_subtracts_realized_lots(self) -> None:
        """max_total_for_reserve = max_lots - current_position_lots."""
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=True)

        # Provide a non-None RiskState so _build_account_state takes the
        # pnl_registry path (which surfaces current_position_lots).
        risk_state = MagicMock()
        risk_state.daily_starting_balance = Decimal("100000")
        risk_state.current_equity = Decimal("100000")
        risk_state.peak_equity = Decimal("100000")
        risk_state.daily_pnl = Decimal("0")
        risk_state.daily_pnl_percent = Decimal("0")
        risk_state.total_drawdown_percent = Decimal("0")
        risk_registry = MagicMock()
        risk_registry.get_risk_state = MagicMock(return_value=risk_state)

        pnl_registry = MagicMock()
        pnl_registry.get_open_positions_count = MagicMock(return_value=1)
        pnl_registry.get_total_exposure = MagicMock(return_value=Decimal("740"))
        pnl_registry.get_total_position_lots = MagicMock(return_value=Decimal("0.4"))
        pnl_registry.get_or_create = AsyncMock()

        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=risk_registry,
            pnl_registry=pnl_registry,
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )
        await adapter.send_order_and_wait(_make_order(volume=0.3))

        reserve_kwargs = reservation.reserve.call_args.kwargs
        assert reserve_kwargs["account_id"] == "acct-1"
        assert reserve_kwargs["requested_lots"] == Decimal("0.3")
        # 1.0 (max) - 0.4 (realized) = 0.6 headroom for in-flight reservation
        assert reserve_kwargs["max_total_lots"] == Decimal("0.6")


class TestGateReject:
    """Rejected reservation blocks the order without sending."""

    @pytest.mark.asyncio
    async def test_reject_raises_blocked_and_skips_send(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=False)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        with pytest.raises(OrderBlockedError) as exc_info:
            await adapter.send_order_and_wait(_make_order(volume=1.5))

        assert "atomic_exposure_reservation" == exc_info.value.blocked_by_rule
        zmq.send_order_and_wait.assert_not_called()
        reservation.release.assert_not_called()

    @pytest.mark.asyncio
    async def test_reject_does_not_release(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=False)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("0.5"),
        )

        with pytest.raises(OrderBlockedError):
            await adapter.send_order_and_wait(_make_order(volume=1.0))

        reservation.release.assert_not_called()


class TestReleaseOnTerminalPaths:
    """Release fires on filled, rejected, raised, and cancelled."""

    @pytest.mark.asyncio
    async def test_release_on_zmq_send_exception(self) -> None:
        zmq = _make_zmq_adapter()
        zmq.send_order_and_wait = AsyncMock(side_effect=RuntimeError("boom"))
        reservation = _make_reservation(accepted=True)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        with pytest.raises(RuntimeError, match="boom"):
            await adapter.send_order_and_wait(_make_order(volume=0.5))

        reservation.release.assert_awaited_once_with("acct-1", Decimal("0.5"))

    @pytest.mark.asyncio
    async def test_release_on_zmq_timeout(self) -> None:
        zmq = _make_zmq_adapter()
        zmq.send_order_and_wait = AsyncMock(side_effect=asyncio.TimeoutError())
        reservation = _make_reservation(accepted=True)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        with pytest.raises(asyncio.TimeoutError):
            await adapter.send_order_and_wait(_make_order(volume=0.5))

        reservation.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_release_on_mt5_rejection(self) -> None:
        zmq = _make_zmq_adapter()
        zmq.send_order_and_wait = AsyncMock(return_value=_make_order_result(filled=False))
        reservation = _make_reservation(accepted=True)
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )
        await adapter.send_order_and_wait(_make_order(volume=0.5))
        reservation.release.assert_awaited_once()


class TestReleaseOrderingWithPnL:
    """Release runs AFTER PnL tracker on_trade_executed.

    This closes the gap where reservation drops to zero before realized
    lots have been recorded in the PnL tracker.
    """

    @pytest.mark.asyncio
    async def test_release_called_after_pnl_tracker(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=True)

        # Track ordering — PnL tracker.on_trade_executed must be called
        # before reservation.release.
        call_order: list[str] = []

        pnl_tracker = MagicMock()
        pnl_tracker.on_trade_executed = AsyncMock(
            side_effect=lambda *args, **kwargs: call_order.append("pnl")
        )
        pnl_registry = MagicMock()
        pnl_registry.get_or_create = AsyncMock(return_value=pnl_tracker)
        pnl_registry.get_open_positions_count = MagicMock(return_value=0)
        pnl_registry.get_total_exposure = MagicMock(return_value=Decimal("0"))
        pnl_registry.get_total_position_lots = MagicMock(return_value=Decimal("0"))

        reservation.release = AsyncMock(
            side_effect=lambda *args, **kwargs: call_order.append("release")
        )

        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            pnl_registry=pnl_registry,
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        await adapter.send_order_and_wait(_make_order(volume=0.5))

        assert call_order == ["pnl", "release"]


class TestRedisErrorTolerance:
    """A Redis error mid-reserve must not crash the order path."""

    @pytest.mark.asyncio
    async def test_reserve_raises_falls_back_to_no_gate(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = MagicMock()
        reservation.reserve = AsyncMock(side_effect=RuntimeError("redis dead"))
        reservation.release = AsyncMock()
        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        # Should NOT raise — falls back to validator-only behaviour
        await adapter.send_order_and_wait(_make_order())

        zmq.send_order_and_wait.assert_awaited_once()
        # No release because no reservation acquired
        reservation.release.assert_not_called()

    @pytest.mark.asyncio
    async def test_release_swallows_errors(self) -> None:
        zmq = _make_zmq_adapter()
        reservation = _make_reservation(accepted=True)
        reservation.release = AsyncMock(side_effect=RuntimeError("redis dead"))

        adapter = ValidatedZmqAdapter(
            zmq_adapter=zmq,
            order_validator=_make_validation_pass(),
            risk_registry=_make_risk_registry(),
            exposure_reservation=reservation,
            max_lots_provider=lambda _aid, _state: Decimal("1.0"),
        )

        # Order completes successfully even though release blew up.
        result = await adapter.send_order_and_wait(_make_order(volume=0.5))
        assert result.is_filled
