"""Story 10.5e3 — phase-changed Redis subscriber tests.

Covers the listener wired by :meth:`LiveOrchestrator._start_phase_change_listener`:

- ``account:phase-changed:{aid}`` (pmessage) → ``reload_account(aid)``.
- Channel name parser tolerates bytes/str + rejects malformed channels.
- Unknown account ids are logged + ignored — no crash.
- A reload exception does not break the listener.
- Stop cancels the listener and unsubscribes.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from decimal import Decimal
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import (
    PHASE_CHANGED_CHANNEL_PREFIX,
    LiveOrchestrator,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test pubsub stub — emits messages from a queue, listener-friendly
# ---------------------------------------------------------------------------


class _PubSubStub:
    """Minimal Redis pubsub fake.

    ``listen`` is an async generator that drains an internal queue;
    tests push messages onto the queue then await the orchestrator's
    handler to fire. Used by :class:`_RedisManagerStub` below.
    """

    instances: ClassVar[list["_PubSubStub"]] = []

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.psubscribed: list[str] = []
        self.punsubscribed: int = 0
        self.closed: bool = False
        _PubSubStub.instances.append(self)

    async def psubscribe(self, pattern: str) -> None:
        self.psubscribed.append(pattern)

    async def punsubscribe(self) -> None:
        self.punsubscribed += 1

    async def aclose(self) -> None:
        self.closed = True

    async def listen(self) -> AsyncGenerator[dict, None]:
        # Cancellation propagates from ``queue.get()`` and exits the
        # generator cleanly — matches redis-py's real PubSub.listen.
        while True:
            msg = await self.queue.get()
            yield msg


class _RedisManagerStub:
    def __init__(self) -> None:
        self.pubsub_obj = _PubSubStub()
        client = MagicMock()
        client.pubsub = MagicMock(return_value=self.pubsub_obj)
        client.setex = AsyncMock()
        self.client = client


@pytest.fixture(autouse=True)
def _reset_pubsub_stub() -> None:
    _PubSubStub.instances.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _account(account_id: str = "acct-1") -> MagicMock:
    sig_filter = MagicMock()
    sig_filter.symbols = []  # keeps _build_session_components a no-op
    cfg = MagicMock()
    cfg.id = account_id
    cfg.signal_filter = sig_filter
    cfg.strategy = "ma_crossover"
    cfg.strategy_params = {}
    return cfg


def _account_manager(active: list[MagicMock]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=[a.id for a in active])
    am.get_account = MagicMock(side_effect=lambda aid: next(
        (a for a in active if a.id == aid), None
    ))
    am.pause_account = AsyncMock()
    return am


def _ras() -> MagicMock:
    svc = MagicMock()
    svc.get_rules_for_account = MagicMock(return_value=[])
    return svc


def _risk_registry() -> MagicMock:
    state = MagicMock()
    state.daily_starting_balance = Decimal("100000")
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=state)
    return registry


def _live(*, accounts: list[MagicMock]) -> tuple[LiveOrchestrator, _RedisManagerStub]:
    manager = _RedisManagerStub()
    live = LiveOrchestrator(
        services=LiveServiceBundle(),
        account_manager=_account_manager(accounts),
        rule_assignment_service=_ras(),
        risk_registry=_risk_registry(),
        redis_manager=manager,
        validated_adapter=None,  # no node — keep this test focused on the listener
        audit_service=MagicMock(log_system_event_sync=AsyncMock()),
        health_push_interval=10.0,
    )
    return live, manager


async def _await_pmessage_handled(
    live: LiveOrchestrator, *, predicate, timeout: float = 1.0
) -> bool:
    """Spin until ``predicate(live)`` is true or the timeout elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate(live):
            return True
        await asyncio.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# Channel parsing
# ---------------------------------------------------------------------------


class TestChannelParsing:
    """``_parse_phase_message`` is a pure function — exercise edge cases."""

    def test_str_channel_extracts_account_id(self) -> None:
        msg = {
            "type": "pmessage",
            "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}ftmo-007",
        }
        assert LiveOrchestrator._parse_phase_message(msg) == "ftmo-007"

    def test_bytes_channel_decoded(self) -> None:
        msg = {
            "type": "pmessage",
            "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}acct-x".encode(),
        }
        assert LiveOrchestrator._parse_phase_message(msg) == "acct-x"

    def test_non_pmessage_returns_none(self) -> None:
        # Subscribe-ack frame
        msg = {
            "type": "psubscribe",
            "channel": PHASE_CHANGED_CHANNEL_PREFIX + "*",
        }
        assert LiveOrchestrator._parse_phase_message(msg) is None

    def test_non_dict_returns_none(self) -> None:
        assert LiveOrchestrator._parse_phase_message("garbage") is None

    def test_unrelated_channel_raises(self) -> None:
        msg = {"type": "pmessage", "channel": "other:topic:foo"}
        with pytest.raises(ValueError, match="Unexpected channel"):
            LiveOrchestrator._parse_phase_message(msg)

    def test_empty_account_id_raises(self) -> None:
        msg = {"type": "pmessage", "channel": PHASE_CHANGED_CHANNEL_PREFIX}
        with pytest.raises(ValueError, match="Empty account_id"):
            LiveOrchestrator._parse_phase_message(msg)


# ---------------------------------------------------------------------------
# Listener lifecycle
# ---------------------------------------------------------------------------


class TestListenerLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_pattern(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])
        await live.start()

        assert manager.pubsub_obj.psubscribed == [
            f"{PHASE_CHANGED_CHANNEL_PREFIX}*"
        ]
        await live.stop()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_and_cancels_listener(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])
        await live.start()
        listener_task = live._phase_listener_task
        assert listener_task is not None and not listener_task.done()

        await live.stop()
        assert manager.pubsub_obj.punsubscribed == 1
        assert manager.pubsub_obj.closed is True
        assert live._phase_listener_task is None

    @pytest.mark.asyncio
    async def test_psubscribe_failure_propagates_no_listener_left_behind(
        self,
    ) -> None:
        """If ``psubscribe`` raises, ``start()`` propagates the error and the
        orchestrator does not retain a half-initialised listener task."""
        live, manager = _live(accounts=[_account("acct-1")])
        # Force the pubsub-subscribe path to fail
        manager.pubsub_obj.psubscribe = AsyncMock(
            side_effect=ConnectionError("redis down")
        )

        with pytest.raises(ConnectionError, match="redis down"):
            await live.start()

        # No listener task spawned (psubscribe is the first await in start)
        assert live._phase_listener_task is None
        # Stop is safe even though start failed midway
        await live.stop()


# ---------------------------------------------------------------------------
# Reload dispatch
# ---------------------------------------------------------------------------


class TestReloadDispatch:
    @pytest.mark.asyncio
    async def test_pmessage_for_active_account_triggers_reload(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])
        # Spy reload_account so we can assert without rebuilding components.
        reload_calls: list[str] = []

        async def _reload_spy(aid: str):
            reload_calls.append(aid)
            return live.sessions[aid]

        live.reload_account = _reload_spy  # type: ignore[assignment]

        await live.start()
        await manager.pubsub_obj.queue.put(
            {
                "type": "pmessage",
                "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}acct-1",
                "data": b"{}",
            }
        )

        ok = await _await_pmessage_handled(
            live, predicate=lambda _: reload_calls == ["acct-1"]
        )
        assert ok, f"reload not triggered: {reload_calls}"
        await live.stop()

    @pytest.mark.asyncio
    async def test_pmessage_for_unknown_account_is_ignored(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])

        reload_calls: list[str] = []

        async def _reload_spy(aid: str):
            reload_calls.append(aid)
            return live.sessions.get(aid)

        live.reload_account = _reload_spy  # type: ignore[assignment]

        await live.start()
        await manager.pubsub_obj.queue.put(
            {
                "type": "pmessage",
                "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}not-an-account",
                "data": b"{}",
            }
        )
        # Give the listener a chance to drain; then assert reload was NOT called.
        await asyncio.sleep(0.05)
        assert reload_calls == []
        await live.stop()

    @pytest.mark.asyncio
    async def test_malformed_channel_skipped_listener_alive(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])
        reload_calls: list[str] = []

        async def _reload_spy(aid: str):
            reload_calls.append(aid)
            return live.sessions[aid]

        live.reload_account = _reload_spy  # type: ignore[assignment]

        await live.start()
        # Bad channel first
        await manager.pubsub_obj.queue.put(
            {"type": "pmessage", "channel": "garbage:channel", "data": b""}
        )
        # Followed by a valid one — proves the listener survived the bad msg
        await manager.pubsub_obj.queue.put(
            {
                "type": "pmessage",
                "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}acct-1",
                "data": b"{}",
            }
        )
        ok = await _await_pmessage_handled(
            live, predicate=lambda _: reload_calls == ["acct-1"]
        )
        assert ok, "listener died after malformed message"
        await live.stop()

    @pytest.mark.asyncio
    async def test_reload_failure_does_not_kill_listener(self) -> None:
        live, manager = _live(accounts=[_account("acct-1")])

        call_count = {"n": 0}

        async def _reload_spy(aid: str):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("reload boom")
            return live.sessions[aid]

        live.reload_account = _reload_spy  # type: ignore[assignment]

        await live.start()
        # First message — reload raises
        await manager.pubsub_obj.queue.put(
            {
                "type": "pmessage",
                "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}acct-1",
                "data": b"{}",
            }
        )
        # Second message — should still be processed
        await manager.pubsub_obj.queue.put(
            {
                "type": "pmessage",
                "channel": f"{PHASE_CHANGED_CHANNEL_PREFIX}acct-1",
                "data": b"{}",
            }
        )
        ok = await _await_pmessage_handled(
            live, predicate=lambda _: call_count["n"] >= 2
        )
        assert ok, f"listener stopped after reload failure: {call_count}"
        await live.stop()
