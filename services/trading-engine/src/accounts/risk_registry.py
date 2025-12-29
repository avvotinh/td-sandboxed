"""RiskStateRegistry - Registry for per-account risk managers.

Ensures complete isolation between accounts:
- Each account gets its own AccountRiskManager
- No state is shared between accounts
- Operations are dispatched to correct account's manager
"""

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from .risk_manager import AccountRiskManager
from .risk_state import RiskState

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


class RiskStateRegistry:
    """Registry for per-account risk managers.

    Ensures complete isolation between accounts:
    - Each account gets its own AccountRiskManager
    - No state is shared between accounts
    - Operations are dispatched to correct account's manager

    Example:
        registry = RiskStateRegistry(redis_manager)

        # Update Account A - does NOT affect Account B
        await registry.update_account_equity("account-a", Decimal("99000"))

        # Check Account B - uses only Account B's state
        violated, current = await registry.check_account_violation(
            "account-b", "daily_loss", Decimal("5.0")
        )
    """

    def __init__(self, redis_manager: "RedisStateManager") -> None:
        """Initialize registry.

        Args:
            redis_manager: Redis state manager for persistence
        """
        self._redis = redis_manager
        self._risk_managers: dict[str, AccountRiskManager] = {}
        self._locks: dict[str, asyncio.Lock] = {}  # Per-account locks

    def _get_lock(self, account_id: str) -> asyncio.Lock:
        """Get or create lock for account.

        Uses setdefault for atomic get-or-create to prevent race conditions
        when multiple coroutines request locks for the same new account_id.

        Args:
            account_id: Account identifier

        Returns:
            asyncio.Lock for the account
        """
        # setdefault is atomic - prevents race condition where two coroutines
        # could create separate locks for the same account_id
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def get_or_create(self, account_id: str) -> AccountRiskManager:
        """Get or lazily create risk manager for an account.

        Args:
            account_id: Account identifier

        Returns:
            AccountRiskManager for the specified account
        """
        if account_id not in self._risk_managers:
            # Try to load existing state from Redis
            existing_state = await self._redis.get_risk_state(account_id)

            manager = AccountRiskManager(
                account_id=account_id,
                redis_manager=self._redis,
                initial_state=existing_state,
            )
            self._risk_managers[account_id] = manager
            logger.debug(f"Created risk manager for account {account_id}")

        return self._risk_managers[account_id]

    async def update_account_equity(self, account_id: str, equity: Decimal) -> None:
        """Update equity for a specific account (isolated).

        Args:
            account_id: Account to update
            equity: Current equity value
        """
        lock = self._get_lock(account_id)
        async with lock:
            manager = await self.get_or_create(account_id)
            await manager.update_equity(equity)

    async def record_account_trade(
        self, account_id: str, realized_pnl: Decimal
    ) -> None:
        """Record trade P&L for a specific account (isolated).

        Args:
            account_id: Account to update
            realized_pnl: Realized profit/loss
        """
        lock = self._get_lock(account_id)
        async with lock:
            manager = await self.get_or_create(account_id)
            await manager.record_trade_pnl(realized_pnl)

    async def check_account_violation(
        self, account_id: str, rule_type: str, limit: Decimal
    ) -> tuple[bool, Decimal]:
        """Check rule violation for a specific account (isolated).

        Args:
            account_id: Account to check
            rule_type: Type of rule ("daily_loss", "max_drawdown")
            limit: Limit percentage

        Returns:
            Tuple of (is_violated, current_value)

        Raises:
            ValueError: If unknown rule type
        """
        manager = await self.get_or_create(account_id)

        if rule_type == "daily_loss":
            return manager.check_daily_loss_limit(limit)
        elif rule_type == "max_drawdown":
            return manager.check_max_drawdown(limit)
        else:
            raise ValueError(f"Unknown rule type: {rule_type}")

    def get_risk_state(self, account_id: str) -> RiskState | None:
        """Get current risk state for an account.

        Args:
            account_id: Account to query

        Returns:
            RiskState if manager exists, None otherwise
        """
        manager = self._risk_managers.get(account_id)
        return manager.state if manager else None

    async def reset_daily_all(self, account_balances: dict[str, Decimal]) -> None:
        """Reset daily metrics for all accounts at midnight UTC.

        Args:
            account_balances: Dict of account_id -> starting balance
        """
        for account_id, balance in account_balances.items():
            manager = await self.get_or_create(account_id)
            await manager.reset_daily(balance)
        logger.info(f"Reset daily risk state for {len(account_balances)} accounts")

    async def record_violation(
        self,
        account_id: str,
        rule_type: str,
        current_value: Decimal,
        limit_value: Decimal,
    ) -> None:
        """Record rule violation to Redis for audit trail.

        Args:
            account_id: Account that violated rule
            rule_type: Type of rule violated
            current_value: Current metric value
            limit_value: Limit that was exceeded
        """
        await self._redis.record_risk_violation(
            account_id,
            rule_type,
            str(current_value),
            str(limit_value),
        )
        logger.warning(
            f"Recorded violation for {account_id}: {rule_type} "
            f"at {current_value}% (limit: {limit_value}%)"
        )

    async def pause_account_for_violation(
        self,
        account_id: str,
        reason: str,
    ) -> None:
        """Log that an account should be paused for a violation.

        NOTE: This method only logs the violation. It does NOT actually pause
        the account because RiskStateRegistry doesn't have access to AccountManager
        (to avoid circular dependencies).

        For actual account pausing, use RiskIsolationService._pause_for_violation()
        which coordinates between RiskStateRegistry and AccountManager.

        Args:
            account_id: Account that should be paused
            reason: Reason for pausing (logged for audit trail)
        """
        logger.warning(
            f"Risk violation detected for {account_id}: {reason}. "
            "Use RiskIsolationService for actual account pausing."
        )
