"""Story 10.5e2 — TradingNode lifecycle integration with :class:`LiveOrchestrator`.

Covers the wiring extension on top of 10.5e1:

- ``_build_session_components`` calls the injected ``node_factory``
  when both ``redis_manager`` and ``validated_adapter`` are wired (full
  live-trading deps); the resulting node is attached to
  ``session.components["trading_node"]``.
- ``_start_session`` spawns ``node.run_async()`` as a tracked task.
- ``_teardown_session_components`` calls ``stop_async()``, awaits/
  cancels the run task, and disposes the node.
- A runtime crash in ``run_async()`` propagates to
  ``_isolate_failed_session`` (AC8) without affecting other accounts.
- Backwards compat: when ``validated_adapter`` is absent (10.5e1-shape
  wiring), no node is built and the session still flips RUNNING.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _account(
    account_id: str = "acct-1",
    *,
    symbols: list[str] | None = None,
    strategy: str = "ma_crossover",
    strategy_params: dict | None = None,
) -> MagicMock:
    sig_filter = MagicMock()
    sig_filter.symbols = symbols if symbols is not None else ["XAUUSD"]
    cfg = MagicMock()
    cfg.id = account_id
    cfg.signal_filter = sig_filter
    cfg.strategy = strategy
    cfg.strategy_params = strategy_params or {}
    return cfg


def _account_manager(active: list[MagicMock]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=[a.id for a in active])
    am.get_account = MagicMock(side_effect=lambda aid: next(
        (a for a in active if a.id == aid), None
    ))
    am.pause_account = AsyncMock()
    return am


def _rule_assignment_service() -> MagicMock:
    svc = MagicMock()
    svc.get_rules_for_account = MagicMock(return_value=[])
    return svc


def _risk_registry(starting: Decimal = Decimal("100000")) -> MagicMock:
    state = MagicMock()
    state.daily_starting_balance = starting
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=state)
    return registry


def _redis_manager() -> MagicMock:
    client = MagicMock()
    client.setex = AsyncMock()
    # Story 10.5e3 — phase-changed listener subscribes via ``pubsub()``.
    pubsub_stub = MagicMock()
    pubsub_stub.psubscribe = AsyncMock()
    pubsub_stub.punsubscribe = AsyncMock()
    pubsub_stub.aclose = AsyncMock()

    async def _empty_listen():
        if False:
            yield  # pragma: no cover

    pubsub_stub.listen = _empty_listen
    client.pubsub = MagicMock(return_value=pubsub_stub)
    manager = MagicMock()
    manager.client = client
    return manager


class _StubNode:
    """Minimal trading node for lifecycle assertions.

    Tracks the events the orchestrator drives (run/stop/dispose) so
    tests can verify ordering without needing a Nautilus kernel.
    """

    instances: ClassVar[list["_StubNode"]] = []

    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.run_started = asyncio.Event()
        self.stop_called = False
        self.disposed = False
        self.run_exception: BaseException | None = None
        # Sentinel — the run task awaits this so tests can finish run_async
        # at a deterministic moment.
        self.allow_finish = asyncio.Event()
        _StubNode.instances.append(self)

    async def run_async(self) -> None:
        self.run_started.set()
        await self.allow_finish.wait()
        if self.run_exception is not None:
            raise self.run_exception

    async def stop_async(self) -> None:
        self.stop_called = True
        # Releasing run_async on stop mirrors Nautilus's real shutdown.
        self.allow_finish.set()

    def dispose(self) -> None:
        self.disposed = True


@pytest.fixture(autouse=True)
def _reset_stub_node() -> None:
    _StubNode.instances.clear()


def _make_node_factory(
    crash_for: set[str] | None = None,
    raise_on_build_for: set[str] | None = None,
):
    """Return a callable usable as ``node_factory=`` parameter.

    The orchestrator passes ``account=, spec=`` keyword args. The
    callable returns a :class:`_StubNode` and optionally pre-loads it
    with a runtime crash exception or raises during build.
    """
    crash_for = crash_for or set()
    raise_on_build_for = raise_on_build_for or set()

    def _factory(*, account, spec):
        if account.id in raise_on_build_for:
            raise RuntimeError(f"build failed for {account.id}")
        node = _StubNode(account_id=account.id)
        if account.id in crash_for:
            node.run_exception = RuntimeError(f"runtime crash in {account.id}")
        return node

    return _factory


def _live(
    *,
    accounts: list[MagicMock],
    node_factory=None,
    with_validated_adapter: bool = True,
) -> LiveOrchestrator:
    return LiveOrchestrator(
        services=LiveServiceBundle(),
        account_manager=_account_manager(accounts),
        rule_assignment_service=_rule_assignment_service(),
        risk_registry=_risk_registry(),
        redis_manager=_redis_manager(),
        validated_adapter=MagicMock() if with_validated_adapter else None,
        audit_service=MagicMock(log_system_event_sync=AsyncMock()),
        node_factory=node_factory or _make_node_factory(),
        health_push_interval=10.0,  # disable noisy health publishes
    )


# ---------------------------------------------------------------------------
# Component build
# ---------------------------------------------------------------------------


class TestNodeAttached:
    @pytest.mark.asyncio
    async def test_node_built_when_full_live_deps_wired(self) -> None:
        live = _live(accounts=[_account("acct-1")])
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running
        node = session.components["trading_node"]
        assert isinstance(node, _StubNode)
        # Run task tracked in the orchestrator
        assert "acct-1" in live._node_run_tasks
        # ``run_async`` actually got scheduled
        await asyncio.wait_for(node.run_started.wait(), timeout=1.0)

        await live.stop()

    @pytest.mark.asyncio
    async def test_no_node_when_validated_adapter_missing(self) -> None:
        """Backwards compat — 10.5e1-shaped wiring still works."""
        live = _live(
            accounts=[_account("acct-1")],
            with_validated_adapter=False,
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running
        assert session.components["trading_node"] is None
        assert "acct-1" not in live._node_run_tasks

        await live.stop()

    @pytest.mark.asyncio
    async def test_no_node_when_bar_subscriptions_empty(self) -> None:
        """No symbols ⇒ no node; session still flips RUNNING."""
        account = _account("acct-1", symbols=[])
        live = _live(accounts=[account])
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running
        assert session.components["trading_node"] is None

        await live.stop()


# ---------------------------------------------------------------------------
# Lifecycle ordering
# ---------------------------------------------------------------------------


class TestLifecycleOrdering:
    @pytest.mark.asyncio
    async def test_stop_calls_stop_async_then_dispose(self) -> None:
        live = _live(accounts=[_account("acct-1")])
        await live.start()
        node = live.sessions["acct-1"].components["trading_node"]
        await asyncio.wait_for(node.run_started.wait(), timeout=1.0)

        await live.stop()

        assert node.stop_called is True
        assert node.disposed is True
        # Run task no longer tracked
        assert "acct-1" not in live._node_run_tasks

    @pytest.mark.asyncio
    async def test_stop_idempotent_for_node_without_run_task(self) -> None:
        """If ``run_async`` finished early, ``stop`` still disposes node."""
        live = _live(accounts=[_account("acct-1")])
        await live.start()
        node = live.sessions["acct-1"].components["trading_node"]
        # Force run task completion before stop()
        node.allow_finish.set()
        await asyncio.sleep(0)  # let the task notice the event
        # Wait until the orchestrator removes the run task ref.
        for _ in range(50):
            if "acct-1" not in live._node_run_tasks:
                break
            await asyncio.sleep(0.01)

        await live.stop()
        assert node.stop_called is True
        assert node.disposed is True


# ---------------------------------------------------------------------------
# Crash isolation (AC8)
# ---------------------------------------------------------------------------


class TestCrashIsolation:
    @pytest.mark.asyncio
    async def test_runtime_crash_marks_session_failed_and_pauses_account(
        self,
    ) -> None:
        crashing = _account("acct-bad")
        healthy = _account("acct-good")
        live = _live(
            accounts=[crashing, healthy],
            node_factory=_make_node_factory(crash_for={"acct-bad"}),
        )
        await live.start()

        bad_node = live.sessions["acct-bad"].components["trading_node"]
        good_node = live.sessions["acct-good"].components["trading_node"]
        await asyncio.wait_for(bad_node.run_started.wait(), timeout=1.0)
        await asyncio.wait_for(good_node.run_started.wait(), timeout=1.0)

        # Trigger the crash
        bad_node.allow_finish.set()

        # Wait for the orchestrator to react via _on_node_run_done →
        # _handle_node_run_crash. Watch the session state flip.
        for _ in range(100):
            if live.sessions["acct-bad"].is_failed:
                break
            await asyncio.sleep(0.01)

        assert live.sessions["acct-bad"].is_failed is True
        assert "runtime crash" in (
            live.sessions["acct-bad"].last_error or ""
        )
        # Healthy account untouched
        assert live.sessions["acct-good"].is_running is True
        # Pause was driven through the account_manager
        live._account_manager.pause_account.assert_any_call("acct-bad")

        await live.stop()

    @pytest.mark.asyncio
    async def test_build_failure_only_isolates_one_account(self) -> None:
        """If ``node_factory`` raises for one account, others still run."""
        a1 = _account("acct-broken")
        a2 = _account("acct-ok")
        live = _live(
            accounts=[a1, a2],
            node_factory=_make_node_factory(
                raise_on_build_for={"acct-broken"}
            ),
        )
        await live.start()

        assert live.sessions["acct-broken"].is_failed
        assert live.sessions["acct-ok"].is_running

        await live.stop()

    @pytest.mark.asyncio
    async def test_pause_failure_during_crash_does_not_re_raise(
        self,
    ) -> None:
        """If ``pause_account`` raises while isolating a crashed node,
        the orchestrator still marks the session FAILED and proceeds
        — the run-task's done-callback must never let an exception
        escape into the loop."""
        live = _live(
            accounts=[_account("acct-1")],
            node_factory=_make_node_factory(crash_for={"acct-1"}),
        )
        # Force the pause path to fail
        live._account_manager.pause_account = AsyncMock(
            side_effect=RuntimeError("pause exploded")
        )
        await live.start()

        node = live.sessions["acct-1"].components["trading_node"]
        await asyncio.wait_for(node.run_started.wait(), timeout=1.0)
        node.allow_finish.set()

        # Wait for crash propagation despite the pause failure.
        for _ in range(100):
            if live.sessions["acct-1"].is_failed:
                break
            await asyncio.sleep(0.01)

        assert live.sessions["acct-1"].is_failed
        # ``stop`` still completes cleanly with the broken pause path.
        await live.stop()

    @pytest.mark.asyncio
    async def test_done_callback_after_intentional_cancel_is_noop(
        self,
    ) -> None:
        """``stop()`` cancels the run task — the done-callback then fires
        with ``cancelled() == True`` and must not enter the crash path."""
        live = _live(accounts=[_account("acct-1")])
        await live.start()
        node = live.sessions["acct-1"].components["trading_node"]
        await asyncio.wait_for(node.run_started.wait(), timeout=1.0)

        await live.stop()

        # Session went STOPPED, not FAILED — cancellation is not a crash.
        from src.engine.account_session import SessionState

        assert live.sessions["acct-1"].state is SessionState.STOPPED
        # No crash-isolation task should have been queued.
        assert live._pending_isolation_tasks == set()
