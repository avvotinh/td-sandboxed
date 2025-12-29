"""Account Manager - Manages trading account lifecycle and state."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

from .models import AccountConfig, AccountsConfig
from .state import AccountState

if TYPE_CHECKING:
    from ..adapters.mt5_connection_manager import ConnectionHealth, MT5ConnectionManager
    from ..state.redis_state import RedisStateManager
    from .signal_router import SignalRouter

logger = logging.getLogger(__name__)

# Type alias for signal handler function
SignalHandler = Callable[[str], Awaitable[None]]
"""Signal handler receives account_id and processes pending signals for that account.

Example implementation:
    async def process_account_signals(account_id: str) -> None:
        '''Process pending signals for an account.'''
        # Get pending signals from Redis or message queue
        signals = await get_pending_signals(account_id)
        for signal in signals:
            await strategy.on_signal(account_id, signal)
"""


class AccountManager:
    """Manages trading account lifecycle and state.

    The AccountManager handles:
    - Account state transitions (start, stop, pause, resume)
    - State persistence to Redis
    - Account configuration validation

    State Machine:
        active ↔ paused
        active/paused → stopped
        stopped → active (restart)
        any → error (system-initiated)
        error → stopped (acknowledge)
    """

    def __init__(self, redis_manager: "RedisStateManager") -> None:
        """Initialize AccountManager.

        Args:
            redis_manager: Redis state manager for persistence.
        """
        self._redis = redis_manager
        self._accounts: dict[str, AccountConfig] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._signal_handler: SignalHandler | None = None
        self._error_counts: dict[str, int] = {}  # Track error count per account
        self._accounts_lock = asyncio.Lock()  # Protect account mutations
        self._signal_router: "SignalRouter | None" = None  # Optional signal router
        self._mt5_connection_manager: "MT5ConnectionManager | None" = None  # Per-account connections

    def load_accounts(self, config: AccountsConfig) -> None:
        """Load account configurations for validation.

        Args:
            config: AccountsConfig with account definitions.
        """
        self._accounts = {acc.id: acc for acc in config.accounts}

    def set_signal_handler(self, handler: SignalHandler) -> None:
        """Set the signal processing callback for accounts.

        Args:
            handler: Async function that takes account_id and processes signals.
                     Called on each loop iteration for active accounts.
        """
        self._signal_handler = handler

    def set_signal_router(self, router: "SignalRouter") -> None:
        """Register a SignalRouter for automatic mapping updates.

        When registered, the router's rebuild_mapping() is called automatically
        when accounts are added via add_account().

        Args:
            router: SignalRouter instance to register.
        """
        self._signal_router = router

    def get_signal_router(self) -> "SignalRouter | None":
        """Get the registered SignalRouter.

        Returns:
            The registered SignalRouter or None if not registered.
        """
        return self._signal_router

    def set_mt5_connection_manager(self, manager: "MT5ConnectionManager") -> None:
        """Register an MT5ConnectionManager for per-account connections.

        When registered, connection lifecycle is managed automatically:
        - start_connection() called when account transitions to "active"
        - stop_connection() called when account transitions to "stopped"

        Args:
            manager: MT5ConnectionManager instance to register.
        """
        self._mt5_connection_manager = manager

    def get_mt5_connection_manager(self) -> "MT5ConnectionManager | None":
        """Get the registered MT5ConnectionManager.

        Returns:
            The registered MT5ConnectionManager or None if not registered.
        """
        return self._mt5_connection_manager

    def get_connection_health(self, account_id: str) -> "ConnectionHealth | None":
        """Get MT5 connection health for an account.

        Args:
            account_id: Account to get connection health for.

        Returns:
            ConnectionHealth if MT5ConnectionManager is registered, None otherwise.
        """
        if self._mt5_connection_manager is None:
            return None
        return self._mt5_connection_manager.get_health(account_id)

    async def start_all_accounts(self) -> None:
        """Start all accounts with status 'active' concurrently.

        Each account runs in its own asyncio.Task with isolated error handling.
        If MT5ConnectionManager is registered, also starts per-account MT5 connections.

        Note: AccountConfig.status is a string field with pattern validation.
        """
        # Start MT5 connections first if manager is registered
        if self._mt5_connection_manager is not None:
            await self._mt5_connection_manager.start_all_connections()

        for account_id, account in self._accounts.items():
            if account.status == "active":
                await self._spawn_account_task(account_id)

        logger.info(f"Started {len(self._tasks)} account tasks")

    async def _spawn_account_task(self, account_id: str) -> None:
        """Spawn a new task for an account."""
        if account_id in self._tasks:
            logger.warning(f"Account {account_id} task already running")
            return

        task = asyncio.create_task(
            self._run_account_loop(account_id),
            name=f"account-{account_id}",
        )
        self._tasks[account_id] = task
        await self._redis.save_account_status(account_id, "active")
        logger.info(f"Spawned task for account {account_id}")

    async def _run_account_loop(self, account_id: str) -> None:
        """Main loop for a single account - runs until stopped or error.

        CRITICAL: This loop is isolated - errors here do NOT affect other accounts.
        """
        try:
            logger.info(f"Account {account_id} loop started")

            while True:
                # Update health heartbeat
                await self._update_health(account_id)

                # Check if we should stop
                status = await self._redis.get_account_status(account_id)
                if status in ("stopped", "paused"):
                    logger.info(f"Account {account_id} loop exiting: status={status}")
                    break

                # Process signals if handler is set
                if self._signal_handler:
                    await self._signal_handler(account_id)

                # Small sleep to prevent busy loop
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.info(f"Account {account_id} task cancelled")
            raise
        except Exception as e:
            logger.exception(f"Account {account_id} error: {e}")
            await self._handle_account_error(account_id, e)
        finally:
            await self._clear_health(account_id)
            self._tasks.pop(account_id, None)

    async def _handle_account_error(self, account_id: str, error: Exception) -> None:
        """Handle account error - set error state, increment count, and publish alert."""
        # Increment error count
        self._error_counts[account_id] = self._error_counts.get(account_id, 0) + 1

        await self.set_error(account_id)
        await self._redis.save_account_last_error(account_id, str(error))
        await self._publish_alert(
            account_id,
            "error",
            f"Account {account_id} encountered error: {error}",
        )

    async def _update_health(self, account_id: str) -> None:
        """Update account health heartbeat in Redis."""
        error_count = self._error_counts.get(account_id, 0)
        await self._redis.update_account_health(
            account_id,
            {
                "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                "status": "healthy",
                "error_count": str(error_count),
            },
        )

    async def _clear_health(self, account_id: str) -> None:
        """Clear account health data on stop."""
        await self._redis.clear_account_health(account_id)

    async def _publish_alert(
        self, account_id: str, alert_type: str, message: str
    ) -> None:
        """Publish alert to Redis pub/sub channel."""
        await self._redis.publish_alert(account_id, alert_type, message)

    def _validate_account_exists(self, account_id: str) -> None:
        """Validate account exists in configuration.

        Args:
            account_id: Account ID to validate.

        Raises:
            ValueError: If account not found in configuration.
        """
        if account_id not in self._accounts:
            available = list(self._accounts.keys())
            raise ValueError(
                f"Account '{account_id}' not found in configuration. "
                f"Available accounts: {available}"
            )

    async def start_account(self, account_id: str) -> None:
        """Start a trading account (set to active from stopped or new).

        Args:
            account_id: Account ID to start.

        Raises:
            ValueError: If account not found or invalid state transition.
        """
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)
        target = AccountState.ACTIVE

        # New account (no prior state) - initialize as active
        if current is None:
            await self._redis.save_account_status(account_id, target.value)
            return

        current_state = AccountState(current)
        if not current_state.can_transition_to(target):
            raise ValueError(
                f"Cannot transition account '{account_id}' from '{current}' to '{target.value}'"
            )

        await self._redis.save_account_status(account_id, target.value)

    async def stop_account(self, account_id: str) -> None:
        """Stop a trading account - cancel task and update status.

        This method is safe to call even if the account task isn't running.
        Also stops the MT5 connection if MT5ConnectionManager is registered.

        Args:
            account_id: Account ID to stop.

        Raises:
            ValueError: If account not found.
        """
        self._validate_account_exists(account_id)

        # Cancel the task if running
        if account_id in self._tasks:
            task = self._tasks[account_id]
            task.cancel()
            try:
                # Wait for task to complete cancellation (up to 30s)
                await asyncio.wait_for(task, timeout=30.0)
            except asyncio.CancelledError:
                # Expected - task was cancelled successfully
                pass
            except asyncio.TimeoutError:
                # Task didn't respond to cancellation in time
                logger.warning(f"Account {account_id} task did not stop within timeout")
            finally:
                self._tasks.pop(account_id, None)

        # Stop MT5 connection if manager is registered
        if self._mt5_connection_manager is not None:
            await self._mt5_connection_manager.stop_connection(account_id)

        current = await self.get_account_status(account_id)

        # Allow stop from any state except already stopped
        if current == AccountState.STOPPED.value:
            return  # Already stopped, idempotent

        await self._redis.save_account_status(account_id, AccountState.STOPPED.value)
        logger.info(f"Account {account_id} stopped")

    async def pause_account(self, account_id: str) -> None:
        """Pause a trading account temporarily.

        Args:
            account_id: Account ID to pause.

        Raises:
            ValueError: If account not found or invalid state transition.
        """
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)
        target = AccountState.PAUSED

        if current is None:
            raise ValueError(
                f"Cannot pause account '{account_id}' - no prior state. Start it first."
            )

        current_state = AccountState(current)
        if not current_state.can_transition_to(target):
            raise ValueError(
                f"Cannot transition account '{account_id}' from '{current}' to '{target.value}'"
            )

        await self._redis.save_account_status(account_id, target.value)

    async def resume_account(self, account_id: str) -> None:
        """Resume a paused account (paused → active).

        Args:
            account_id: Account ID to resume.

        Raises:
            ValueError: If account not found or not paused.
        """
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)

        if current != AccountState.PAUSED.value:
            raise ValueError(
                f"Cannot resume account '{account_id}' - not paused (current: {current})"
            )

        await self._redis.save_account_status(account_id, AccountState.ACTIVE.value)

    async def acknowledge_error(self, account_id: str) -> None:
        """Acknowledge error state and transition to stopped.

        Args:
            account_id: Account ID to acknowledge error.

        Raises:
            ValueError: If account not found or not in error state.
        """
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)

        if current != AccountState.ERROR.value:
            raise ValueError(
                f"Account '{account_id}' is not in error state (current: {current})"
            )

        await self._redis.save_account_status(account_id, AccountState.STOPPED.value)

    async def set_error(self, account_id: str) -> None:
        """Set account to error state (system-initiated).

        Args:
            account_id: Account ID to set to error.

        Raises:
            ValueError: If account not found.
        """
        self._validate_account_exists(account_id)
        await self._redis.save_account_status(account_id, AccountState.ERROR.value)

    async def get_account_status(self, account_id: str) -> str | None:
        """Get current status of an account.

        Args:
            account_id: Account ID to get status for.

        Returns:
            Current status string or None if no status set.
        """
        return await self._redis.get_account_status(account_id)

    async def get_all_statuses(self) -> dict[str, str]:
        """Get status of all configured accounts.

        Returns:
            Dictionary of account_id -> status.
        """
        statuses = {}
        for account_id in self._accounts:
            status = await self._redis.get_account_status(account_id)
            statuses[account_id] = status or "unknown"
        return statuses

    async def add_account(self, account_id: str, config: AccountsConfig) -> None:
        """Hot-reload: Add a new account while others are running.

        This operation is atomic - the account is added and started (if active)
        within a single lock acquisition to prevent race conditions.
        Also starts the MT5 connection if MT5ConnectionManager is registered.

        Args:
            account_id: Account ID to add.
            config: Fresh AccountsConfig with new account.

        Raises:
            ValueError: If account not found in config or already loaded.
        """
        # Find the new account in config (outside lock - read-only)
        new_account = next(
            (acc for acc in config.accounts if acc.id == account_id),
            None,
        )
        if not new_account:
            raise ValueError(f"Account {account_id} not found in config")

        # Atomic add + start operation
        async with self._accounts_lock:
            if account_id in self._accounts:
                raise ValueError(f"Account {account_id} already loaded")

            # Add to accounts dict and start atomically
            self._accounts[account_id] = new_account

            # Update signal router mapping if registered
            if self._signal_router is not None:
                self._signal_router.add_account(new_account)

            # Start if status is active (within lock for atomicity)
            if new_account.status == "active":
                # Start MT5 connection if manager is registered
                if self._mt5_connection_manager is not None:
                    await self._mt5_connection_manager.start_connection(account_id)

                await self._spawn_account_task(account_id)

            logger.info(f"Hot-loaded account {account_id}")

    async def shutdown(self) -> None:
        """Gracefully shutdown all account tasks and close connections.

        This is the preferred method for stopping the AccountManager.
        It:
        1. Stops all MT5 connections gracefully (if registered)
        2. Stops all account tasks gracefully
        3. Closes the Redis connection
        """
        logger.info("Shutting down all account tasks...")

        # Stop all MT5 connections first
        if self._mt5_connection_manager is not None:
            await self._mt5_connection_manager.stop_all_connections()

        # Cancel all tasks
        for account_id, task in list(self._tasks.items()):
            task.cancel()

        # Wait for all tasks to complete
        if self._tasks:
            await asyncio.gather(
                *self._tasks.values(),
                return_exceptions=True,
            )

        self._tasks.clear()
        await self._redis.close()
        logger.info("All account tasks shut down")

    async def close(self) -> None:
        """Close Redis connection gracefully.

        Note: For proper cleanup with running tasks, use shutdown() instead.
        """
        await self._redis.close()
