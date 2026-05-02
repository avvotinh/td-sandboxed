"""Story 10.5a — per-account session lifecycle tests for LiveOrchestrator.

Covers ``start()`` iterating active accounts, ``add_account`` /
``remove_account`` / ``reload_account`` runtime hot-swap, crash
isolation pausing the failed account while others continue, and the
synchronous ``health()`` snapshot.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine.account_session import SessionState
from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator


def _make_account_manager(active_ids: list[str]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=list(active_ids))
    am.pause_account = AsyncMock()
    return am


def _make_audit_service() -> MagicMock:
    audit = MagicMock()
    audit.log_system_event_sync = AsyncMock()
    return audit


@pytest.mark.asyncio
async def test_start_without_account_manager_skips_session_loop() -> None:
    """Backward-compat: bundle-only ``LiveOrchestrator`` continues to work."""
    live = LiveOrchestrator(services=LiveServiceBundle())
    await live.start()
    await live.stop()
    assert live.sessions == {}


@pytest.mark.asyncio
async def test_start_creates_one_session_per_active_account() -> None:
    am = _make_account_manager(["acct-a", "acct-b", "acct-c"])
    live = LiveOrchestrator(
        services=LiveServiceBundle(),
        account_manager=am,
    )
    await live.start()

    sessions = live.sessions
    assert set(sessions) == {"acct-a", "acct-b", "acct-c"}
    assert all(s.is_running for s in sessions.values())

    await live.stop()
    assert all(
        s.state is SessionState.STOPPED for s in live.sessions.values()
    )


@pytest.mark.asyncio
async def test_add_account_hot_adds_session() -> None:
    am = _make_account_manager(["acct-a"])
    live = LiveOrchestrator(services=LiveServiceBundle(), account_manager=am)
    await live.start()

    new_session = await live.add_account("acct-b")
    assert new_session.is_running is True
    assert "acct-b" in live.sessions

    await live.stop()


@pytest.mark.asyncio
async def test_add_account_idempotent_for_running_account() -> None:
    am = _make_account_manager(["acct-a"])
    live = LiveOrchestrator(services=LiveServiceBundle(), account_manager=am)
    await live.start()

    first = live.sessions["acct-a"]
    again = await live.add_account("acct-a")
    assert again is first  # same instance, no double-start

    await live.stop()


@pytest.mark.asyncio
async def test_add_account_requires_account_manager() -> None:
    live = LiveOrchestrator(services=LiveServiceBundle())
    with pytest.raises(RuntimeError, match="account_manager"):
        await live.add_account("acct-x")


@pytest.mark.asyncio
async def test_remove_account_stops_and_drops_session() -> None:
    am = _make_account_manager(["acct-a", "acct-b"])
    live = LiveOrchestrator(services=LiveServiceBundle(), account_manager=am)
    await live.start()

    await live.remove_account("acct-a")
    assert "acct-a" not in live.sessions
    assert "acct-b" in live.sessions  # untouched

    await live.stop()


@pytest.mark.asyncio
async def test_remove_account_unknown_is_noop() -> None:
    am = _make_account_manager([])
    live = LiveOrchestrator(services=LiveServiceBundle(), account_manager=am)
    await live.remove_account("does-not-exist")  # must not raise


@pytest.mark.asyncio
async def test_reload_account_recreates_session() -> None:
    am = _make_account_manager(["acct-a"])
    live = LiveOrchestrator(services=LiveServiceBundle(), account_manager=am)
    await live.start()

    original = live.sessions["acct-a"]
    reloaded = await live.reload_account("acct-a")

    assert reloaded is not original
    assert reloaded.is_running is True
    assert "acct-a" in live.sessions

    await live.stop()


# --- Crash isolation (AC8 skeleton) ---------------------------------------


class _ExplodingOrchestrator(LiveOrchestrator):
    """Test seam — fails session start for accounts in the explode set."""

    def __init__(self, *args, explode_for: set[str], **kwargs):
        super().__init__(*args, **kwargs)
        self._explode_for = explode_for

    async def _build_session_components(self, session) -> None:  # type: ignore[no-untyped-def]
        if session.account_id in self._explode_for:
            raise RuntimeError(f"boom for {session.account_id}")
        return None


@pytest.mark.asyncio
async def test_start_isolates_per_account_failures() -> None:
    am = _make_account_manager(["acct-a", "acct-b", "acct-c"])
    audit = _make_audit_service()

    live = _ExplodingOrchestrator(
        services=LiveServiceBundle(),
        account_manager=am,
        audit_service=audit,
        explode_for={"acct-b"},
    )
    await live.start()

    sessions = live.sessions
    assert sessions["acct-a"].is_running is True
    assert sessions["acct-c"].is_running is True
    assert sessions["acct-b"].is_failed is True
    assert "boom" in (sessions["acct-b"].last_error or "")

    am.pause_account.assert_awaited_once_with("acct-b")
    audit.log_system_event_sync.assert_awaited()
    call = audit.log_system_event_sync.call_args
    assert call.kwargs["event_subtype"] == "node_crashed"
    assert call.kwargs["account_id"] == "acct-b"

    await live.stop()


@pytest.mark.asyncio
async def test_pause_failure_is_swallowed() -> None:
    """If pause_account raises (no prior state), still record audit + continue."""
    am = _make_account_manager(["acct-a"])
    am.pause_account = AsyncMock(side_effect=ValueError("no prior state"))
    audit = _make_audit_service()

    live = _ExplodingOrchestrator(
        services=LiveServiceBundle(),
        account_manager=am,
        audit_service=audit,
        explode_for={"acct-a"},
    )
    await live.start()  # must not raise

    assert live.sessions["acct-a"].is_failed is True
    audit.log_system_event_sync.assert_awaited()


# --- Health snapshot (AC7 skeleton) ---------------------------------------


@pytest.mark.asyncio
async def test_health_reflects_running_and_failed() -> None:
    am = _make_account_manager(["acct-a", "acct-b"])
    live = _ExplodingOrchestrator(
        services=LiveServiceBundle(),
        account_manager=am,
        audit_service=_make_audit_service(),
        explode_for={"acct-b"},
    )
    await live.start()

    health = live.health()
    assert health.accounts_running == 1
    assert ("acct-b", health.accounts_failed[0][1]) in [
        (aid, err) for aid, err in health.accounts_failed
    ]
    assert "boom" in health.accounts_failed[0][1]

    await live.stop()


# --- Stop ordering --------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_tears_down_sessions_before_services() -> None:
    """Sessions stop before bundled services so they cannot post writes
    to a service that has already torn down (e.g. trade_db_writer)."""
    am = _make_account_manager(["acct-a"])

    teardown_order: list[str] = []

    class _TrackingOrchestrator(LiveOrchestrator):
        async def _teardown_session_components(self, session) -> None:  # type: ignore[no-untyped-def]
            teardown_order.append(f"session:{session.account_id}")

    trade_writer = AsyncMock()
    trade_writer.start = AsyncMock()
    trade_writer.stop = AsyncMock(
        side_effect=lambda *a, **kw: teardown_order.append("trade_writer")
    )

    live = _TrackingOrchestrator(
        services=LiveServiceBundle(trade_db_writer=trade_writer),
        account_manager=am,
    )
    await live.start()
    await live.stop()

    assert teardown_order == ["session:acct-a", "trade_writer"]
