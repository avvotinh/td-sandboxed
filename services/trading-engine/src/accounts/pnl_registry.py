"""PnLTrackerRegistry - Registry for per-account P&L trackers.

Manages per-account PnLTracker instances with complete isolation:
- Each account gets its own PnLTracker
- No state is shared between accounts
- Broadcasts tick updates to relevant trackers
"""

import asyncio
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from .pnl_tracker import PnLTracker

if TYPE_CHECKING:
    from .risk_registry import RiskStateRegistry
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


class PnLTrackerRegistry:
    """Registry for per-account P&L trackers.

    Ensures complete isolation between accounts:
    - Each account gets its own PnLTracker instance
    - No state is shared between trackers
    - Tick updates are routed only to relevant trackers

    Example:
        registry = PnLTrackerRegistry(risk_registry, redis_manager)

        # Create tracker for account
        tracker = await registry.get_or_create("ftmo-001", Decimal("100000"))

        # Broadcast tick to all relevant trackers
        await registry.on_tick_all("XAUUSD", Decimal("1850.25"), Decimal("1850.50"))

        # Get exposure for account
        exposure = registry.get_total_exposure("ftmo-001")
    """

    def __init__(
        self,
        risk_registry: "RiskStateRegistry",
        redis_manager: "RedisStateManager | None" = None,
    ) -> None:
        """Initialize P&L tracker registry.

        Args:
            risk_registry: RiskStateRegistry for equity updates
            redis_manager: Optional Redis manager for balance persistence
        """
        self._risk_registry = risk_registry
        self._redis = redis_manager
        self._trackers: dict[str, PnLTracker] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, account_id: str) -> asyncio.Lock:
        """Get or create lock for account.

        Uses setdefault for atomic get-or-create.

        Args:
            account_id: Account identifier

        Returns:
            asyncio.Lock for the account
        """
        return self._locks.setdefault(account_id, asyncio.Lock())

    async def get_or_create(
        self,
        account_id: str,
        initial_balance: Decimal | None = None,
    ) -> PnLTracker:
        """Get or create P&L tracker for an account.

        Args:
            account_id: Account identifier
            initial_balance: Starting balance (required for new trackers)

        Returns:
            PnLTracker for the specified account

        Raises:
            ValueError: If creating new tracker without initial_balance
        """
        if account_id in self._trackers:
            return self._trackers[account_id]

        if initial_balance is None:
            # Try to get balance from Redis
            if self._redis:
                balance = await self._redis.get_account_balance(account_id)
                if balance is not None:
                    initial_balance = balance
                else:
                    initial_balance = Decimal("0")
                    logger.warning(
                        f"No balance found for {account_id}, using 0"
                    )
            else:
                raise ValueError(
                    f"initial_balance required for new tracker: {account_id}"
                )

        tracker = PnLTracker(
            account_id=account_id,
            initial_balance=initial_balance,
            risk_registry=self._risk_registry,
            redis_manager=self._redis,
        )
        self._trackers[account_id] = tracker
        logger.debug(f"Created P&L tracker for {account_id}")

        return tracker

    def get(self, account_id: str) -> PnLTracker | None:
        """Get existing tracker for an account.

        Args:
            account_id: Account identifier

        Returns:
            PnLTracker if exists, None otherwise
        """
        return self._trackers.get(account_id)

    async def on_tick_all(
        self,
        symbol: str,
        bid: Decimal,
        ask: Decimal,
    ) -> None:
        """Broadcast tick update to all trackers with positions in symbol.

        Only updates trackers that have open positions for the symbol
        (fast-path optimization for efficiency).

        Args:
            symbol: Trading symbol
            bid: Current bid price (Decimal)
            ask: Current ask price (Decimal)
        """
        for account_id, tracker in self._trackers.items():
            if tracker.has_position_for_symbol(symbol):
                async with self._get_lock(account_id):
                    await tracker.on_tick(symbol, bid, ask)

    def get_open_positions_count(self, account_id: str) -> int:
        """Get count of open positions for an account.

        Args:
            account_id: Account identifier

        Returns:
            Number of open positions (0 if tracker not found)
        """
        tracker = self._trackers.get(account_id)
        return tracker.get_open_positions_count() if tracker else 0

    def get_total_exposure(self, account_id: str) -> Decimal:
        """Get total exposure for an account.

        Args:
            account_id: Account identifier

        Returns:
            Total exposure (0 if tracker not found)
        """
        tracker = self._trackers.get(account_id)
        return tracker.get_total_exposure() if tracker else Decimal("0")

    def get_total_position_lots(self, account_id: str) -> Decimal:
        """Get total lots across all open positions for an account.

        Args:
            account_id: Account identifier

        Returns:
            Total volume in lots (0 if tracker not found)
        """
        tracker = self._trackers.get(account_id)
        if not tracker:
            return Decimal("0")
        return sum(p.volume for p in tracker._positions.values())

    def get_all_trackers(self) -> dict[str, PnLTracker]:
        """Get all registered trackers.

        Returns:
            Dict mapping account_id to PnLTracker
        """
        return self._trackers.copy()

    async def reset_daily_all(self, account_balances: dict[str, Decimal]) -> None:
        """Reset daily P&L for all trackers at their session reset boundary.

        Caller is responsible for invoking this once per local trading day
        per ``FirmProfile.session`` (was: midnight UTC).

        Args:
            account_balances: Dict of account_id -> starting balance
        """
        for account_id, balance in account_balances.items():
            tracker = self._trackers.get(account_id)
            if tracker:
                tracker.reset_daily(balance)

        logger.info(f"Reset daily P&L for {len(account_balances)} trackers")
