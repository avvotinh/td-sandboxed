"""Story 10.5e1 tests — per-account component build + health surface push.

Covers the wiring extension on :class:`LiveOrchestrator`:

- ``_build_session_components`` resolves the per-account ``RuleEngine``
  via ``RuleAssignmentService``, builds the
  ``PropFirmComplianceActor`` through the shared factory, computes
  ``bar_subscriptions`` from ``account.signal_filter.symbols``, and
  attaches everything onto the :class:`LiveAccountSession`.
- ``_health_push_loop`` SETEXes a JSON snapshot to
  ``health:trading-engine`` every ``health_push_interval`` seconds.
- The orchestrator continues to start cleanly when only the partial
  set of deps is wired (backwards compat with 10.5a callers).
"""
from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine.account_session import LiveAccountSession
from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import (
    HEALTH_REDIS_KEY,
    HEALTH_REDIS_TTL_SECONDS,
    LiveOrchestrator,
)


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


def _account(
    account_id: str = "acct-1",
    symbols: list[str] | None = None,
) -> MagicMock:
    """Build a duck-typed account config with a signal_filter."""
    sym = symbols if symbols is not None else ["XAUUSD", "EURUSD"]
    sig_filter = MagicMock()
    sig_filter.symbols = sym

    cfg = MagicMock()
    cfg.id = account_id
    cfg.signal_filter = sig_filter
    return cfg


def _account_manager(active: list[MagicMock]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=[a.id for a in active])
    am.get_account = MagicMock(side_effect=lambda aid: next(
        (a for a in active if a.id == aid), None
    ))
    am.pause_account = AsyncMock()
    return am


def _rule_assignment_service(rules: list | None = None) -> MagicMock:
    svc = MagicMock()
    svc.get_rules_for_account = MagicMock(return_value=list(rules or []))
    return svc


def _risk_registry(starting_balance: Decimal = Decimal("100000")) -> MagicMock:
    state = MagicMock()
    state.daily_starting_balance = starting_balance
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=state)
    return registry


def _redis_manager() -> tuple[MagicMock, MagicMock]:
    """Return ``(manager, client)`` so tests can assert on .setex()."""
    client = MagicMock()
    client.setex = AsyncMock()
    manager = MagicMock()
    # ``client`` is a property in the real class — use a normal attribute so
    # MagicMock returns the same object every access.
    type(manager).client = MagicMock(return_value=client)
    manager.client = client
    return manager, client


# -------------------------------------------------------------------------
# _build_session_components
# -------------------------------------------------------------------------


class TestComponentBuild:
    @pytest.mark.asyncio
    async def test_resolves_rule_engine_compliance_actor_and_subscriptions(
        self,
    ) -> None:
        account = _account("acct-1", symbols=["XAUUSD", "EURUSD"])
        am = _account_manager([account])
        ras = _rule_assignment_service(rules=[])
        risk = _risk_registry(Decimal("250000"))

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running

        components = session.components
        assert "rule_engine" in components
        assert components["rule_engine"].account_id == "acct-1"
        assert "compliance_actor" in components
        assert components["initial_balance"] == Decimal("250000")
        # bar_subscriptions = symbols × default timeframes (("1m",))
        assert sorted(components["bar_subscriptions"]) == [
            ("EURUSD", "1m"),
            ("XAUUSD", "1m"),
        ]

        ras.get_rules_for_account.assert_called_once_with(account)
        await live.stop()

    @pytest.mark.asyncio
    async def test_no_signal_filter_symbols_yields_empty_subscriptions(
        self,
    ) -> None:
        account = _account("acct-1", symbols=[])
        am = _account_manager([account])
        ras = _rule_assignment_service()
        risk = _risk_registry()

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.components["bar_subscriptions"] == []
        await live.stop()

    @pytest.mark.asyncio
    async def test_initial_balance_falls_back_to_zero_without_risk_state(
        self,
    ) -> None:
        account = _account("acct-1")
        am = _account_manager([account])
        ras = _rule_assignment_service()

        # No risk_registry wired
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.components["initial_balance"] == Decimal("0")
        await live.stop()

    @pytest.mark.asyncio
    async def test_unknown_account_fails_session_with_clear_error(self) -> None:
        # AccountManager reports active id but get_account returns None
        account = _account("acct-known")
        am = _account_manager([account])
        am.get_account = MagicMock(return_value=None)  # always None
        ras = _rule_assignment_service()

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            audit_service=MagicMock(
                log_system_event_sync=AsyncMock()
            ),
        )
        await live.start()

        session = live.sessions["acct-known"]
        assert session.is_failed
        assert "missing from AccountManager" in (session.last_error or "")
        await live.stop()

    @pytest.mark.asyncio
    async def test_no_rule_assignment_service_skips_component_build(
        self,
    ) -> None:
        """Backward compat: 10.5a-style construction (no RAS) still works."""
        account = _account("acct-1")
        am = _account_manager([account])

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            # rule_assignment_service intentionally absent
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running
        assert session.components == {}
        await live.stop()


# -------------------------------------------------------------------------
# Health surface push
# -------------------------------------------------------------------------


class TestHealthPush:
    @pytest.mark.asyncio
    async def test_health_snapshot_serialises_to_json_with_required_fields(
        self,
    ) -> None:
        live = LiveOrchestrator(services=LiveServiceBundle())
        snapshot = live.health()
        payload = snapshot.to_redis_payload()
        decoded = json.loads(payload)

        assert decoded["accounts_running"] == 0
        assert decoded["accounts_failed"] == []
        # ts populated from utcnow() in iso format
        assert "T" in decoded["ts"]

    @pytest.mark.asyncio
    async def test_publish_calls_setex_with_correct_key_and_ttl(self) -> None:
        manager, client = _redis_manager()
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            redis_manager=manager,
        )

        await live._publish_health_snapshot()

        client.setex.assert_awaited_once()
        key, ttl, payload = client.setex.call_args.args
        assert key == HEALTH_REDIS_KEY
        assert ttl == HEALTH_REDIS_TTL_SECONDS
        decoded = json.loads(payload)
        assert "accounts_running" in decoded

    @pytest.mark.asyncio
    async def test_publish_is_noop_without_redis_manager(self) -> None:
        live = LiveOrchestrator(services=LiveServiceBundle())
        # Must not raise even though no Redis is wired
        await live._publish_health_snapshot()

    @pytest.mark.asyncio
    async def test_loop_starts_and_publishes_at_least_once(self) -> None:
        manager, client = _redis_manager()
        am = _account_manager([_account("acct-1")])
        ras = _rule_assignment_service()
        risk = _risk_registry()

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
            redis_manager=manager,
            health_push_interval=0.01,
        )
        await live.start()
        # Wait for at least one tick
        for _ in range(50):
            if client.setex.await_count >= 1:
                break
            await asyncio.sleep(0.01)
        await live.stop()

        assert client.setex.await_count >= 1

    @pytest.mark.asyncio
    async def test_loop_survives_redis_failure(self) -> None:
        """A SETEX failure shouldn't kill the loop — next tick retries."""
        manager, client = _redis_manager()

        call_log: list[bool] = []

        async def _flaky_setex(*args, **kwargs):
            call_log.append(True)
            if len(call_log) == 1:
                raise RuntimeError("redis hiccup")

        client.setex = AsyncMock(side_effect=_flaky_setex)

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            redis_manager=manager,
            health_push_interval=0.01,
        )
        await live.start()
        for _ in range(50):
            if len(call_log) >= 2:
                break
            await asyncio.sleep(0.01)
        await live.stop()

        assert len(call_log) >= 2  # retried after the failure


# -------------------------------------------------------------------------
# Stop ordering
# -------------------------------------------------------------------------


class TestStopOrdering:
    @pytest.mark.asyncio
    async def test_health_task_cancelled_before_session_teardown(self) -> None:
        manager, client = _redis_manager()

        teardown_log: list[str] = []

        class _TrackingOrchestrator(LiveOrchestrator):
            async def _publish_health_snapshot(self) -> None:
                teardown_log.append("health_tick")

            async def _teardown_session_components(
                self, session: LiveAccountSession
            ) -> None:
                teardown_log.append(f"session_teardown:{session.account_id}")

        am = _account_manager([_account("acct-a")])
        ras = _rule_assignment_service()

        live = _TrackingOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            redis_manager=manager,
            health_push_interval=0.005,
        )
        await live.start()
        # wait for at least one health tick to arrive in the log
        for _ in range(50):
            if "health_tick" in teardown_log:
                break
            await asyncio.sleep(0.005)

        teardown_log.clear()  # reset before stop
        await live.stop()

        # First teardown action after stop must be the session, not a
        # final health tick — health task is cancelled first.
        assert teardown_log[0].startswith("session_teardown:")
        # No health_tick should appear AFTER session teardown began
        assert "health_tick" not in teardown_log
