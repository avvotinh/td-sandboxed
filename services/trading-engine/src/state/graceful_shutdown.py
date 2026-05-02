"""Graceful shutdown handler for trading engine.

Handles orderly shutdown sequence:
1. Stop accepting new signals
2. Wait for in-flight orders
3. Persist final state snapshots
4. Set clean shutdown flag
5. Close all connections
6. Exit cleanly

Supports both CLI stop command and OS signals (SIGTERM, SIGINT).
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..adapters.zmq_adapter import ZmqAdapter
    from ..audit.audit_service import AuditService
    from .cold_storage_service import ColdStorageService
    from .crash_recovery import CrashRecoveryManager
    from .redis_state import RedisStateManager
    from .snapshot_service import SnapshotService

logger = logging.getLogger(__name__)


class ShutdownPhase(Enum):
    """Phases of graceful shutdown sequence."""

    NOT_STARTED = auto()
    STOPPING_SIGNALS = auto()
    WAITING_ORDERS = auto()
    PERSISTING_STATE = auto()
    CLOSING_CONNECTIONS = auto()
    COMPLETE = auto()


@dataclass
class ShutdownResult:
    """Result of graceful shutdown sequence.

    Attributes:
        success: True if shutdown completed cleanly
        phase_reached: Last phase completed
        pending_orders_at_timeout: Orders that didn't complete before timeout
        accounts_snapshot_count: Number of accounts with final snapshot saved
        duration_seconds: Total shutdown duration
        exit_code: Process exit code (0 for success)
    """

    success: bool
    phase_reached: ShutdownPhase
    pending_orders_at_timeout: int
    accounts_snapshot_count: int
    duration_seconds: float
    exit_code: int


class GracefulShutdown:
    """Orchestrates graceful shutdown of trading engine.

    Handles the complete shutdown sequence when triggered by:
    - CLI command: `trading-engine stop`
    - OS signals: SIGTERM, SIGINT (Ctrl+C)

    The shutdown sequence follows architecture spec:
    1. Set shutdown flag (atomic) - prevents race conditions
    2. Stop accepting new signals - unsubscribe from Redis
    3. Wait for in-flight orders (up to 30s timeout)
    4. Persist final state snapshots for all accounts
    5. Close connections (ZMQ, Redis, TimescaleDB)
    6. Exit with code 0

    Example:
        shutdown = GracefulShutdown(
            redis_manager=redis,
            account_manager=accounts,
            snapshot_service=snapshots,
            zmq_adapter=zmq,
            crash_recovery=crash_mgr,
        )
        shutdown.register_signal_handlers()
        # ... engine runs ...
        result = await shutdown.initiate()  # Called on stop or signal
    """

    PENDING_ORDER_TIMEOUT_SECONDS = 30
    AUDIT_DRAIN_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        redis_manager: RedisStateManager,
        account_manager: AccountManager,
        snapshot_service: SnapshotService | None = None,
        zmq_adapter: ZmqAdapter | None = None,
        crash_recovery: CrashRecoveryManager | None = None,
        cold_storage_service: ColdStorageService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        """Initialize GracefulShutdown.

        Args:
            redis_manager: Redis client for pub/sub unsubscribe
            account_manager: Account manager to stop account tasks
            snapshot_service: For final state snapshots (optional)
            zmq_adapter: ZMQ adapter for pending order tracking (optional)
            crash_recovery: Crash recovery manager for clean shutdown flag
            cold_storage_service: Cold storage service for final TimescaleDB snapshot
            audit_service: Audit service whose writer must be drained before
                we close the DB connection (story 10.3 — bounded queue must
                not lose pending entries on shutdown)
        """
        self._redis = redis_manager
        self._account_manager = account_manager
        self._snapshot_service = snapshot_service
        self._zmq = zmq_adapter
        self._crash_recovery = crash_recovery
        self._cold_storage_service = cold_storage_service
        self._audit_service = audit_service
        self._shutdown_event = asyncio.Event()
        self._shutdown_in_progress = False
        self._current_phase = ShutdownPhase.NOT_STARTED
        self._start_time: datetime | None = None

    def bind_recovery_artifacts(
        self,
        crash_recovery: CrashRecoveryManager | None,
        cold_storage_service: ColdStorageService | None,
    ) -> None:
        """Late-bind the recovery-flow artifacts that only exist post-recovery.

        Story 10.2 introduces this so the DI container can construct
        :class:`GracefulShutdown` eagerly (with redis + account_manager)
        and wire in the artifacts produced by the recovery and live-start
        phases later. Idempotent — last call wins.
        """
        self._crash_recovery = crash_recovery
        self._cold_storage_service = cold_storage_service

    def register_signal_handlers(self) -> None:
        """Register handlers for SIGTERM and SIGINT.

        Uses asyncio's add_signal_handler for proper async integration.
        Signal handlers set the shutdown event which triggers the
        shutdown sequence in the main event loop.

        CRITICAL: Must be called from main thread after event loop starts.
        """
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: self._handle_signal(s),
            )
            logger.debug("Registered handler for %s", sig.name)

        logger.info("Signal handlers registered for graceful shutdown")

    def _handle_signal(self, signum: signal.Signals) -> None:
        """Handle OS signal by triggering shutdown.

        Args:
            signum: The signal received (SIGTERM or SIGINT)
        """
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, initiating graceful shutdown", sig_name)
        self._shutdown_event.set()

    def unregister_signal_handlers(self) -> None:
        """Unregister signal handlers during shutdown.

        Prevents duplicate shutdown triggers and allows clean exit.
        """
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)
            logger.debug("Signal handlers unregistered")
        except Exception as e:
            logger.warning("Failed to unregister signal handlers: %s", e)

    async def _stop_signal_processing(self) -> None:
        """Stop accepting new trading signals.

        Actions:
        1. Unsubscribe from Redis market data channels
        2. Stop SignalRouter from processing new signals
        3. Stop all account tasks from processing

        After this step, no new trades will be initiated.
        """
        self._current_phase = ShutdownPhase.STOPPING_SIGNALS
        logger.info("Stopping signal processing...")

        # Stop account manager from processing new signals
        # This stops all account tasks gracefully
        # NOTE: Use shutdown() not stop_all() - verified in account_manager.py:645
        try:
            await self._account_manager.shutdown()
            logger.debug("Account manager stopped")
        except Exception as e:
            logger.error("Error stopping account manager: %s", e)

        # Future: Unsubscribe from Redis market data channels
        # await self._redis.unsubscribe_all()

        logger.info("Signal processing stopped - no new trades will be initiated")

    async def _wait_for_pending_orders(self) -> int:
        """Wait for pending orders to complete with timeout.

        Monitors ZmqAdapter for pending order count.
        Logs progress every 5 seconds during wait.
        Returns number of orders still pending at timeout.

        Returns:
            Number of orders that did NOT complete before timeout
        """
        self._current_phase = ShutdownPhase.WAITING_ORDERS

        if self._zmq is None:
            logger.debug("No ZMQ adapter - skipping pending order wait")
            return 0

        pending = self._zmq.get_pending_order_count()
        if pending == 0:
            logger.info("No pending orders to wait for")
            return 0

        logger.info("Waiting for %d pending orders...", pending)

        start = datetime.now(timezone.utc)
        timeout = self.PENDING_ORDER_TIMEOUT_SECONDS
        check_interval = 1.0  # Check every second
        log_interval = 5.0  # Log every 5 seconds

        last_log_time = start
        while True:
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()

            if elapsed >= timeout:
                remaining = self._zmq.get_pending_order_count()
                if remaining > 0:
                    logger.warning(
                        "Shutdown timeout: %d orders still pending after %.1fs",
                        remaining,
                        timeout,
                    )
                return remaining

            pending = self._zmq.get_pending_order_count()
            if pending == 0:
                logger.info(
                    "All pending orders completed in %.1f seconds",
                    elapsed,
                )
                return 0

            # Log progress periodically
            now = datetime.now(timezone.utc)
            if (now - last_log_time).total_seconds() >= log_interval:
                logger.info(
                    "Waiting for %d pending orders... (%.1fs elapsed)",
                    pending,
                    elapsed,
                )
                last_log_time = now

            await asyncio.sleep(check_interval)

    async def _persist_final_state(self) -> int:
        """Persist final state snapshot for all accounts.

        Uses SnapshotService.stop() and ColdStorageService.stop() which:
        1. Stop the periodic snapshot loops
        2. Create one final snapshot for all active accounts
        3. Write final snapshots to both Redis and TimescaleDB
        4. Log any snapshot failures

        Returns:
            Number of accounts with successful final snapshot
        """
        self._current_phase = ShutdownPhase.PERSISTING_STATE
        logger.info("Persisting final state snapshots...")

        active_accounts = 0

        # Stop Redis snapshot service (creates final Redis snapshot)
        if self._snapshot_service is not None:
            try:
                await self._snapshot_service.stop()
                active_accounts = await self._get_active_account_count()
                logger.info(
                    "Final Redis state persisted for %d accounts",
                    active_accounts,
                )
            except Exception as e:
                logger.error("Failed to persist final Redis state: %s", e)

        # Stop cold storage service (creates final TimescaleDB snapshot)
        if self._cold_storage_service is not None:
            try:
                await self._cold_storage_service.stop()
                logger.info("Final TimescaleDB cold storage snapshot persisted")
            except Exception as e:
                logger.error("Failed to persist final cold storage state: %s", e)

        # Drain the bounded audit queue BEFORE we close the DB connection.
        # Story 10.3 — every queued audit entry must reach TimescaleDB;
        # back-pressure callers may have blocked waiting for space, so we
        # cannot drop them. The writer is intentionally left running so
        # that the lifecycle's final ``engine_stopped`` audit row can still
        # use ``log_sync``; lifecycle will call ``stop()`` once its trailing
        # audits are written.
        if self._audit_service is not None:
            try:
                await self._audit_service.drain(
                    timeout=self.AUDIT_DRAIN_TIMEOUT_SECONDS
                )
                logger.info("Audit writer drained")
            except asyncio.TimeoutError:
                logger.warning(
                    "Audit writer drain timed out after %ds — entries may be lost",
                    self.AUDIT_DRAIN_TIMEOUT_SECONDS,
                )
            except Exception as e:
                logger.error("Audit writer drain raised: %s", e)

        return active_accounts

    async def _get_active_account_count(self) -> int:
        """Get count of active accounts for logging."""
        account_ids = self._account_manager.get_all_accounts()
        if not account_ids:
            return 0

        statuses = await asyncio.gather(
            *[self._account_manager.get_account_status(acc) for acc in account_ids]
        )
        return sum(1 for s in statuses if s in ("active", "paused"))

    async def _close_connections(self) -> None:
        """Close all service connections gracefully.

        Order matters - close in reverse dependency order:
        1. ZeroMQ (execution bridge)
        2. Redis (state and pub/sub)
        3. TimescaleDB (audit logs) - future

        Each close is wrapped in try/except to ensure
        subsequent closes happen even on error.
        """
        self._current_phase = ShutdownPhase.CLOSING_CONNECTIONS
        logger.info("Closing connections...")

        # 1. Close ZMQ adapter
        if self._zmq is not None:
            try:
                await self._zmq.close()
                logger.debug("ZMQ adapter closed")
            except Exception as e:
                logger.error("Error closing ZMQ adapter: %s", e)

        # 2. Close Redis connection
        try:
            await self._redis.close()
            logger.debug("Redis connection closed")
        except Exception as e:
            logger.error("Error closing Redis connection: %s", e)

        # Future: Close TimescaleDB connection
        # if self._db is not None:
        #     await self._db.close()

        logger.info("All connections closed")

    async def initiate(self) -> ShutdownResult:
        """Execute graceful shutdown sequence.

        This is the main entry point called by:
        - Engine.shutdown() (from CLI stop command)
        - Signal handler (SIGTERM/SIGINT)

        Sequence (per Architecture doc):
        1. Set shutdown flag (atomic)
        2. Stop accepting new signals
        3. Wait for in-flight orders (30s timeout)
        4. Persist final state
        5. Set clean shutdown flag (CrashRecoveryManager)
        6. Close connections
        7. Exit with code 0

        Returns:
            ShutdownResult with status and metrics
        """
        # Prevent duplicate shutdown
        if self._shutdown_in_progress:
            logger.warning("Shutdown already in progress")
            return ShutdownResult(
                success=False,
                phase_reached=self._current_phase,
                pending_orders_at_timeout=0,
                accounts_snapshot_count=0,
                duration_seconds=0,
                exit_code=1,
            )

        self._shutdown_in_progress = True
        self._start_time = datetime.now(timezone.utc)
        logger.info("Initiating graceful shutdown...")

        # Unregister signal handlers to prevent re-entry
        self.unregister_signal_handlers()

        pending_orders_remaining = 0
        accounts_snapshotted = 0

        try:
            # Phase 1: Stop signal processing
            await self._stop_signal_processing()

            # Phase 2: Wait for pending orders
            pending_orders_remaining = await self._wait_for_pending_orders()

            # Phase 3: Persist final state
            accounts_snapshotted = await self._persist_final_state()

            # Phase 4: Run crash recovery shutdown sequence
            # This sets clean shutdown flag and releases process lock
            if self._crash_recovery is not None:
                await self._crash_recovery.shutdown_sequence()
                logger.debug("Crash recovery shutdown sequence completed")

            # Phase 5: Close connections
            await self._close_connections()

            self._current_phase = ShutdownPhase.COMPLETE

            duration = (datetime.now(timezone.utc) - self._start_time).total_seconds()

            logger.info(
                "Shutdown complete in %.2f seconds (accounts: %d, pending orders at timeout: %d)",
                duration,
                accounts_snapshotted,
                pending_orders_remaining,
            )

            return ShutdownResult(
                success=True,
                phase_reached=ShutdownPhase.COMPLETE,
                pending_orders_at_timeout=pending_orders_remaining,
                accounts_snapshot_count=accounts_snapshotted,
                duration_seconds=duration,
                exit_code=0,
            )

        except Exception as e:
            logger.error("Shutdown failed at phase %s: %s", self._current_phase.name, e)
            duration = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            return ShutdownResult(
                success=False,
                phase_reached=self._current_phase,
                pending_orders_at_timeout=pending_orders_remaining,
                accounts_snapshot_count=accounts_snapshotted,
                duration_seconds=duration,
                exit_code=1,
            )

    async def wait_for_shutdown_signal(self) -> ShutdownResult:
        """Wait for shutdown signal then execute shutdown.

        Called by Engine.run() to wait for termination.
        Blocks until SIGTERM, SIGINT, or shutdown_event is set.

        Returns:
            ShutdownResult from initiate()
        """
        await self._shutdown_event.wait()
        return await self.initiate()

    def trigger_shutdown(self) -> None:
        """Programmatically trigger shutdown.

        Used by Engine.shutdown() to trigger from code
        rather than waiting for OS signal.
        """
        logger.info("Shutdown triggered programmatically")
        self._shutdown_event.set()
