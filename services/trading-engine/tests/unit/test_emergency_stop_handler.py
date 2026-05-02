"""Unit tests for :class:`EmergencyStopHandler` (story 10.7)."""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_models import MT5Position
from src.state.emergency_stop_handler import (
    EMERGENCY_STOP_CHANNEL,
    EMERGENCY_STOP_CONFIRMATION_CHANNEL,
    EmergencyStopHandler,
    EmergencyStopResult,
)


# -------------------------------------------------------------------------
# Fixtures / fakes
# -------------------------------------------------------------------------


def _position(
    *,
    ticket: int = 12345,
    side: str = "BUY",
    volume: Decimal = Decimal("0.5"),
    symbol: str = "XAUUSD",
) -> MT5Position:
    return MT5Position(
        ticket=ticket,
        symbol=symbol,
        side=side,
        volume=volume,
        entry_price=Decimal("1850.0"),
        entry_time="2026-05-01T10:00:00Z",
        current_price=Decimal("1851.0"),
        profit=Decimal("0"),
        swap=Decimal("0"),
        commission=Decimal("0"),
    )


class _FakePubSub:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.subscribed: tuple[str, ...] | None = None
        self.unsubscribed = False
        self.closed = False

    async def subscribe(self, *channels: str) -> None:
        self.subscribed = channels

    async def listen(self):
        while True:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                await asyncio.sleep(0.5)
                continue
            yield msg

    async def unsubscribe(self) -> None:
        self.unsubscribed = True

    async def aclose(self) -> None:
        self.closed = True

    def push_command(self, command: dict[str, Any]) -> None:
        self._queue.put_nowait(
            {
                "type": "message",
                "channel": EMERGENCY_STOP_CHANNEL,
                "data": json.dumps(command).encode("utf-8"),
            }
        )

    def push_raw(self, message: dict[str, Any]) -> None:
        self._queue.put_nowait(message)


def _redis_manager() -> tuple[MagicMock, MagicMock, _FakePubSub]:
    pubsub = _FakePubSub()
    client = MagicMock()
    client.pubsub = MagicMock(return_value=pubsub)
    client.publish = AsyncMock()
    manager = MagicMock()
    manager.client = client
    return manager, client, pubsub


def _account_manager(active: list[str], pause_raises_on: set[str] | None = None) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=list(active))

    async def _pause(account_id: str) -> None:
        if pause_raises_on and account_id in pause_raises_on:
            raise ValueError(f"cannot pause {account_id}")

    am.pause_account = AsyncMock(side_effect=_pause)
    return am


def _zmq_adapter(
    positions_by_account: dict[str, list[MT5Position]] | None = None,
    *,
    query_raises_on: set[str] | None = None,
    send_raises_for_tickets: set[int] | None = None,
) -> MagicMock:
    z = MagicMock()
    pos_map = dict(positions_by_account or {})

    async def _query(account_id: str, timeout: float = 5.0) -> list[MT5Position]:
        if query_raises_on and account_id in query_raises_on:
            raise RuntimeError(f"mt5 query failed for {account_id}")
        return list(pos_map.get(account_id, []))

    z.query_positions = AsyncMock(side_effect=_query)

    sent: list = []

    async def _send(order, timeout: float = 5.0):
        sent.append(order)
        return MagicMock()

    z.send_order_and_wait = AsyncMock(side_effect=_send)
    z._sent_orders = sent  # type: ignore[attr-defined]
    return z


def _audit_service() -> MagicMock:
    a = MagicMock()
    a.log_system_event_sync = AsyncMock()
    return a


def _build_handler(
    active_accounts: list[str],
    *,
    positions: dict[str, list[MT5Position]] | None = None,
    query_raises_on: set[str] | None = None,
    pause_raises_on: set[str] | None = None,
) -> tuple[EmergencyStopHandler, MagicMock, _FakePubSub, MagicMock, MagicMock, MagicMock]:
    manager, client, pubsub = _redis_manager()
    am = _account_manager(active_accounts, pause_raises_on=pause_raises_on)
    z = _zmq_adapter(positions, query_raises_on=query_raises_on)
    audit = _audit_service()
    handler = EmergencyStopHandler(
        redis_manager=manager,
        account_manager=am,
        zmq_adapter=z,
        audit_service=audit,
    )
    return handler, client, pubsub, am, z, audit


# -------------------------------------------------------------------------
# Lifecycle
# -------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_emergency_stop_channel(self) -> None:
        handler, _client, pubsub, *_ = _build_handler([])
        await handler.start()
        assert pubsub.subscribed == (EMERGENCY_STOP_CHANNEL,)
        assert handler.is_running
        await handler.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self) -> None:
        handler, _client, pubsub, *_ = _build_handler([])
        await handler.start()
        first_task = handler._listener_task  # type: ignore[attr-defined]
        await handler.start()
        assert handler._listener_task is first_task  # type: ignore[attr-defined]
        await handler.stop()

    @pytest.mark.asyncio
    async def test_stop_idempotent_when_not_running(self) -> None:
        handler, *_ = _build_handler([])
        await handler.stop()  # never started
        assert not handler.is_running

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_and_closes_pubsub(self) -> None:
        handler, _client, pubsub, *_ = _build_handler([])
        await handler.start()
        await handler.stop()
        assert pubsub.unsubscribed
        assert pubsub.closed


# -------------------------------------------------------------------------
# Happy path — flat all positions
# -------------------------------------------------------------------------


class TestFlatPositions:
    @pytest.mark.asyncio
    async def test_closes_every_position_for_every_active_account(
        self,
    ) -> None:
        positions = {
            "acct-a": [_position(ticket=1, side="BUY"), _position(ticket=2, side="SELL")],
            "acct-b": [_position(ticket=3, side="BUY")],
        }
        handler, client, _pubsub, am, z, audit = _build_handler(
            ["acct-a", "acct-b"], positions=positions
        )
        await handler._handle_stop({"command": "stop_all"})

        # 3 close orders sent total (2 + 1)
        assert z.send_order_and_wait.await_count == 3
        # 2 pause calls
        assert am.pause_account.await_count == 2
        # 2 audit rows: triggered + complete
        events = [
            c.kwargs["event_subtype"]
            for c in audit.log_system_event_sync.await_args_list
        ]
        assert events == [
            "emergency_stop_triggered",
            "emergency_stop_complete",
        ]
        # Confirmation published
        client.publish.assert_awaited_once()
        ch, payload = client.publish.call_args.args
        assert ch == EMERGENCY_STOP_CONFIRMATION_CHANNEL
        decoded = json.loads(payload)
        assert decoded["positions_closed"] == 3
        assert decoded["accounts_paused"] == 2

    @pytest.mark.asyncio
    async def test_close_orders_have_opposite_side(self) -> None:
        positions = {
            "acct-a": [
                _position(ticket=1, side="BUY"),
                _position(ticket=2, side="SELL"),
            ]
        }
        handler, _c, _ps, _am, z, _audit = _build_handler(
            ["acct-a"], positions=positions
        )
        await handler._handle_stop({"command": "stop_all"})

        sides = [order.action.value for order in z._sent_orders]
        # BUY position → SELL close, SELL position → BUY close
        assert sorted(sides) == ["BUY", "SELL"]

    @pytest.mark.asyncio
    async def test_no_positions_still_pauses_account(self) -> None:
        handler, _c, _ps, am, z, _audit = _build_handler(
            ["acct-a"], positions={"acct-a": []}
        )
        await handler._handle_stop({"command": "stop_all"})

        z.send_order_and_wait.assert_not_called()
        am.pause_account.assert_awaited_once_with("acct-a")


# -------------------------------------------------------------------------
# Failure isolation
# -------------------------------------------------------------------------


class TestFailureIsolation:
    @pytest.mark.asyncio
    async def test_query_failure_recorded_but_other_accounts_proceed(
        self,
    ) -> None:
        positions = {
            "acct-a": [_position(ticket=1)],
            "acct-b": [],  # query raises here
            "acct-c": [_position(ticket=3)],
        }
        handler, client, _ps, am, z, audit = _build_handler(
            ["acct-a", "acct-b", "acct-c"],
            positions=positions,
            query_raises_on={"acct-b"},
        )
        await handler._handle_stop({"command": "stop_all"})

        # 2 close orders (acct-a + acct-c). acct-b query failed.
        assert z.send_order_and_wait.await_count == 2
        # All 3 paused regardless.
        assert am.pause_account.await_count == 3

        # Failures recorded in confirmation payload
        ch, payload = client.publish.call_args.args
        decoded = json.loads(payload)
        failure_accounts = [f[0] for f in decoded["failures"]]
        assert "acct-b" in failure_accounts

    @pytest.mark.asyncio
    async def test_pause_failure_recorded_in_confirmation(self) -> None:
        handler, client, _ps, am, _z, _audit = _build_handler(
            ["acct-a"],
            positions={"acct-a": []},
            pause_raises_on={"acct-a"},
        )
        await handler._handle_stop({"command": "stop_all"})

        ch, payload = client.publish.call_args.args
        decoded = json.loads(payload)
        assert decoded["accounts_paused"] == 0
        assert any("acct-a" in f for f in decoded["failures"])

    @pytest.mark.asyncio
    async def test_unsupported_position_side_skipped_not_raised(self) -> None:
        bad = _position(side="HOLD", ticket=99)
        positions = {"acct-a": [bad, _position(ticket=1, side="BUY")]}
        handler, _c, _ps, _am, z, _audit = _build_handler(
            ["acct-a"], positions=positions
        )
        await handler._handle_stop({"command": "stop_all"})

        # Only the BUY position closed; bad side skipped without raising.
        assert z.send_order_and_wait.await_count == 1


# -------------------------------------------------------------------------
# Listener loop
# -------------------------------------------------------------------------


class TestListenerLoop:
    @pytest.mark.asyncio
    async def test_pubsub_message_triggers_full_flow(self) -> None:
        handler, client, pubsub, am, z, _audit = _build_handler(
            ["acct-a"], positions={"acct-a": [_position(ticket=1)]}
        )
        await handler.start()
        pubsub.push_command({"command": "stop_all", "initiator": "telegram"})

        for _ in range(50):
            if z.send_order_and_wait.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        await handler.stop()

        z.send_order_and_wait.assert_awaited()
        am.pause_account.assert_awaited()
        client.publish.assert_awaited()

    @pytest.mark.asyncio
    async def test_malformed_payload_skipped_then_continues(self) -> None:
        handler, _c, pubsub, _am, z, _audit = _build_handler(
            ["acct-a"], positions={"acct-a": [_position(ticket=1)]}
        )
        await handler.start()
        # Bad JSON first
        pubsub.push_raw(
            {
                "type": "message",
                "channel": EMERGENCY_STOP_CHANNEL,
                "data": b"{not json",
            }
        )
        # Then a valid command
        pubsub.push_command({"command": "stop_all"})

        for _ in range(50):
            if z.send_order_and_wait.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        await handler.stop()

        z.send_order_and_wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_subscribe_frame_is_skipped(self) -> None:
        handler, *_ = _build_handler(["acct-a"])
        await handler.start()
        # No exception even when only subscribe frames arrive
        await asyncio.sleep(0.05)
        await handler.stop()


# -------------------------------------------------------------------------
# Audit-row contract
# -------------------------------------------------------------------------


class TestAuditContract:
    @pytest.mark.asyncio
    async def test_trigger_is_logged_before_any_pause(self) -> None:
        handler, _c, _ps, am, _z, audit = _build_handler(
            ["acct-a"], positions={"acct-a": []}
        )
        call_order: list[str] = []

        async def _audit_call(**kwargs):
            call_order.append(kwargs["event_subtype"])

        audit.log_system_event_sync = AsyncMock(side_effect=_audit_call)

        async def _pause(account_id: str) -> None:
            call_order.append(f"pause:{account_id}")

        am.pause_account = AsyncMock(side_effect=_pause)

        await handler._handle_stop({"command": "stop_all"})

        assert call_order[0] == "emergency_stop_triggered"
        assert call_order[-1] == "emergency_stop_complete"
        assert "pause:acct-a" in call_order


# -------------------------------------------------------------------------
# EmergencyStopResult
# -------------------------------------------------------------------------


class TestEmergencyStopResult:
    def test_to_payload_includes_originating_command(self) -> None:
        result = EmergencyStopResult(
            accounts_processed=2,
            positions_closed=3,
            accounts_paused=2,
        )
        payload = result.to_payload(
            command={"command": "stop_all", "initiator": "telegram"}
        )
        decoded = json.loads(payload)
        assert decoded["type"] == "emergency_stop_confirmation"
        assert decoded["accounts_processed"] == 2
        assert decoded["positions_closed"] == 3
        assert decoded["originating_command"] == {
            "command": "stop_all",
            "initiator": "telegram",
        }
