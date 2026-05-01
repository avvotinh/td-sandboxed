"""Unit tests for :class:`EngineLifecycle` (story 10.2 — pre-built deps)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.engine.lifecycle import EngineLifecycle
from src.engine.lock_lost import LockLostMediator
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
    graceful_shutdown=None,
):
    recovery = MagicMock()
    recovery.run = AsyncMock(
        return_value=recovery_outcome if recovery_outcome else _make_outcome()
    )

    live = MagicMock()
    live.start = AsyncMock()
    live.stop = AsyncMock()
    live.cold_storage_service = None
    live.trade_db_writer = None
    live.violation_service = None

    mediator = LockLostMediator()
    lifecycle = EngineLifecycle(
        recovery=recovery,
        live=live,
        graceful_shutdown=graceful_shutdown,
        audit_service=audit_service,
        lock_lost_mediator=mediator,
    )
    return lifecycle, recovery, live, mediator


@pytest.mark.asyncio
async def test_run_orchestrates_recovery_then_live_then_shutdown_signal():
    """run() invokes recovery → live.start → wait → live.stop in order."""
    outcome = _make_outcome()
    lifecycle, recovery, live, _ = _make_lifecycle(outcome)

    run_task = asyncio.create_task(lifecycle.run())
    while not lifecycle.is_running and not run_task.done():
        await asyncio.sleep(0)

    assert lifecycle.is_running is True
    recovery.run.assert_awaited_once()
    live.start.assert_awaited_once_with()

    await lifecycle.shutdown()
    await run_task

    live.stop.assert_awaited_once()
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_shutdown_idempotent_when_not_running():
    lifecycle, _, _, _ = _make_lifecycle()
    await lifecycle.shutdown()
    await lifecycle.shutdown()
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_recovery_outcome_properties_forward_to_lifecycle():
    lifecycle, _, _, _ = _make_lifecycle()
    assert lifecycle.recovery_result is None
    assert lifecycle.reconciliation_results is None
    assert lifecycle.pnl_recalculation_results is None
    assert lifecycle.resume_result is None
    assert lifecycle.shutdown_result is None
    assert lifecycle.is_running is False


@pytest.mark.asyncio
async def test_on_lock_lost_triggers_shutdown_event():
    lifecycle, _, _, _ = _make_lifecycle()
    lifecycle._running = True
    lifecycle._on_lock_lost()
    assert lifecycle._running is False
    assert lifecycle._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_lock_lost_mediator_routes_to_lifecycle_handler():
    """Constructor binds the mediator → lifecycle._on_lock_lost."""
    lifecycle, _, _, mediator = _make_lifecycle()
    lifecycle._running = True
    mediator()  # invoke mediator as if from CrashRecoveryManager
    assert lifecycle._running is False
    assert lifecycle._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_run_with_graceful_shutdown_late_binds_recovery_artifacts():
    """When graceful_shutdown is wired, run() late-binds recovery artifacts."""
    crash_recovery = MagicMock()
    cold_storage = MagicMock()
    outcome = _make_outcome(crash_recovery=crash_recovery)

    fake_shutdown_result = MagicMock()
    fake_shutdown_result.success = True

    fake_graceful = MagicMock()
    fake_graceful.bind_recovery_artifacts = MagicMock()
    fake_graceful.register_signal_handlers = MagicMock()
    fake_graceful.wait_for_shutdown_signal = AsyncMock(return_value=fake_shutdown_result)

    lifecycle, _, live, _ = _make_lifecycle(outcome, graceful_shutdown=fake_graceful)
    live.cold_storage_service = cold_storage

    await lifecycle.run()

    fake_graceful.bind_recovery_artifacts.assert_called_once_with(
        crash_recovery=crash_recovery,
        cold_storage_service=cold_storage,
    )
    fake_graceful.register_signal_handlers.assert_called_once()
    assert lifecycle.shutdown_result is fake_shutdown_result


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

    lifecycle, _, _, _ = _make_lifecycle(outcome, audit_service=audit_service)

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
async def test_on_lock_lost_emits_audit_event():
    audit_service = MagicMock()
    audit_service.log_system_event = AsyncMock()
    lifecycle, _, _, _ = _make_lifecycle(audit_service=audit_service)
    lifecycle._on_lock_lost()
    await asyncio.sleep(0)
    audit_service.log_system_event.assert_awaited()
    assert lifecycle._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_shutdown_via_graceful_shutdown_when_present():
    fake_graceful = MagicMock()
    lifecycle, _, _, _ = _make_lifecycle(graceful_shutdown=fake_graceful)
    lifecycle._running = True
    await lifecycle.shutdown()
    fake_graceful.trigger_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_invokes_crash_recovery_when_no_graceful():
    crash_recovery = MagicMock()
    crash_recovery.shutdown_sequence = AsyncMock()
    outcome = _make_outcome(crash_recovery=crash_recovery)
    lifecycle, _, _, _ = _make_lifecycle(outcome)
    lifecycle._running = True
    lifecycle._recovery_outcome = outcome
    await lifecycle.shutdown()
    crash_recovery.shutdown_sequence.assert_awaited_once()


def test_trade_db_writer_and_violation_service_forwarded_to_live():
    lifecycle, _, live, _ = _make_lifecycle()
    sentinel_writer = object()
    sentinel_violation = object()
    live.trade_db_writer = sentinel_writer
    live.violation_service = sentinel_violation
    assert lifecycle.trade_db_writer is sentinel_writer
    assert lifecycle.violation_service is sentinel_violation
