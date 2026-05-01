"""RecoveryOrchestrator — owns the cold-start recovery flow.

Story 10.1 extracts the recovery sequence (crash detection, position
reconciliation, daily P&L recompute, trading resume) out of the
`TradingEngine` god-object into a single class that orchestrates the four
existing state modules without altering their public API.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..accounts.account_manager import AccountManager
from ..accounts.pnl_registry import PnLTrackerRegistry
from ..accounts.risk_registry import RiskStateRegistry
from ..adapters.zmq_adapter import ZmqAdapter
from ..audit.audit_service import AuditService
from ..config.firm_registry import FirmRegistry
from ..rules.audit_logger import audit_task_done_callback
from ..state.cold_storage_writer import ColdStorageWriter
from ..state.crash_recovery import CrashRecoveryManager
from ..state.crash_recovery import RecoveryResult as CrashRecoveryResult
from ..state.daily_pnl_recalculator import DailyPnLRecalculator, RecalculationResult
from ..state.position_reconciler import (
    PositionReconciler,
    ReconciliationResult,
    run_position_reconciliation,
)
from ..state.redis_state import RedisStateManager
from ..state.trading_resumer import ResumeResult, TradingResumer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryOutcome:
    """Aggregated artifacts produced by `RecoveryOrchestrator.run`.

    The CrashRecoveryManager and ColdStorageWriter references are
    forwarded to downstream lifecycle stages (graceful shutdown, cold
    storage service) which need to share the same long-lived instances.
    """

    crash_result: CrashRecoveryResult | None
    reconciliation_results: dict[str, ReconciliationResult] | None
    pnl_recalculation_results: dict[str, RecalculationResult] | None
    resume_result: ResumeResult | None
    crash_recovery: CrashRecoveryManager | None
    cold_storage_writer: ColdStorageWriter | None


class RecoveryOrchestrator:
    """Orchestrates crash recovery, reconciliation, P&L recompute, and resume.

    .. note:: Story 10.1 takes raw deps and constructs the four recovery
       managers internally because :class:`CrashRecoveryManager` requires the
       ``on_lock_lost`` callback bound to the lifecycle, which itself depends
       on this orchestrator. Story 10.2's DI container resolves the cycle so
       this constructor can accept pre-built managers per the spec example.
    """

    # TODO(10.2): switch to ``__init__(crash_recovery, position_reconciler,
    # pnl_recalculator, trading_resumer)`` once the DI container can supply
    # pre-built managers wired with a callback shim for ``on_lock_lost``.
    def __init__(
        self,
        redis_manager: RedisStateManager | None,
        zmq_adapter: ZmqAdapter | None,
        db_session_factory: async_sessionmaker[AsyncSession] | None,
        risk_registry: RiskStateRegistry | None,
        pnl_registry: PnLTrackerRegistry | None,
        account_manager: AccountManager | None,
        firm_registry: FirmRegistry | None,
        audit_service: AuditService | None,
        database_url: str | None,
    ) -> None:
        self._redis_manager = redis_manager
        self._zmq_adapter = zmq_adapter
        self._db_session_factory = db_session_factory
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._account_manager = account_manager
        self._firm_registry = firm_registry
        self._audit_service = audit_service
        self._database_url = database_url

    @property
    def zmq_adapter(self) -> ZmqAdapter | None:
        """Exposed so EngineLifecycle can pass it to GracefulShutdown."""
        return self._zmq_adapter

    async def run(self, on_lock_lost: Callable[[], None]) -> RecoveryOutcome:
        """Execute the recovery flow. Behavior matches `engine.py` baseline."""
        if self._redis_manager is None:
            logger.info("No Redis manager configured, skipping crash recovery")
            return RecoveryOutcome(None, None, None, None, None, None)

        cold_storage_writer = (
            ColdStorageWriter(self._database_url)
            if self._database_url is not None
            else None
        )

        crash_recovery = CrashRecoveryManager(
            redis_manager=self._redis_manager,
            on_lock_lost=on_lock_lost,
            cold_storage_writer=cold_storage_writer,
        )

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

            if self._zmq_adapter is not None:
                reconciliation_results = await self._run_reconciliation(
                    crash_recovery, crash_result.accounts_needing_recovery
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
                        "Crash indicators NOT cleared - some accounts require manual intervention"
                    )
            else:
                logger.warning(
                    "ZMQ adapter not available - skipping position reconciliation"
                )
                await crash_recovery.clear_crash_indicators()

        return RecoveryOutcome(
            crash_result=crash_result,
            reconciliation_results=reconciliation_results,
            pnl_recalculation_results=pnl_results,
            resume_result=resume_result,
            crash_recovery=crash_recovery,
            cold_storage_writer=cold_storage_writer,
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

    async def _run_reconciliation(
        self,
        crash_recovery: CrashRecoveryManager,
        accounts: list[str],
    ) -> dict[str, ReconciliationResult]:
        reconciler = PositionReconciler(
            zmq_adapter=self._zmq_adapter,
            redis_manager=self._redis_manager,
        )
        return await run_position_reconciliation(
            reconciler=reconciler,
            crash_recovery=crash_recovery,
            accounts=accounts,
        )

    async def _run_pnl_recalculation(
        self,
        crash_recovery: CrashRecoveryManager,
        reconciliation_results: dict[str, ReconciliationResult],
    ) -> dict[str, RecalculationResult]:
        results: dict[str, RecalculationResult] = {}
        if (
            self._db_session_factory is None
            or self._redis_manager is None
            or self._risk_registry is None
            or self._pnl_registry is None
        ):
            logger.warning(
                "Skipping P&L recalculation - missing required dependencies "
                "(db_session_factory, redis_manager, risk_registry, or pnl_registry)"
            )
            return results

        recalculator = DailyPnLRecalculator(
            db_session_factory=self._db_session_factory,
            redis_manager=self._redis_manager,
            risk_registry=self._risk_registry,
            pnl_registry=self._pnl_registry,
            firm_registry=self._firm_registry,
            account_manager=self._account_manager,
        )

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
        if self._redis_manager is None or self._account_manager is None:
            logger.warning(
                "Skipping trading resume - missing redis_manager or account_manager"
            )
            return ResumeResult(
                success=False,
                accounts_resumed=0,
                accounts_skipped=0,
                accounts_blocked=0,
                recovery_duration=timedelta(0),
                account_results=[],
                notification_sent=False,
            )

        resumer = TradingResumer(
            redis_manager=self._redis_manager,
            account_manager=self._account_manager,
        )
        return await resumer.resume_trading_after_recovery(
            reconciliation_results=reconciliation_results,
            pnl_results=pnl_results or {},
            recovery_start_time=recovery_start_time,
        )
