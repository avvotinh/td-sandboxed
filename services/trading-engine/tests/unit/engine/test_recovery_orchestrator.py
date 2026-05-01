"""Unit tests for :class:`RecoveryOrchestrator` (story 10.2 — pre-built collaborators)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.collaborators import RecoveryCollaborators
from src.engine.recovery_orchestrator import RecoveryOrchestrator, RecoveryOutcome


def _orchestrator(
    collaborators: RecoveryCollaborators | None = None,
    risk_registry=None,
    audit_service=None,
) -> RecoveryOrchestrator:
    return RecoveryOrchestrator(
        collaborators=collaborators or RecoveryCollaborators(),
        risk_registry=risk_registry,
        audit_service=audit_service,
    )


@pytest.mark.asyncio
async def test_run_returns_empty_outcome_when_no_crash_recovery():
    """No CrashRecoveryManager → recovery skipped, outcome is empty."""
    outcome = await _orchestrator().run()

    assert outcome == RecoveryOutcome(
        crash_result=None,
        reconciliation_results=None,
        pnl_recalculation_results=None,
        resume_result=None,
        crash_recovery=None,
        cold_storage_writer=None,
    )


@pytest.mark.asyncio
async def test_run_no_recovery_mode_returns_crash_result_only():
    """Healthy boot — startup_sequence returns recovery_mode=False, no further work."""
    crash_result = MagicMock()
    crash_result.recovery_mode = False
    crash_result.accounts_needing_recovery = []

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(crash_recovery=fake_crash)
    )

    outcome = await orchestrator.run()

    assert outcome.crash_result is crash_result
    assert outcome.crash_recovery is fake_crash
    assert outcome.reconciliation_results is None
    assert outcome.pnl_recalculation_results is None
    assert outcome.resume_result is None


@pytest.mark.asyncio
async def test_run_recovery_mode_runs_full_pipeline():
    """recovery_mode=True with all collaborators → reconciler/pnl/resume invoked."""
    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash.clear_crash_indicators = AsyncMock()
    fake_crash.validate_snapshot_for_recovery = AsyncMock(return_value=(True, None))

    fake_reconciler = MagicMock()

    recon_result = MagicMock()
    recon_result.success = True
    recon_result.requires_manual_intervention = False

    pnl_result = MagicMock()
    pnl_result.success = True
    pnl_result.adjustment = Decimal("0")

    resume_result = MagicMock()

    fake_recalculator = MagicMock()
    fake_recalculator.recalculate_daily_pnl = AsyncMock(return_value=pnl_result)
    fake_recalculator.apply_recalculation = AsyncMock()

    fake_resumer = MagicMock()
    fake_resumer.resume_trading_after_recovery = AsyncMock(return_value=resume_result)

    cold_writer = MagicMock()

    risk_registry = MagicMock()
    risk_registry.get_risk_state = MagicMock(return_value=None)

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(
            crash_recovery=fake_crash,
            position_reconciler=fake_reconciler,
            pnl_recalculator=fake_recalculator,
            trading_resumer=fake_resumer,
            cold_storage_writer=cold_writer,
        ),
        risk_registry=risk_registry,
    )

    with patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ):
        outcome = await orchestrator.run()

    assert outcome.reconciliation_results == {"acct-1": recon_result}
    assert outcome.pnl_recalculation_results == {"acct-1": pnl_result}
    assert outcome.resume_result is resume_result
    assert outcome.cold_storage_writer is cold_writer
    fake_crash.clear_crash_indicators.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_blocked_account_skips_pnl_and_resume():
    """If reconciliation requires manual intervention, indicators NOT cleared."""
    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash.clear_crash_indicators = AsyncMock()

    recon_result = MagicMock()
    recon_result.success = False
    recon_result.requires_manual_intervention = True

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(
            crash_recovery=fake_crash,
            position_reconciler=MagicMock(),
        ),
    )

    with patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ):
        outcome = await orchestrator.run()

    assert outcome.pnl_recalculation_results is None
    assert outcome.resume_result is None
    fake_crash.clear_crash_indicators.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_systemexit_when_startup_runtime_error():
    """RuntimeError from startup_sequence → SystemExit(1) per legacy behavior."""
    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(
        side_effect=RuntimeError("another instance running")
    )

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(crash_recovery=fake_crash)
    )

    with pytest.raises(SystemExit) as excinfo:
        await orchestrator.run()

    assert excinfo.value.code == 1


@pytest.mark.asyncio
async def test_run_no_reconciler_clears_indicators_without_reconciliation():
    """recovery_mode=True but no PositionReconciler → skip reconciliation."""
    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash.clear_crash_indicators = AsyncMock()

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(crash_recovery=fake_crash)
    )

    outcome = await orchestrator.run()

    assert outcome.reconciliation_results is None
    fake_crash.clear_crash_indicators.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_pnl_skipped_when_recalculator_missing():
    """All reconciled but no DailyPnLRecalculator → empty pnl results, resume fallback."""
    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash.clear_crash_indicators = AsyncMock()

    recon_result = MagicMock()
    recon_result.success = True
    recon_result.requires_manual_intervention = False

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(
            crash_recovery=fake_crash,
            position_reconciler=MagicMock(),
            # pnl_recalculator + trading_resumer absent
        ),
    )

    with patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ):
        outcome = await orchestrator.run()

    assert outcome.pnl_recalculation_results == {}
    assert outcome.resume_result is not None
    assert outcome.resume_result.success is False
    assert outcome.resume_result.recovery_duration == timedelta(0)


@pytest.mark.asyncio
async def test_audit_event_emitted_on_recovery_mode():
    """audit_service receives ``crash_recovery`` event when recovery_mode triggered."""
    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash = MagicMock()
    fake_crash.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash.clear_crash_indicators = AsyncMock()

    audit = MagicMock()
    audit.log_system_event = AsyncMock()

    orchestrator = _orchestrator(
        collaborators=RecoveryCollaborators(crash_recovery=fake_crash),
        audit_service=audit,
    )

    await orchestrator.run()

    import asyncio

    await asyncio.sleep(0)
    audit.log_system_event.assert_awaited()
    assert audit.log_system_event.await_args.kwargs["event_subtype"] == "crash_recovery"
