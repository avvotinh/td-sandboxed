"""Trading Engine Core Orchestration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from .rules.audit_logger import audit_task_done_callback

if TYPE_CHECKING:

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from .accounts.account_manager import AccountManager
    from .accounts.pnl_registry import PnLTrackerRegistry
    from .accounts.risk_registry import RiskStateRegistry
    from .adapters.zmq_adapter import ZmqAdapter
    from .audit.audit_service import AuditService
    from .orders.trade_db_writer import TradeDBWriter
    from .rules.violation_db_writer import ViolationDBWriter
    from .rules.violation_service import ViolationService
    from .snapshots.daily_snapshot_service import DailySnapshotService
    from .snapshots.snapshot_db_writer import SnapshotDBWriter as SnapshotDBWriterType
    from .state.cold_storage_service import ColdStorageService
    from .state.cold_storage_writer import ColdStorageWriter
    from .state.crash_recovery import CrashRecoveryManager, RecoveryResult
    from .state.daily_pnl_recalculator import DailyPnLRecalculator, RecalculationResult
    from .state.graceful_shutdown import GracefulShutdown, ShutdownResult
    from .state.position_reconciler import PositionReconciler, ReconciliationResult
    from .state.redis_state import RedisStateManager
    from .state.snapshot_service import SnapshotService
    from .state.trading_resumer import ResumeResult, TradingResumer

logger = logging.getLogger(__name__)


class TradingEngine:
    """Main trading engine orchestrator.

    This is a scaffold placeholder. Actual trading logic
    implementation begins in Epic 2.

    Responsibilities (future):
    - Multi-account management
    - Strategy execution via NautilusTrader
    - Rule engine integration for compliance
    - Redis/ZeroMQ adapter coordination
    - Crash detection and recovery (Story 5.2)
    """

    def __init__(
        self,
        redis_manager: RedisStateManager | None = None,
        zmq_adapter: ZmqAdapter | None = None,
        db_session_factory: async_sessionmaker[AsyncSession] | None = None,
        risk_registry: RiskStateRegistry | None = None,
        pnl_registry: PnLTrackerRegistry | None = None,
        account_manager: AccountManager | None = None,
        snapshot_service: SnapshotService | None = None,
        database_url: str | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Initialize the trading engine.

        Args:
            redis_manager: Optional Redis state manager for crash recovery.
                          If provided, crash recovery will be enabled.
            zmq_adapter: Optional ZMQ adapter for MT5 communication.
                        Required for position reconciliation during recovery.
            db_session_factory: Optional async session factory for database queries.
                               Required for P&L recalculation during recovery.
            risk_registry: Optional RiskStateRegistry for risk state management.
                          Required for P&L recalculation during recovery.
            pnl_registry: Optional PnLTrackerRegistry for P&L tracker access.
                         Required for P&L recalculation during recovery.
            account_manager: Optional AccountManager for starting account tasks.
                            Required for trading resume during recovery.
            snapshot_service: Optional SnapshotService for state snapshots.
                            Required for graceful shutdown final snapshot.
            database_url: Optional async PostgreSQL URL for cold storage.
                         Format: postgresql+asyncpg://user:pass@host:port/db
                         If provided, enables TimescaleDB cold storage backup.
        """
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._redis_manager = redis_manager
        self._zmq_adapter = zmq_adapter
        self._db_session_factory = db_session_factory
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._account_manager = account_manager
        self._snapshot_service = snapshot_service
        self._database_url = database_url
        self._crash_recovery: CrashRecoveryManager | None = None
        self._recovery_result: RecoveryResult | None = None
        self._reconciliation_results: dict[str, ReconciliationResult] | None = None
        self._pnl_recalculation_results: dict[str, RecalculationResult] | None = None
        self._reconciler: PositionReconciler | None = None
        self._pnl_recalculator: DailyPnLRecalculator | None = None
        self._trading_resumer: TradingResumer | None = None
        self._resume_result: ResumeResult | None = None
        self._graceful_shutdown: GracefulShutdown | None = None
        self._shutdown_result: ShutdownResult | None = None
        self._cold_storage_writer: ColdStorageWriter | None = None
        self._cold_storage_service: ColdStorageService | None = None
        self._daily_snapshot_writer: SnapshotDBWriterType | None = None
        self._daily_snapshot_service: DailySnapshotService | None = None
        self._trade_db_writer: TradeDBWriter | None = None
        self._violation_db_writer: ViolationDBWriter | None = None
        self._violation_service: ViolationService | None = None
        self._audit_service = audit_service

    @property
    def is_running(self) -> bool:
        """Check if the engine is currently running.

        Returns:
            bool: True if the engine is running, False otherwise.
        """
        return self._running

    @property
    def recovery_result(self) -> RecoveryResult | None:
        """Get the recovery result from startup.

        Returns:
            RecoveryResult if crash recovery ran, None otherwise.
        """
        return self._recovery_result

    @property
    def reconciliation_results(self) -> dict[str, ReconciliationResult] | None:
        """Get the position reconciliation results from startup.

        Returns:
            Dict mapping account_id to ReconciliationResult, or None if
            no reconciliation was performed.
        """
        return self._reconciliation_results

    @property
    def pnl_recalculation_results(self) -> dict[str, RecalculationResult] | None:
        """Get the P&L recalculation results from startup.

        Returns:
            Dict mapping account_id to RecalculationResult, or None if
            no recalculation was performed.
        """
        return self._pnl_recalculation_results

    @property
    def resume_result(self) -> ResumeResult | None:
        """Get the trading resume result from startup.

        Returns:
            ResumeResult if trading resume ran, None otherwise.
        """
        return self._resume_result

    @property
    def shutdown_result(self) -> ShutdownResult | None:
        """Get the graceful shutdown result.

        Returns:
            ShutdownResult if graceful shutdown ran, None otherwise.
        """
        return self._shutdown_result

    def _on_lock_lost(self) -> None:
        """Handle loss of process lock by triggering emergency shutdown.

        Called by CrashRecoveryManager when heartbeat detects lock was lost.
        This typically means another instance acquired the lock or Redis issue.
        """
        logger.critical("Process lock lost! Triggering emergency shutdown.")

        # Audit: log lock loss as critical system event
        if self._audit_service:

            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="lock_lost",
                    message="Process lock lost - emergency shutdown triggered",
                    level="ERROR",
                    context={"trigger": "heartbeat_failure"},
                ),
                name="audit_lock_lost",
            )
            task.add_done_callback(audit_task_done_callback)

        self._running = False
        self._shutdown_event.set()

    async def _initialize_cold_storage(self) -> None:
        """Initialize cold storage service for TimescaleDB backup.

        Creates ColdStorageService if cold_storage_writer (created in crash recovery)
        and snapshot_service are configured. This starts the 60-second snapshot loop.
        """
        if self._cold_storage_writer is None:
            # Writer not created (no database_url in crash recovery)
            return

        if self._snapshot_service is None:
            logger.warning(
                "Cold storage requires snapshot_service, cold storage disabled"
            )
            return

        from .state.cold_storage_service import ColdStorageService

        self._cold_storage_service = ColdStorageService(
            cold_storage_writer=self._cold_storage_writer,
            snapshot_service=self._snapshot_service,
        )
        await self._cold_storage_service.start()
        logger.info("Cold storage service initialized")

    async def _initialize_trade_audit(self) -> None:
        """Initialize TradeDBWriter for trade execution audit logging.

        Requires database_url. Creates the writer and starts its flush timer.
        The writer should be passed to OrderExecutionService instances via
        the trade_db_writer property.
        """
        if self._database_url is None:
            logger.warning("No database URL — trade audit logging disabled")
            return

        from .orders.trade_db_writer import TradeDBWriter

        self._trade_db_writer = TradeDBWriter(self._database_url)
        await self._trade_db_writer.start()
        logger.info("Trade audit writer initialized")

    @property
    def trade_db_writer(self) -> TradeDBWriter | None:
        """Get the TradeDBWriter for injection into OrderExecutionService."""
        return self._trade_db_writer

    async def _initialize_violation_tracking(self) -> None:
        """Initialize ViolationDBWriter and ViolationService.

        Requires database_url. Creates the writer, starts its flush timer,
        and wraps it in ViolationService for use by OrderValidator.
        """
        if self._database_url is None:
            logger.warning("No database URL — violation tracking disabled")
            return

        from .rules.violation_db_writer import ViolationDBWriter
        from .rules.violation_service import ViolationService

        self._violation_db_writer = ViolationDBWriter(self._database_url)
        await self._violation_db_writer.start()

        self._violation_service = ViolationService(self._violation_db_writer)
        logger.info("Violation tracking service initialized")

    async def _initialize_daily_snapshots(self) -> None:
        """Initialize the daily account snapshot scheduler.

        Requires database_url, redis_manager, account_manager, and db_session_factory.
        """
        if self._database_url is None:
            logger.warning("No database URL — daily snapshots disabled")
            return

        if (
            self._redis_manager is None
            or self._account_manager is None
            or self._db_session_factory is None
        ):
            logger.warning(
                "Daily snapshots require redis_manager, account_manager, "
                "and db_session_factory"
            )
            return

        from .snapshots.snapshot_db_writer import SnapshotDBWriter

        self._daily_snapshot_writer = SnapshotDBWriter(self._database_url)
        await self._daily_snapshot_writer.start()

        from .snapshots.daily_snapshot_service import DailySnapshotService

        self._daily_snapshot_service = DailySnapshotService(
            db_writer=self._daily_snapshot_writer,
            redis_state=self._redis_manager,
            account_manager=self._account_manager,
            db_session_factory=self._db_session_factory,
            audit_service=self._audit_service,
        )
        await self._daily_snapshot_service.start()
        logger.info("Daily snapshot service initialized")

    async def _initialize_crash_recovery(self) -> RecoveryResult | None:
        """Initialize crash recovery manager and run startup sequence.

        Returns:
            RecoveryResult if Redis is configured, None otherwise.

        Raises:
            SystemExit: If another engine instance is already running.
        """
        if self._redis_manager is None:
            logger.info("No Redis manager configured, skipping crash recovery")
            return None

        # Initialize cold storage writer first (needed for fallback recovery)
        if self._database_url is not None:
            from .state.cold_storage_writer import ColdStorageWriter

            self._cold_storage_writer = ColdStorageWriter(self._database_url)

        from .state.crash_recovery import CrashRecoveryManager

        self._crash_recovery = CrashRecoveryManager(
            redis_manager=self._redis_manager,
            on_lock_lost=self._on_lock_lost,
            cold_storage_writer=self._cold_storage_writer,
        )

        # Run startup sequence - this checks for crashes and acquires lock
        try:
            result = await self._crash_recovery.startup_sequence()
        except RuntimeError as e:
            # Another instance running - exit immediately per story spec
            logger.critical("Engine startup failed: %s", e)
            raise SystemExit(1) from e

        # Handle recovery mode if needed (Story 5.3 - Position Reconciliation)
        if result.recovery_mode:
            # Capture recovery start time NOW for accurate duration calculation
            recovery_start_time = datetime.now(timezone.utc)

            logger.warning(
                "Entering recovery mode for %d accounts",
                len(result.accounts_needing_recovery),
            )

            # Audit: log crash recovery event
            if self._audit_service:
    
                task = asyncio.create_task(
                    self._audit_service.log_system_event(
                        event_subtype="crash_recovery",
                        message=f"Crash recovery initiated for {len(result.accounts_needing_recovery)} accounts",
                        level="WARNING",
                        context={"accounts": result.accounts_needing_recovery},
                    ),
                    name="audit_crash_recovery",
                )
                task.add_done_callback(audit_task_done_callback)

            # Run position reconciliation if ZMQ adapter is available
            if self._zmq_adapter is not None:
                self._reconciliation_results = await self._run_position_reconciliation(
                    result.accounts_needing_recovery
                )

                # Check for any accounts requiring manual intervention
                blocked_accounts = [
                    acc
                    for acc, recon_result in self._reconciliation_results.items()
                    if recon_result.requires_manual_intervention
                ]

                if blocked_accounts:
                    logger.critical(
                        "Accounts blocked pending manual intervention: %s",
                        blocked_accounts,
                    )
                    # These accounts won't be started until manually reviewed

                # AC6: Only clear crash indicators if ALL accounts reconciled successfully
                all_success = all(
                    r.success for r in self._reconciliation_results.values()
                )
                if all_success:
                    # Story 5.4: Daily P&L recalculation after position reconciliation
                    self._pnl_recalculation_results = (
                        await self._run_daily_pnl_recalculation(
                            self._reconciliation_results
                        )
                    )

                    # Story 5.5: Resume trading for eligible accounts
                    # Uses recovery_start_time captured at recovery mode entry
                    self._resume_result = await self._run_trading_resume(
                        reconciliation_results=self._reconciliation_results,
                        pnl_results=self._pnl_recalculation_results or {},
                        recovery_start_time=recovery_start_time,
                    )

                    await self._crash_recovery.clear_crash_indicators()
                    logger.info("Crash indicators cleared - all accounts reconciled successfully")
                else:
                    logger.warning(
                        "Crash indicators NOT cleared - some accounts require manual intervention"
                    )
            else:
                logger.warning(
                    "ZMQ adapter not available - skipping position reconciliation"
                )
                # No reconciliation performed, clear indicators to allow startup
                await self._crash_recovery.clear_crash_indicators()

        return result

    async def _run_position_reconciliation(
        self,
        accounts: list[str],
    ) -> dict[str, ReconciliationResult]:
        """Run reconciliation for all accounts needing recovery.

        Called after crash detection, before resuming trading.
        Initializes PositionReconciler and runs reconciliation for each account.

        Args:
            accounts: List of account IDs from recovery result

        Returns:
            Dict mapping account_id to ReconciliationResult
        """
        from .state.position_reconciler import (
            PositionReconciler,
            run_position_reconciliation,
        )

        # Initialize the reconciler
        self._reconciler = PositionReconciler(
            zmq_adapter=self._zmq_adapter,
            redis_manager=self._redis_manager,
        )

        # Run reconciliation using helper function
        return await run_position_reconciliation(
            reconciler=self._reconciler,
            crash_recovery=self._crash_recovery,
            accounts=accounts,
        )

    async def _run_daily_pnl_recalculation(
        self,
        reconciliation_results: dict[str, ReconciliationResult],
    ) -> dict[str, RecalculationResult]:
        """Recalculate daily P&L for all successfully reconciled accounts.

        Called after position reconciliation (Story 5.3), before trading resumes.
        Only recalculates for accounts that passed reconciliation.

        Args:
            reconciliation_results: Results from position reconciliation

        Returns:
            Dict mapping account_id to RecalculationResult
        """
        from .state.daily_pnl_recalculator import DailyPnLRecalculator

        results: dict[str, RecalculationResult] = {}

        # Skip if required dependencies are not configured
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

        # Initialize the recalculator (lazy init)
        if self._pnl_recalculator is None:
            self._pnl_recalculator = DailyPnLRecalculator(
                db_session_factory=self._db_session_factory,
                redis_manager=self._redis_manager,
                risk_registry=self._risk_registry,
                pnl_registry=self._pnl_registry,
            )

        for account_id, recon_result in reconciliation_results.items():
            # Skip accounts that failed reconciliation
            if recon_result.requires_manual_intervention:
                logger.warning(
                    "Skipping P&L recalculation for %s - manual intervention required",
                    account_id,
                )
                continue

            # Get snapshot daily P&L for comparison
            valid, snapshot = await self._crash_recovery.validate_snapshot_for_recovery(
                account_id
            )
            # Use daily_starting_balance as base for comparison
            # (daily_pnl in snapshot could be stale)
            snapshot_daily_pnl = Decimal("0")
            if snapshot is not None:
                # Get current daily P&L from risk state (if available)
                risk_state = self._risk_registry.get_risk_state(account_id)
                if risk_state is not None:
                    snapshot_daily_pnl = risk_state.daily_pnl

            # Recalculate
            result = await self._pnl_recalculator.recalculate_daily_pnl(
                account_id,
                snapshot_daily_pnl,
            )

            # Apply if successful
            if result.success:
                await self._pnl_recalculator.apply_recalculation(account_id, result)

            results[account_id] = result

            # Log summary
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
        pnl_results: dict[str, RecalculationResult],
        recovery_start_time: datetime,
    ) -> ResumeResult:
        """Resume trading for all eligible accounts after recovery.

        Called after P&L recalculation, before clearing crash indicators.
        Only resumes accounts that:
        - Were "active" before crash
        - Passed reconciliation successfully
        - Passed P&L recalculation (or fallback)

        Args:
            reconciliation_results: Results from position reconciliation
            pnl_results: Results from P&L recalculation
            recovery_start_time: When crash recovery started

        Returns:
            ResumeResult with resume details
        """
        from datetime import timedelta

        from .state.trading_resumer import ResumeResult, TradingResumer

        # Initialize resumer (lazy init)
        if self._trading_resumer is None:
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

            self._trading_resumer = TradingResumer(
                redis_manager=self._redis_manager,
                account_manager=self._account_manager,
            )

        return await self._trading_resumer.resume_trading_after_recovery(
            reconciliation_results=reconciliation_results,
            pnl_results=pnl_results,
            recovery_start_time=recovery_start_time,
        )

    def _initialize_graceful_shutdown(self) -> None:
        """Initialize graceful shutdown handler.

        Called after all engine components are initialized.
        Registers signal handlers for SIGTERM/SIGINT.
        """
        if self._redis_manager is None or self._account_manager is None:
            logger.warning(
                "Graceful shutdown requires redis_manager and account_manager"
            )
            return

        from .state.graceful_shutdown import GracefulShutdown

        self._graceful_shutdown = GracefulShutdown(
            redis_manager=self._redis_manager,
            account_manager=self._account_manager,
            snapshot_service=self._snapshot_service,
            zmq_adapter=self._zmq_adapter,
            crash_recovery=self._crash_recovery,
            cold_storage_service=self._cold_storage_service,
        )
        self._graceful_shutdown.register_signal_handlers()
        logger.info("Graceful shutdown handler initialized")

    async def run(self) -> None:
        """Start the trading engine main loop.

        This placeholder demonstrates the async pattern that will be
        used for the actual implementation. Now includes crash recovery
        detection, process locking, and graceful shutdown handling.

        Raises:
            RuntimeError: If another engine instance is already running.
        """
        # Initialize crash recovery FIRST before other components
        self._recovery_result = await self._initialize_crash_recovery()

        # Initialize cold storage service after crash recovery
        # (uses the writer that was created in crash recovery)
        await self._initialize_cold_storage()

        # Initialize trade audit writer (TradeDBWriter for Story 7.1)
        await self._initialize_trade_audit()

        # Initialize violation tracking (ViolationDBWriter + ViolationService)
        await self._initialize_violation_tracking()

        # Initialize daily snapshot service (midnight UTC scheduler)
        await self._initialize_daily_snapshots()

        # Initialize graceful shutdown after crash recovery
        self._initialize_graceful_shutdown()

        logger.info("Trading Engine v0.1.0 running")
        self._running = True

        # Audit: log engine start
        if self._audit_service:

            start_context: dict = {"version": "0.1.0"}
            if self._recovery_result and self._recovery_result.recovery_mode:
                start_context["recovery_mode"] = True
                start_context["accounts_recovered"] = self._recovery_result.accounts_needing_recovery
            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="engine_start",
                    message="Trading Engine started",
                    context=start_context,
                ),
                name="audit_engine_start",
            )
            task.add_done_callback(audit_task_done_callback)

        # Wait for shutdown signal (via SIGTERM, SIGINT, or shutdown())
        if self._graceful_shutdown is not None:
            try:
                self._shutdown_result = (
                    await self._graceful_shutdown.wait_for_shutdown_signal()
                )
                if not self._shutdown_result.success:
                    logger.error("Shutdown completed with errors")
            except asyncio.CancelledError:
                logger.info("Engine run loop cancelled")
        else:
            # Fallback to simple event wait (no graceful shutdown)
            try:
                await self._shutdown_event.wait()
            except asyncio.CancelledError:
                logger.info("Engine run loop cancelled")

        # Audit: log shutdown completion with result
        if self._audit_service:

            shutdown_success = self._shutdown_result.success if self._shutdown_result else True
            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="engine_stopped",
                    message="Trading Engine stopped",
                    level="INFO" if shutdown_success else "ERROR",
                    context={
                        "graceful": self._graceful_shutdown is not None,
                        "success": shutdown_success,
                    },
                ),
                name="audit_engine_stopped",
            )
            task.add_done_callback(audit_task_done_callback)
            # Brief wait to allow the audit entry to be buffered before engine teardown
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except Exception:
                logger.warning("Failed to buffer engine_stopped audit entry", exc_info=True)

        # Stop daily snapshot service
        if self._daily_snapshot_service:
            await self._daily_snapshot_service.stop()
        if self._daily_snapshot_writer:
            await self._daily_snapshot_writer.stop()

        # Stop trade audit writer
        if self._trade_db_writer:
            await self._trade_db_writer.stop()

        # Stop violation tracking
        if self._violation_db_writer:
            await self._violation_db_writer.stop()

        # Stop audit service (flushes buffered entries including engine_stopped)
        if self._audit_service:
            await self._audit_service.stop()

        self._running = False
        logger.info("Trading Engine stopped")

    async def shutdown(self) -> None:
        """Gracefully shutdown the trading engine.

        Triggers the graceful shutdown sequence which:
        1. Stops signal processing
        2. Waits for pending orders (30s timeout)
        3. Persists final state snapshot
        4. Sets clean shutdown flag
        5. Closes all connections

        Exit code is 0 on success.
        """
        if not self._running:
            return

        logger.info("Shutdown requested via Engine.shutdown()")

        # Audit: log engine stop
        if self._audit_service:

            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="engine_stop",
                    message="Trading Engine shutdown requested",
                    context={"graceful": self._graceful_shutdown is not None},
                ),
                name="audit_engine_stop",
            )
            task.add_done_callback(audit_task_done_callback)

        if self._graceful_shutdown is not None:
            self._graceful_shutdown.trigger_shutdown()
            # The actual shutdown is handled by run() waiting on the event
        else:
            # Fallback for backward compatibility
            self._running = False
            self._shutdown_event.set()
            if self._crash_recovery is not None:
                await self._crash_recovery.shutdown_sequence()
