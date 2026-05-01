"""EngineLifecycle — top-level coordinator: recovery → live → shutdown.

Story 10.1 lifts the run/shutdown sequence out of the god-object. Behavior
matches the `engine.py` baseline 100%: same audit events, same shutdown
ordering, same idempotent shutdown semantics.
"""
from __future__ import annotations

import asyncio
import logging

from ..accounts.account_manager import AccountManager
from ..audit.audit_service import AuditService
from ..rules.audit_logger import audit_task_done_callback
from ..state.crash_recovery import CrashRecoveryManager
from ..state.crash_recovery import RecoveryResult as CrashRecoveryResult
from ..state.daily_pnl_recalculator import RecalculationResult
from ..state.graceful_shutdown import GracefulShutdown, ShutdownResult
from ..state.position_reconciler import ReconciliationResult
from ..state.redis_state import RedisStateManager
from ..state.snapshot_service import SnapshotService
from ..state.trading_resumer import ResumeResult
from .live_orchestrator import LiveOrchestrator
from .recovery_orchestrator import RecoveryOrchestrator, RecoveryOutcome

logger = logging.getLogger(__name__)


class EngineLifecycle:
    """Coordinates recovery, live-trading auxiliary services, and shutdown."""

    # TODO(10.2): the spec sketch envisions
    # ``__init__(recovery, live, graceful_shutdown, audit_service)`` with a
    # pre-built GracefulShutdown injected. This implementation takes the raw
    # graceful-shutdown deps and constructs it post-recovery because
    # GracefulShutdown needs the live CrashRecoveryManager produced by the
    # recovery flow. The DI container in 10.2 will close that gap.
    def __init__(
        self,
        recovery: RecoveryOrchestrator,
        live: LiveOrchestrator,
        audit_service: AuditService | None,
        redis_manager: RedisStateManager | None,
        account_manager: AccountManager | None,
        snapshot_service: SnapshotService | None,
    ) -> None:
        self._recovery = recovery
        self._live = live
        self._audit_service = audit_service
        self._redis_manager = redis_manager
        self._account_manager = account_manager
        self._snapshot_service = snapshot_service

        self._running = False
        self._shutdown_event = asyncio.Event()
        self._graceful_shutdown: GracefulShutdown | None = None
        self._recovery_outcome: RecoveryOutcome | None = None
        self._shutdown_result: ShutdownResult | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def recovery_result(self) -> CrashRecoveryResult | None:
        return self._recovery_outcome.crash_result if self._recovery_outcome else None

    @property
    def reconciliation_results(self) -> dict[str, ReconciliationResult] | None:
        return (
            self._recovery_outcome.reconciliation_results
            if self._recovery_outcome
            else None
        )

    @property
    def pnl_recalculation_results(self) -> dict[str, RecalculationResult] | None:
        return (
            self._recovery_outcome.pnl_recalculation_results
            if self._recovery_outcome
            else None
        )

    @property
    def resume_result(self) -> ResumeResult | None:
        return (
            self._recovery_outcome.resume_result if self._recovery_outcome else None
        )

    @property
    def shutdown_result(self) -> ShutdownResult | None:
        return self._shutdown_result

    @property
    def trade_db_writer(self) -> object | None:
        return self._live.trade_db_writer

    @property
    def violation_service(self) -> object | None:
        return self._live.violation_service

    def _on_lock_lost(self) -> None:
        """Triggered when CrashRecoveryManager detects the process lock was lost."""
        logger.critical("Process lock lost! Triggering emergency shutdown.")
        if self._audit_service is not None:
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

    async def run(self) -> None:
        """Execute the full lifecycle: recovery → live start → wait → cleanup."""
        self._recovery_outcome = await self._recovery.run(self._on_lock_lost)
        await self._live.start(self._recovery_outcome.cold_storage_writer)
        self._init_graceful_shutdown(self._recovery_outcome.crash_recovery)

        logger.info("Trading Engine v0.1.0 running")
        self._running = True
        self._audit_engine_start()

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
            try:
                await self._shutdown_event.wait()
            except asyncio.CancelledError:
                logger.info("Engine run loop cancelled")

        await self._audit_engine_stopped()
        await self._live.stop()
        if self._audit_service is not None:
            await self._audit_service.stop()

        self._running = False
        logger.info("Trading Engine stopped")

    async def shutdown(self) -> None:
        """Trigger graceful shutdown. Idempotent — no-op if not running."""
        if not self._running:
            return

        logger.info("Shutdown requested via Engine.shutdown()")

        if self._audit_service is not None:
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
        else:
            self._running = False
            self._shutdown_event.set()
            crash_recovery = (
                self._recovery_outcome.crash_recovery
                if self._recovery_outcome
                else None
            )
            if crash_recovery is not None:
                await crash_recovery.shutdown_sequence()

    def _init_graceful_shutdown(
        self, crash_recovery: CrashRecoveryManager | None
    ) -> None:
        if self._redis_manager is None or self._account_manager is None:
            logger.warning(
                "Graceful shutdown requires redis_manager and account_manager"
            )
            return
        self._graceful_shutdown = GracefulShutdown(
            redis_manager=self._redis_manager,
            account_manager=self._account_manager,
            snapshot_service=self._snapshot_service,
            zmq_adapter=self._recovery.zmq_adapter,
            crash_recovery=crash_recovery,
            cold_storage_service=self._live.cold_storage_service,
        )
        self._graceful_shutdown.register_signal_handlers()
        logger.info("Graceful shutdown handler initialized")

    def _audit_engine_start(self) -> None:
        if self._audit_service is None:
            return
        start_context: dict = {"version": "0.1.0"}
        crash_result = (
            self._recovery_outcome.crash_result if self._recovery_outcome else None
        )
        if crash_result is not None and crash_result.recovery_mode:
            start_context["recovery_mode"] = True
            start_context["accounts_recovered"] = crash_result.accounts_needing_recovery
        task = asyncio.create_task(
            self._audit_service.log_system_event(
                event_subtype="engine_start",
                message="Trading Engine started",
                context=start_context,
            ),
            name="audit_engine_start",
        )
        task.add_done_callback(audit_task_done_callback)

    async def _audit_engine_stopped(self) -> None:
        if self._audit_service is None:
            return
        shutdown_success = (
            self._shutdown_result.success if self._shutdown_result else True
        )
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
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            logger.warning(
                "Failed to buffer engine_stopped audit entry", exc_info=True
            )
