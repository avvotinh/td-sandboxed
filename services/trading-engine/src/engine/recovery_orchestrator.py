"""RecoveryOrchestrator — owns the cold-start recovery flow.

Story 10.1 extracted the recovery sequence (crash detection, position
reconciliation, daily P&L recompute, trading resume) into this class.
Story 10.2 swaps the raw-deps constructor for pre-built collaborators
supplied by the DI container, matching the spec sketch in
``docs/sprint-artifacts/10-1-engine-split.md``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ..accounts.risk_registry import RiskStateRegistry
from ..audit.audit_service import AuditService
from ..rules.audit_logger import audit_task_done_callback
from ..state.cold_storage_writer import ColdStorageWriter
from ..state.crash_recovery import CrashRecoveryManager
from ..state.crash_recovery import RecoveryResult as CrashRecoveryResult
from ..state.daily_pnl_recalculator import RecalculationResult
from ..state.position_reconciler import (
    ReconciliationResult,
    run_position_reconciliation,
)
from ..state.trading_resumer import ResumeResult
from .collaborators import RecoveryCollaborators

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryOutcome:
    """Aggregated artifacts produced by :meth:`RecoveryOrchestrator.run`.

    The :class:`CrashRecoveryManager` and :class:`ColdStorageWriter`
    references are forwarded to downstream lifecycle stages (graceful
    shutdown, cold storage service) which need to share the same
    long-lived instances.
    """

    crash_result: CrashRecoveryResult | None
    reconciliation_results: dict[str, ReconciliationResult] | None
    pnl_recalculation_results: dict[str, RecalculationResult] | None
    resume_result: ResumeResult | None
    crash_recovery: CrashRecoveryManager | None
    cold_storage_writer: ColdStorageWriter | None


class RecoveryOrchestrator:
    """Orchestrates crash recovery, reconciliation, P&L recompute, and resume."""

    def __init__(
        self,
        collaborators: RecoveryCollaborators,
        risk_registry: RiskStateRegistry | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Build with pre-built recovery collaborators.

        ``risk_registry`` is needed only by the P&L recompute step to
        snapshot the per-account daily P&L base; ``audit_service`` is
        used to log the ``crash_recovery`` system event when recovery
        mode kicks in.
        """
        self._collaborators = collaborators
        self._risk_registry = risk_registry
        self._audit_service = audit_service

    async def run(self) -> RecoveryOutcome:
        """Execute the recovery flow. Behavior matches the engine.py baseline.

        The lock-loss callback is bound onto :class:`CrashRecoveryManager`
        at construction time via :class:`LockLostMediator` — this method
        does not take it as a parameter.
        """
        crash_recovery = self._collaborators.crash_recovery
        if crash_recovery is None:
            logger.info("No crash recovery configured, skipping recovery flow")
            return RecoveryOutcome(None, None, None, None, None, None)

        try:
            crash_result = await crash_recovery.startup_sequence()
        except RuntimeError as e:
            logger.critical("Engine startup failed: %s", e)
            raise SystemExit(1) from e

        reconciliation_results: dict[str, ReconciliationResult] | None = None
        pnl_results: dict[str, RecalculationResult] | None = None
        resume_result: ResumeResult | None = None

        if crash_result.recovery_mode:
            recovery_start_time = datetime.now(timezone.utc)
            logger.warning(
                "Entering recovery mode for %d accounts",
                len(crash_result.accounts_needing_recovery),
            )
            self._audit_crash_recovery(crash_result.accounts_needing_recovery)

            reconciler = self._collaborators.position_reconciler
            if reconciler is not None:
                reconciliation_results = await run_position_reconciliation(
                    reconciler=reconciler,
                    crash_recovery=crash_recovery,
                    accounts=crash_result.accounts_needing_recovery,
                )
                blocked_accounts = [
                    acc
                    for acc, r in reconciliation_results.items()
                    if r.requires_manual_intervention
                ]
                if blocked_accounts:
                    logger.critical(
                        "Accounts blocked pending manual intervention: %s",
                        blocked_accounts,
                    )

                if all(r.success for r in reconciliation_results.values()):
                    pnl_results = await self._run_pnl_recalculation(
                        crash_recovery, reconciliation_results
                    )
                    resume_result = await self._run_trading_resume(
                        reconciliation_results,
                        pnl_results,
                        recovery_start_time,
                    )
                    await crash_recovery.clear_crash_indicators()
                    logger.info(
                        "Crash indicators cleared - all accounts reconciled successfully"
                    )
                else:
                    logger.warning(
                        "Crash indicators NOT cleared - some accounts require "
                        "manual intervention"
                    )
            else:
                logger.warning(
                    "Position reconciler not configured - skipping reconciliation"
                )
                await crash_recovery.clear_crash_indicators()

        return RecoveryOutcome(
            crash_result=crash_result,
            reconciliation_results=reconciliation_results,
            pnl_recalculation_results=pnl_results,
            resume_result=resume_result,
            crash_recovery=crash_recovery,
            cold_storage_writer=self._collaborators.cold_storage_writer,
        )

    def _audit_crash_recovery(self, accounts: list[str]) -> None:
        if self._audit_service is None:
            return
        task = asyncio.create_task(
            self._audit_service.log_system_event(
                event_subtype="crash_recovery",
                message=f"Crash recovery initiated for {len(accounts)} accounts",
                level="WARNING",
                context={"accounts": accounts},
            ),
            name="audit_crash_recovery",
        )
        task.add_done_callback(audit_task_done_callback)

    async def _run_pnl_recalculation(
        self,
        crash_recovery: CrashRecoveryManager,
        reconciliation_results: dict[str, ReconciliationResult],
    ) -> dict[str, RecalculationResult]:
        recalculator = self._collaborators.pnl_recalculator
        results: dict[str, RecalculationResult] = {}
        if recalculator is None or self._risk_registry is None:
            logger.warning(
                "Skipping P&L recalculation - recalculator or risk_registry missing"
            )
            return results

        for account_id, recon_result in reconciliation_results.items():
            if recon_result.requires_manual_intervention:
                logger.warning(
                    "Skipping P&L recalculation for %s - manual intervention required",
                    account_id,
                )
                continue

            _valid, snapshot = await crash_recovery.validate_snapshot_for_recovery(
                account_id
            )
            snapshot_daily_pnl = Decimal("0")
            if snapshot is not None:
                risk_state = self._risk_registry.get_risk_state(account_id)
                if risk_state is not None:
                    snapshot_daily_pnl = risk_state.daily_pnl

            result = await recalculator.recalculate_daily_pnl(
                account_id, snapshot_daily_pnl
            )
            if result.success:
                await recalculator.apply_recalculation(account_id, result)

            results[account_id] = result

            if result.success and result.adjustment != Decimal("0"):
                logger.info(
                    "Account %s P&L adjusted by %s",
                    account_id,
                    result.adjustment,
                )

        return results

    async def _run_trading_resume(
        self,
        reconciliation_results: dict[str, ReconciliationResult],
        pnl_results: dict[str, RecalculationResult] | None,
        recovery_start_time: datetime,
    ) -> ResumeResult:
        resumer = self._collaborators.trading_resumer
        if resumer is None:
            logger.warning("Skipping trading resume - resumer not configured")
            return ResumeResult(
                success=False,
                accounts_resumed=0,
                accounts_skipped=0,
                accounts_blocked=0,
                recovery_duration=timedelta(0),
                account_results=[],
                notification_sent=False,
            )
        return await resumer.resume_trading_after_recovery(
            reconciliation_results=reconciliation_results,
            pnl_results=pnl_results or {},
            recovery_start_time=recovery_start_time,
        )
