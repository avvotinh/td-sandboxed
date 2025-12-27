"""Data routing for strategy market data.

This module provides routing of market data (bars, ticks) from adapters
to account strategies based on signal filtering rules.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.adapters.redis_models import Bar
    from src.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class HasStrategy(Protocol):
    """Protocol for objects with a strategy and signal filter."""

    strategy_instance: BaseStrategy | None
    strategy: str
    status: str

    @property
    def signal_filter(self):
        """Signal filter configuration."""
        ...


class StrategyDataRouter:
    """Routes market data from adapters to account strategies.

    Provides callbacks for bar and tick data that route to appropriate
    strategy instances based on account configuration and signal filters.

    Example:
        router = StrategyDataRouter(accounts)
        redis_adapter.set_bar_callback(router.route_bar)
        zmq_adapter.set_tick_callback(router.route_tick)
    """

    def __init__(self, accounts: list[HasStrategy]):
        """Initialize data router.

        Args:
            accounts: List of account configurations with strategy instances
        """
        self._accounts = accounts

    def route_bar(self, bar: Bar) -> None:
        """Route bar data to matching account strategies.

        Routes bar to all active accounts whose signal filter
        allows the bar's symbol.

        Args:
            bar: Bar data to route
        """
        for account in self._accounts:
            if not self._should_route_to_account(account, bar.symbol):
                continue

            strategy = getattr(account, 'strategy_instance', None)
            if strategy is None:
                continue

            try:
                strategy.on_bar(bar)
            except Exception as e:
                logger.error(
                    "Error routing bar to strategy %s: %s",
                    account.strategy,
                    e,
                )

    async def route_bar_async(self, bar: Bar) -> None:
        """Async version of bar routing.

        Args:
            bar: Bar data to route
        """
        self.route_bar(bar)

    def route_tick(self, tick) -> None:
        """Route tick data to matching account strategies.

        Routes tick to all active accounts whose signal filter
        allows the tick's symbol.

        Args:
            tick: Tick data to route (with .symbol attribute)
        """
        symbol = getattr(tick, 'symbol', None)
        if symbol is None:
            return

        for account in self._accounts:
            if not self._should_route_to_account(account, symbol):
                continue

            strategy = getattr(account, 'strategy_instance', None)
            if strategy is None:
                continue

            try:
                if hasattr(strategy, 'on_tick'):
                    strategy.on_tick(tick)
            except Exception as e:
                logger.error(
                    "Error routing tick to strategy %s: %s",
                    account.strategy,
                    e,
                )

    async def route_tick_async(self, tick) -> None:
        """Async version of tick routing.

        Args:
            tick: Tick data to route
        """
        self.route_tick(tick)

    def _should_route_to_account(self, account: HasStrategy, symbol: str) -> bool:
        """Check if data should be routed to an account.

        Args:
            account: Account to check
            symbol: Symbol of the data

        Returns:
            True if data should be routed to this account
        """
        # Skip inactive accounts
        if account.status != "active":
            return False

        # Get signal filter
        signal_filter = getattr(account, 'signal_filter', None)
        if signal_filter is None:
            return True  # No filter = allow all

        # Check symbol filter
        allowed_symbols = getattr(signal_filter, 'symbols', [])
        if not allowed_symbols:
            return True  # Empty = allow all

        # Normalize and compare
        symbol_upper = symbol.upper()
        allowed_upper = [s.upper() for s in allowed_symbols]
        return symbol_upper in allowed_upper

    def get_bar_callback(self) -> Callable[[Bar], None]:
        """Get sync callback for bar routing.

        Returns:
            Callback function for bar routing
        """
        return self.route_bar

    def get_bar_callback_async(self) -> Callable[[Bar], Awaitable[None]]:
        """Get async callback for bar routing.

        Returns:
            Async callback function for bar routing
        """
        return self.route_bar_async

    def get_tick_callback(self) -> Callable:
        """Get sync callback for tick routing.

        Returns:
            Callback function for tick routing
        """
        return self.route_tick

    def get_tick_callback_async(self) -> Callable:
        """Get async callback for tick routing.

        Returns:
            Async callback function for tick routing
        """
        return self.route_tick_async
