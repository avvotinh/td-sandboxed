"""AccountRiskManager - Per-account risk state manager.

Each account gets its own AccountRiskManager instance.
State is completely isolated - no cross-account contamination.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from .risk_state import RiskState

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager


class AccountRiskManager:
    """Per-account risk state manager.

    Each account gets its own AccountRiskManager instance.
    State is completely isolated - no cross-account contamination.

    Warning Levels (as percentage of limit):
        70% - First warning
        80% - Second warning
        90% - Critical warning
        100% - Violation (trading blocked)
    """

    WARNING_THRESHOLDS = [70, 80, 90]

    def __init__(
        self,
        account_id: str,
        redis_manager: "RedisStateManager",
        initial_state: RiskState | None = None,
    ) -> None:
        """Initialize risk manager for a specific account.

        Args:
            account_id: Account identifier (used for Redis key namespacing)
            redis_manager: Redis state manager for persistence
            initial_state: Optional initial state (from Redis recovery)
        """
        self._account_id = account_id
        self._redis = redis_manager
        self._state = initial_state or RiskState()

    @property
    def account_id(self) -> str:
        """Account ID this manager is responsible for."""
        return self._account_id

    @property
    def state(self) -> RiskState:
        """Current risk state (read-only access)."""
        return self._state

    async def update_equity(self, equity: Decimal) -> None:
        """Update account equity and persist to Redis.

        Args:
            equity: Current account equity
        """
        self._state.update_equity(equity)
        await self._persist_state()

    async def record_trade_pnl(self, realized_pnl: Decimal) -> None:
        """Record realized P&L from completed trade.

        Args:
            realized_pnl: Profit/loss from trade
        """
        self._state.record_trade(realized_pnl)
        await self._persist_state()

    def check_daily_loss_limit(self, limit_percent: Decimal) -> tuple[bool, Decimal]:
        """Check if daily loss limit is violated.

        Args:
            limit_percent: Maximum allowed daily loss (e.g., 5.0 for 5%)

        Returns:
            Tuple of (is_violated, current_percent)
        """
        current = abs(self._state.daily_pnl_percent)  # Loss is negative, take absolute
        is_violated = current >= limit_percent and self._state.daily_pnl < 0
        return (is_violated, self._state.daily_pnl_percent)

    def check_max_drawdown(self, limit_percent: Decimal) -> tuple[bool, Decimal]:
        """Check if max drawdown limit is violated.

        Args:
            limit_percent: Maximum allowed drawdown (e.g., 10.0 for 10%)

        Returns:
            Tuple of (is_violated, current_percent)
        """
        current = self._state.total_drawdown_percent
        is_violated = current >= limit_percent
        return (is_violated, current)

    def get_warning_level(self, limit_percent: Decimal) -> int | None:
        """Get warning level based on percentage of limit consumed.

        Warning levels represent how much of the limit has been used:
        - 70 = 70% of limit consumed (first warning)
        - 80 = 80% of limit consumed (second warning)
        - 90 = 90% of limit consumed (critical warning)

        Example: If limit is 5% and current loss is 4%, usage is 80%, returns 80

        Args:
            limit_percent: The limit being checked (e.g., 5.0 for 5%)

        Returns:
            Warning level (70, 80, 90) or None if below 70% of limit
        """
        if self._state.daily_pnl >= 0:
            return None  # No warning for profit

        if limit_percent <= 0:
            return None  # Invalid limit

        current_usage = abs(self._state.daily_pnl_percent) / limit_percent * 100

        for threshold in reversed(self.WARNING_THRESHOLDS):
            if current_usage >= threshold:
                return threshold
        return None

    async def reset_daily(self, starting_balance: Decimal) -> None:
        """Reset daily metrics at midnight UTC.

        Args:
            starting_balance: Balance at start of new day
        """
        self._state.reset_daily(starting_balance)
        await self._persist_state()

    async def _persist_state(self) -> None:
        """Persist state to Redis."""
        await self._redis.save_risk_state(self._account_id, self._state)
