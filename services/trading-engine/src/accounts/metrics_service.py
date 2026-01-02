"""AccountMetricsService - Service for retrieving and updating account financial metrics.

Combines data from multiple sources:
- Balance: From MT5 via account:{id}:balance key
- Risk metrics: From RiskStateRegistry (Story 3.5)
- Real-time P&L: From PnLTrackerRegistry (Story 4.7)
- Account config: From AccountManager
"""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from .metrics import AccountMetrics

if TYPE_CHECKING:
    from ..state.redis_state import RedisStateManager
    from .account_manager import AccountManager
    from .pnl_registry import PnLTrackerRegistry
    from .risk_registry import RiskStateRegistry

logger = logging.getLogger(__name__)


class AccountMetricsService:
    """Service for retrieving and updating account financial metrics.

    Combines data from multiple sources:
    - Balance: From MT5 via account:{id}:balance key
    - Risk metrics: From RiskStateRegistry (Story 3.5)
    - Account config: From AccountManager

    CRITICAL: All operations are per-account isolated.

    Example:
        service = AccountMetricsService(redis, risk_registry, account_manager)

        # Get metrics for one account
        metrics = await service.get_account_metrics("ftmo-001")

        # Get metrics for all accounts
        all_metrics = await service.get_all_account_metrics()

        # Handle MT5 balance/equity update
        await service.on_mt5_balance_update("ftmo-001", balance, equity)
    """

    # Minimum interval between updates per account (milliseconds)
    DEBOUNCE_MS = 100

    def __init__(
        self,
        redis_manager: "RedisStateManager",
        risk_registry: "RiskStateRegistry",
        account_manager: "AccountManager",
        pnl_registry: "PnLTrackerRegistry | None" = None,
    ) -> None:
        """Initialize metrics service.

        Args:
            redis_manager: Redis state manager for balance storage
            risk_registry: Risk state registry for risk metrics
            account_manager: Account manager for account configs
            pnl_registry: Optional PnL tracker registry for real-time P&L
        """
        self._redis = redis_manager
        self._risk_registry = risk_registry
        self._account_manager = account_manager
        self._pnl_registry = pnl_registry
        self._last_update: dict[str, datetime] = {}
        self._update_lock = asyncio.Lock()

    def set_pnl_registry(self, registry: "PnLTrackerRegistry") -> None:
        """Register PnL tracker registry for real-time P&L metrics.

        Args:
            registry: PnLTrackerRegistry instance.
        """
        self._pnl_registry = registry
        logger.info("PnL registry registered with AccountMetricsService")

    async def get_account_metrics(self, account_id: str) -> AccountMetrics | None:
        """Get complete metrics for a single account.

        Combines data from:
        - Account config (name)
        - Redis (balance, status)
        - RiskStateRegistry (equity, P&L, drawdown)

        Args:
            account_id: Account identifier

        Returns:
            AccountMetrics if account exists, None otherwise
        """
        # Get account config
        account_config = self._account_manager.get_account(account_id)
        if not account_config:
            logger.warning(f"Account not found: {account_id}")
            return None

        # Get balance from Redis
        balance = await self._redis.get_account_balance(account_id)
        if balance is None:
            balance = Decimal("0")

        # Get risk state from registry
        risk_state = self._risk_registry.get_risk_state(account_id)

        # Get account status
        status = await self._redis.get_account_status(account_id) or "unknown"

        # Try to get real-time P&L metrics from PnLTracker
        pnl_tracker = None
        if self._pnl_registry:
            pnl_tracker = self._pnl_registry.get(account_id)

        # Build metrics combining all sources
        if pnl_tracker:
            # Use PnLTracker for real-time equity and unrealized P&L
            pnl_metrics = pnl_tracker.get_pnl_metrics()
            return AccountMetrics(
                account_id=account_id,
                account_name=account_config.name,
                status=status,
                balance=pnl_metrics.balance,
                equity=pnl_metrics.current_equity,
                daily_pnl=pnl_metrics.daily_pnl,
                daily_pnl_percent=pnl_metrics.daily_pnl_percent,
                peak_equity=risk_state.peak_equity if risk_state else pnl_metrics.balance,
                max_drawdown_percent=pnl_metrics.total_drawdown_percent,
                open_positions_count=pnl_metrics.open_positions_count,
                last_updated=datetime.now(timezone.utc),
            )
        elif risk_state:
            return AccountMetrics(
                account_id=account_id,
                account_name=account_config.name,
                status=status,
                balance=balance,
                equity=risk_state.current_equity,
                daily_pnl=risk_state.daily_pnl,
                daily_pnl_percent=risk_state.daily_pnl_percent,
                peak_equity=risk_state.peak_equity,
                max_drawdown_percent=risk_state.total_drawdown_percent,
                open_positions_count=0,  # No PnL tracker, no position tracking
                last_updated=risk_state.last_updated,
            )
        else:
            # No risk state or PnL tracker - use defaults with balance as equity
            return AccountMetrics(
                account_id=account_id,
                account_name=account_config.name,
                status=status,
                balance=balance,
                equity=balance,  # Default equity to balance when no risk state
                daily_pnl=Decimal("0"),
                daily_pnl_percent=Decimal("0"),
                peak_equity=balance,
                max_drawdown_percent=Decimal("0"),
                open_positions_count=0,
            )

    async def get_all_account_metrics(self) -> dict[str, AccountMetrics]:
        """Get metrics for all registered accounts.

        Returns:
            Dict mapping account_id to AccountMetrics
        """
        accounts = self._account_manager.get_all_accounts()
        metrics: dict[str, AccountMetrics] = {}

        for account_id in accounts:
            account_metrics = await self.get_account_metrics(account_id)
            if account_metrics:
                metrics[account_id] = account_metrics

        return metrics

    async def update_balance(self, account_id: str, balance: Decimal) -> None:
        """Update account balance from MT5.

        Args:
            account_id: Account identifier
            balance: New balance value
        """
        await self._redis.save_account_balance(account_id, balance)
        logger.debug(f"Updated balance for {account_id}: {balance}")

    async def on_mt5_balance_update(
        self,
        account_id: str,
        balance: Decimal,
        equity: Decimal,
    ) -> None:
        """Handle balance/equity update from MT5 with debouncing.

        Called when MT5 reports new account info. Uses per-account
        debouncing to prevent high-frequency update floods.

        Args:
            account_id: Account identifier
            balance: Current balance
            equity: Current equity (balance + unrealized P&L)
        """
        # Check debounce
        async with self._update_lock:
            now = datetime.now(timezone.utc)
            last = self._last_update.get(account_id)
            if last:
                elapsed_ms = (now - last).total_seconds() * 1000
                if elapsed_ms < self.DEBOUNCE_MS:
                    logger.debug(
                        f"Debounced update for {account_id}: {elapsed_ms:.1f}ms < {self.DEBOUNCE_MS}ms"
                    )
                    return  # Skip - too soon
            self._last_update[account_id] = now

        # Proceed with update (outside lock for concurrency)
        await self.update_balance(account_id, balance)
        await self._risk_registry.update_account_equity(account_id, equity)

        logger.info(
            f"MT5 update for {account_id}: balance={balance}, equity={equity}"
        )
