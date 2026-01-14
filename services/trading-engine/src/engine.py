"""Trading Engine Core Orchestration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from .accounts.account_manager import AccountManager
    from .accounts.pnl_registry import PnLTrackerRegistry
    from .accounts.risk_registry import RiskStateRegistry
    from .adapters.zmq_adapter import ZmqAdapter
    from .state.crash_recovery import CrashRecoveryManager, RecoveryResult
    from .state.daily_pnl_recalculator import DailyPnLRecalculator, RecalculationResult
    from .state.position_reconciler import PositionReconciler, ReconciliationResult
    from .state.redis_state import RedisStateManager
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
        """
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._redis_manager = redis_manager
        self._zmq_adapter = zmq_adapter
        self._db_session_factory = db_session_factory
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._account_manager = account_manager
        self._crash_recovery: CrashRecoveryManager | None = None
        self._recovery_result: RecoveryResult | None = None
        self._reconciliation_results: dict[str, ReconciliationResult] | None = None
        self._pnl_recalculation_results: dict[str, RecalculationResult] | None = None
        self._reconciler: PositionReconciler | None = None
        self._pnl_recalculator: DailyPnLRecalculator | None = None
        self._trading_resumer: TradingResumer | None = None
        self._resume_result: ResumeResult | None = None

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

    def _on_lock_lost(self) -> None:
        """Handle loss of process lock by triggering emergency shutdown.

        Called by CrashRecoveryManager when heartbeat detects lock was lost.
        This typically means another instance acquired the lock or Redis issue.
        """
        logger.critical("Process lock lost! Triggering emergency shutdown.")
        self._running = False
        self._shutdown_event.set()

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

        from .state.crash_recovery import CrashRecoveryManager

        self._crash_recovery = CrashRecoveryManager(
            redis_manager=self._redis_manager,
            on_lock_lost=self._on_lock_lost,
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

    async def run(self) -> None:
        """Start the trading engine main loop.

        This placeholder demonstrates the async pattern that will be
        used for the actual implementation. Now includes crash recovery
        detection and process locking.

        Raises:
            RuntimeError: If another engine instance is already running.
        """
        # Initialize crash recovery FIRST before other components
        self._recovery_result = await self._initialize_crash_recovery()

        logger.info("Trading Engine v0.1.0 initialized")
        self._running = True

        # Placeholder: Wait for shutdown signal
        # In Epic 2+, this will run the NautilusTrader event loop
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Engine run loop cancelled")

        logger.info("Trading Engine run loop exited")

    async def shutdown(self) -> None:
        """Gracefully shutdown the trading engine.

        Ensures all resources are properly released and state is persisted.
        Runs crash recovery shutdown sequence to set clean shutdown flag.
        """
        if not self._running:
            return

        logger.info("Initiating graceful shutdown...")
        self._running = False
        self._shutdown_event.set()

        # Future: Close adapters, persist state, cleanup resources

        # Run crash recovery shutdown sequence LAST
        if self._crash_recovery is not None:
            await self._crash_recovery.shutdown_sequence()

        logger.info("Shutdown complete")
