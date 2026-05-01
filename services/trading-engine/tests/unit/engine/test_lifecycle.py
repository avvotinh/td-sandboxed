"""Unit tests for :class:`EngineLifecycle` (story 10.1)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.lifecycle import EngineLifecycle
from src.engine.recovery_orchestrator import RecoveryOutcome


def _make_outcome(**overrides) -> RecoveryOutcome:
    defaults = dict(
        crash_result=None,
        reconciliation_results=None,
        pnl_recalculation_results=None,
        resume_result=None,
        crash_recovery=None,
        cold_storage_writer=None,
    )
    defaults.update(overrides)
    return RecoveryOutcome(**defaults)


def _make_lifecycle(
    recovery_outcome: RecoveryOutcome | None = None,
    *,
    audit_service=None,
    redis_manager=None,
    account_manager=None,
):
    recovery = MagicMock()
    recovery.run = AsyncMock(
        return_value=recovery_outcome if recovery_outcome else _make_outcome()
    )
    recovery.zmq_adapter = None

    live = MagicMock()
    live.start = AsyncMock()
    live.stop = AsyncMock()
    live.cold_storage_service = None
    live.trade_db_writer = None
    live.violation_service = None

    lifecycle = EngineLifecycle(
        recovery=recovery,
        live=live,
        audit_service=audit_service,
        redis_manager=redis_manager,
        account_manager=account_manager,
        snapshot_service=None,
    )
    return lifecycle, recovery, live


@pytest.mark.asyncio
async def test_run_orchestrates_recovery_then_live_then_shutdown_signal():
    """run() invokes recovery → live.start → wait → live.stop in order."""
    outcome = _make_outcome()
    lifecycle, recovery, live = _make_lifecycle(outcome)

    # No graceful_shutdown is built when redis/account_manager are None,
    # so run() falls back to waiting on the internal shutdown event.
    import asyncio

    run_task = asyncio.create_task(lifecycle.run())
    await asyncio.sleep(0)  # let recovery + live.start complete
    # At this point recovery and live.start have been awaited; lifecycle is_running.
    while not lifecycle.is_running and not run_task.done():
        await asyncio.sleep(0)

    assert lifecycle.is_running is True
    recovery.run.assert_awaited_once()
    live.start.assert_awaited_once_with(outcome.cold_storage_writer)

    # Trigger fallback shutdown path
    await lifecycle.shutdown()
    await run_task

    live.stop.assert_awaited_once()
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_shutdown_idempotent_when_not_running():
    """shutdown() before run() is a no-op."""
    lifecycle, _, _ = _make_lifecycle()
    await lifecycle.shutdown()
    await lifecycle.shutdown()
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_recovery_outcome_properties_forward_to_lifecycle():
    """is_running false initially; outcome properties return None pre-run."""
    lifecycle, _, _ = _make_lifecycle()
    assert lifecycle.recovery_result is None
    assert lifecycle.reconciliation_results is None
    assert lifecycle.pnl_recalculation_results is None
    assert lifecycle.resume_result is None
    assert lifecycle.shutdown_result is None
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_on_lock_lost_triggers_shutdown_event():
    """Callback wired to RecoveryOrchestrator sets _shutdown_event and clears _running."""
    lifecycle, _, _ = _make_lifecycle()
    lifecycle._running = True
    lifecycle._on_lock_lost()
    assert lifecycle._running is False
    assert lifecycle._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_run_passes_on_lock_lost_callback_to_recovery():
    """recovery.run is invoked with the lifecycle's on_lock_lost callback."""
    lifecycle, recovery, _ = _make_lifecycle()

    import asyncio

    run_task = asyncio.create_task(lifecycle.run())
    while not lifecycle.is_running and not run_task.done():
        await asyncio.sleep(0)

    callback = recovery.run.await_args.args[0]
    assert callable(callback)
    assert callback == lifecycle._on_lock_lost

    await lifecycle.shutdown()
    await run_task


@pytest.mark.asyncio
async def test_run_passes_cold_storage_writer_from_recovery_to_live():
    """LiveOrchestrator.start receives the cold_storage_writer from recovery outcome."""
    cold_writer = MagicMock()
    outcome = _make_outcome(cold_storage_writer=cold_writer)
    lifecycle, _, live = _make_lifecycle(outcome)

    import asyncio

    run_task = asyncio.create_task(lifecycle.run())
    while not lifecycle.is_running and not run_task.done():
        await asyncio.sleep(0)

    live.start.assert_awaited_once_with(cold_writer)

    await lifecycle.shutdown()
    await run_task


@pytest.mark.asyncio
async def test_audit_engine_start_stop_emitted_when_audit_service_present():
    """audit_service receives engine_start + engine_stop + engine_stopped events."""
    audit_service = MagicMock()
    audit_service.log_system_event = AsyncMock()
    audit_service.stop = AsyncMock()

    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]
    outcome = _make_outcome(crash_result=crash_result)

    lifecycle, _, _ = _make_lifecycle(outcome, audit_service=audit_service)

    import asyncio

    run_task = asyncio.create_task(lifecycle.run())
    while not lifecycle.is_running and not run_task.done():
        await asyncio.sleep(0)

    await lifecycle.shutdown()
    await run_task

    event_subtypes = [
        c.kwargs["event_subtype"]
        for c in audit_service.log_system_event.await_args_list
    ]
    assert "engine_start" in event_subtypes
    assert "engine_stop" in event_subtypes
    assert "engine_stopped" in event_subtypes
    audit_service.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_graceful_shutdown_skipped_without_required_deps():
    """Without redis+account_manager, graceful_shutdown is not constructed."""
    lifecycle, _, _ = _make_lifecycle(redis_manager=None, account_manager=None)
    lifecycle._init_graceful_shutdown(crash_recovery=None)
    assert lifecycle._graceful_shutdown is None


@pytest.mark.asyncio
async def test_init_graceful_shutdown_built_when_deps_present():
    """With redis+account_manager, graceful_shutdown is constructed and registered."""
    redis_manager = MagicMock()
    account_manager = MagicMock()
    lifecycle, _, _ = _make_lifecycle(
        redis_manager=redis_manager, account_manager=account_manager
    )

    fake_graceful = MagicMock()
    with patch("src.engine.lifecycle.GracefulShutdown", return_value=fake_graceful):
        lifecycle._init_graceful_shutdown(crash_recovery=MagicMock())

    assert lifecycle._graceful_shutdown is fake_graceful
    fake_graceful.register_signal_handlers.assert_called_once()


@pytest.mark.asyncio
async def test_on_lock_lost_emits_audit_event():
    """_on_lock_lost should fire an ERROR audit event when audit_service set."""
    audit_service = MagicMock()
    audit_service.log_system_event = AsyncMock()
    lifecycle, _, _ = _make_lifecycle(audit_service=audit_service)
    lifecycle._on_lock_lost()
    import asyncio

    await asyncio.sleep(0)
    audit_service.log_system_event.assert_awaited()
    assert lifecycle._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_via_graceful_shutdown_when_present():
    """If graceful_shutdown is wired, shutdown() delegates to its trigger_shutdown."""
    lifecycle, _, _ = _make_lifecycle()
    lifecycle._running = True
    fake_graceful = MagicMock()
    lifecycle._graceful_shutdown = fake_graceful
    await lifecycle.shutdown()
    fake_graceful.trigger_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_invokes_crash_recovery_when_no_graceful():
    """No graceful_shutdown wired → fall back to crash_recovery.shutdown_sequence."""
    crash_recovery = MagicMock()
    crash_recovery.shutdown_sequence = AsyncMock()
    outcome = _make_outcome(crash_recovery=crash_recovery)
    lifecycle, _, _ = _make_lifecycle(outcome)
    lifecycle._running = True
    lifecycle._recovery_outcome = outcome
    await lifecycle.shutdown()
    crash_recovery.shutdown_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_via_graceful_shutdown_path():
    """When graceful_shutdown wired, run() awaits its wait_for_shutdown_signal."""
    redis_manager = MagicMock()
    account_manager = MagicMock()

    crash_recovery = MagicMock()
    outcome = _make_outcome(crash_recovery=crash_recovery)

    fake_shutdown_result = MagicMock()
    fake_shutdown_result.success = True

    fake_graceful = MagicMock()
    fake_graceful.wait_for_shutdown_signal = AsyncMock(
        return_value=fake_shutdown_result
    )
    fake_graceful.register_signal_handlers = MagicMock()

    lifecycle, _, _ = _make_lifecycle(
        outcome, redis_manager=redis_manager, account_manager=account_manager
    )

    with patch("src.engine.lifecycle.GracefulShutdown", return_value=fake_graceful):
        await lifecycle.run()

    assert lifecycle.shutdown_result is fake_shutdown_result
    fake_graceful.wait_for_shutdown_signal.assert_awaited_once()


def test_trade_db_writer_and_violation_service_forwarded_to_live():
    """Property forwarders return whatever LiveOrchestrator exposes."""
    lifecycle, _, live = _make_lifecycle()
    sentinel_writer = object()
    sentinel_violation = object()
    live.trade_db_writer = sentinel_writer
    live.violation_service = sentinel_violation
    assert lifecycle.trade_db_writer is sentinel_writer
    assert lifecycle.violation_service is sentinel_violation
