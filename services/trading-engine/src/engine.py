"""Trading Engine Core Orchestration."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state.crash_recovery import CrashRecoveryManager, RecoveryResult
    from .state.redis_state import RedisStateManager

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
    ) -> None:
        """Initialize the trading engine.

        Args:
            redis_manager: Optional Redis state manager for crash recovery.
                          If provided, crash recovery will be enabled.
        """
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._redis_manager = redis_manager
        self._crash_recovery: CrashRecoveryManager | None = None
        self._recovery_result: RecoveryResult | None = None

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

        # Handle recovery mode if needed
        if result.recovery_mode:
            logger.warning(
                "Entering recovery mode for %d accounts",
                len(result.accounts_needing_recovery),
            )
            # Story 5.3 will implement position reconciliation here

        return result

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
