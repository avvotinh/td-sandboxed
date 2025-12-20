"""Account Manager - Manages trading account lifecycle and state."""

from typing import TYPE_CHECKING

from .models import AccountsConfig
from .state import AccountState

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager


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
        self._accounts: dict[str, object] = {}

    def load_accounts(self, config: AccountsConfig) -> None:
        """Load account configurations for validation.

        Args:
            config: AccountsConfig with account definitions.
        """
        self._accounts = {acc.id: acc for acc in config.accounts}

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
        """Stop a trading account (does NOT close positions).

        Args:
            account_id: Account ID to stop.

        Raises:
            ValueError: If account not found.
        """
        self._validate_account_exists(account_id)
        current = await self.get_account_status(account_id)

        # Allow stop from any state except already stopped
        if current == AccountState.STOPPED.value:
            return  # Already stopped, idempotent

        await self._redis.save_account_status(account_id, AccountState.STOPPED.value)

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

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        await self._redis.close()
