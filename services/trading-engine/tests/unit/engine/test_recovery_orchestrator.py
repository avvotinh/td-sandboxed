"""Unit tests for :class:`RecoveryOrchestrator` (story 10.1)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.recovery_orchestrator import RecoveryOrchestrator, RecoveryOutcome


def _on_lock_lost() -> None:
    """No-op callback for tests that do not exercise lock loss."""


@pytest.mark.asyncio
async def test_run_returns_empty_outcome_when_redis_missing():
    """No Redis manager → recovery skipped, outcome is empty."""
    orchestrator = RecoveryOrchestrator(
        redis_manager=None,
        zmq_adapter=None,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    outcome = await orchestrator.run(_on_lock_lost)

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
    redis_manager = MagicMock()

    crash_result = MagicMock()
    crash_result.recovery_mode = False
    crash_result.accounts_needing_recovery = []

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(return_value=crash_result)

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=None,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ):
        outcome = await orchestrator.run(_on_lock_lost)

    assert outcome.crash_result is crash_result
    assert outcome.crash_recovery is fake_crash_recovery
    assert outcome.reconciliation_results is None
    assert outcome.pnl_recalculation_results is None
    assert outcome.resume_result is None


@pytest.mark.asyncio
async def test_run_recovery_mode_runs_full_pipeline():
    """recovery_mode=True with all deps → reconciler/pnl/resume invoked, indicators cleared."""
    redis_manager = MagicMock()
    zmq_adapter = MagicMock()
    risk_registry = MagicMock()
    risk_registry.get_risk_state = MagicMock(return_value=None)

    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash_recovery.clear_crash_indicators = AsyncMock()
    fake_crash_recovery.validate_snapshot_for_recovery = AsyncMock(
        return_value=(True, None)
    )

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

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=zmq_adapter,
        db_session_factory=MagicMock(),
        risk_registry=risk_registry,
        pnl_registry=MagicMock(),
        account_manager=MagicMock(),
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ), patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ), patch(
        "src.engine.recovery_orchestrator.DailyPnLRecalculator",
        return_value=fake_recalculator,
    ), patch(
        "src.engine.recovery_orchestrator.TradingResumer",
        return_value=fake_resumer,
    ):
        outcome = await orchestrator.run(_on_lock_lost)

    assert outcome.reconciliation_results == {"acct-1": recon_result}
    assert outcome.pnl_recalculation_results == {"acct-1": pnl_result}
    assert outcome.resume_result is resume_result
    fake_crash_recovery.clear_crash_indicators.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_blocked_account_skips_pnl_and_resume():
    """If reconciliation requires manual intervention, indicators NOT cleared."""
    redis_manager = MagicMock()
    zmq_adapter = MagicMock()

    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash_recovery.clear_crash_indicators = AsyncMock()

    recon_result = MagicMock()
    recon_result.success = False
    recon_result.requires_manual_intervention = True

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=zmq_adapter,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ), patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ):
        outcome = await orchestrator.run(_on_lock_lost)

    assert outcome.pnl_recalculation_results is None
    assert outcome.resume_result is None
    fake_crash_recovery.clear_crash_indicators.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_systemexit_when_startup_runtime_error():
    """RuntimeError from startup_sequence → SystemExit(1) per legacy behavior."""
    redis_manager = MagicMock()

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(
        side_effect=RuntimeError("another instance running")
    )

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=None,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ), pytest.raises(SystemExit) as excinfo:
        await orchestrator.run(_on_lock_lost)

    assert excinfo.value.code == 1


@pytest.mark.asyncio
async def test_run_no_zmq_adapter_clears_indicators_without_reconciliation():
    """recovery_mode=True but no ZMQ adapter → skip reconciliation, clear indicators."""
    redis_manager = MagicMock()

    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash_recovery.clear_crash_indicators = AsyncMock()

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=None,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ):
        outcome = await orchestrator.run(_on_lock_lost)

    assert outcome.reconciliation_results is None
    fake_crash_recovery.clear_crash_indicators.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_pnl_skipped_when_required_deps_missing():
    """All reconciled but missing pnl deps → empty pnl results, resume gracefully degrades."""
    redis_manager = MagicMock()
    zmq_adapter = MagicMock()

    crash_result = MagicMock()
    crash_result.recovery_mode = True
    crash_result.accounts_needing_recovery = ["acct-1"]

    fake_crash_recovery = MagicMock()
    fake_crash_recovery.startup_sequence = AsyncMock(return_value=crash_result)
    fake_crash_recovery.clear_crash_indicators = AsyncMock()

    recon_result = MagicMock()
    recon_result.success = True
    recon_result.requires_manual_intervention = False

    orchestrator = RecoveryOrchestrator(
        redis_manager=redis_manager,
        zmq_adapter=zmq_adapter,
        db_session_factory=None,
        risk_registry=None,
        pnl_registry=None,
        account_manager=None,
        firm_registry=None,
        audit_service=None,
        database_url=None,
    )

    with patch(
        "src.engine.recovery_orchestrator.CrashRecoveryManager",
        return_value=fake_crash_recovery,
    ), patch(
        "src.engine.recovery_orchestrator.run_position_reconciliation",
        new=AsyncMock(return_value={"acct-1": recon_result}),
    ):
        outcome = await orchestrator.run(_on_lock_lost)

    assert outcome.pnl_recalculation_results == {}
    # Resume returns success=False fallback when redis_manager+account_manager missing
    assert outcome.resume_result is not None
    assert outcome.resume_result.success is False
    assert outcome.resume_result.recovery_duration == timedelta(0)
