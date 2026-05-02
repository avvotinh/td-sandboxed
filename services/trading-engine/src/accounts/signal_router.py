"""Signal Router - Routes market data to appropriate accounts based on symbol filters.

This module provides O(1) symbol-to-accounts routing for multi-account trading.
The SignalRouter builds a hash map from symbols to account sets, enabling
efficient routing of market data to only the accounts that should receive it.

Integration Pattern:
    from src.accounts.signal_router import SignalRouter
    from src.accounts.account_manager import AccountManager

    # Create router with account manager
    router = SignalRouter(account_manager)

    # Route incoming bars
    account_ids = router.route_bar(bar)
    for account_id in account_ids:
        await process_for_account(account_id, bar)

    # On account changes, rebuild mapping
    await account_manager.add_account(new_account_id, config)
    router.rebuild_mapping()  # Automatically called if integrated
"""

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .account_manager import AccountManager
    from .models import AccountConfig
    from ..adapters.redis_models import Bar

logger = logging.getLogger(__name__)


@runtime_checkable
class HasSymbol(Protocol):
    """Protocol for objects with a symbol attribute (Bar, Tick, etc.)."""

    symbol: str


class SignalRouter:
    """Routes market signals to accounts based on symbol filters.

    Provides O(1) lookup for symbol → account mapping.

    Attributes:
        _account_manager: Reference to AccountManager for account data.
        _symbol_map: Dict mapping symbol (uppercase) → set of account_ids.
        _wildcard_accounts: Set of account_ids with no symbol filter (receive all).
    """

    def __init__(self, account_manager: "AccountManager") -> None:
        """Initialize SignalRouter.

        Args:
            account_manager: AccountManager instance to get account configurations.
        """
        self._account_manager = account_manager
        self._symbol_map: dict[str, set[str]] = {}
        self._wildcard_accounts: set[str] = set()
        self._build_symbol_mapping()

    def _build_symbol_mapping(self) -> None:
        """Build symbol → accounts hash map from current accounts.

        Accounts with empty symbol filters are tracked as wildcards
        and receive all symbols.
        """
        self._symbol_map.clear()
        self._wildcard_accounts.clear()

        for account_id, account in self._account_manager._accounts.items():
            # Skip non-active accounts
            if account.status != "active":
                continue

            signal_filter = account.signal_filter
            symbols = signal_filter.symbols if signal_filter else []

            if not symbols:
                # Empty filter = receive all symbols
                self._wildcard_accounts.add(account_id)
                logger.debug(f"Account {account_id} receives all symbols (no filter)")
            else:
                # Add account to each symbol's set
                for symbol in symbols:
                    symbol_upper = symbol.upper()
                    if symbol_upper not in self._symbol_map:
                        self._symbol_map[symbol_upper] = set()
                    self._symbol_map[symbol_upper].add(account_id)
                logger.debug(f"Account {account_id} filters for symbols: {symbols}")

        logger.info(
            f"Signal mapping built: {len(self._symbol_map)} symbols, "
            f"{len(self._wildcard_accounts)} wildcard accounts"
        )

    def route_symbol(self, symbol: str) -> list[str]:
        """Get account IDs that should receive data for a symbol.

        O(1) lookup via hash map.

        Args:
            symbol: Trading symbol (e.g., "XAUUSD").

        Returns:
            List of account IDs that should receive this symbol.
        """
        symbol_upper = symbol.upper()

        # Get accounts specifically filtering for this symbol
        specific_accounts = self._symbol_map.get(symbol_upper, set())

        # Combine with wildcard accounts (receive all)
        all_accounts = specific_accounts | self._wildcard_accounts

        if not all_accounts:
            logger.debug(
                f"No accounts for symbol {symbol}. "
                f"Available symbols: {list(self._symbol_map.keys())[:10]}"
            )

        return list(all_accounts)

    def route_bar(self, bar: "Bar") -> list[str]:
        """Route a bar to appropriate accounts.

        Args:
            bar: Bar object with .symbol attribute.

        Returns:
            List of account IDs that should receive this bar.
        """
        return self.route_symbol(bar.symbol)

    def route_tick(self, tick: HasSymbol) -> list[str]:
        """Route a tick to appropriate accounts.

        Args:
            tick: Tick object with .symbol attribute.

        Returns:
            List of account IDs that should receive this tick.
        """
        return self.route_symbol(tick.symbol)

    async def route_bar_async(self, bar: "Bar") -> list[str]:
        """Async variant of route_bar for callback signature compatibility.

        Note: This method exists for integration with async callback interfaces
        (e.g., RedisAdapter). The actual routing is synchronous since it only
        performs O(1) hash lookups with no I/O.

        Args:
            bar: Bar object with .symbol attribute.

        Returns:
            List of account IDs that should receive this bar.
        """
        return self.route_bar(bar)

    async def route_tick_async(self, tick: HasSymbol) -> list[str]:
        """Async variant of route_tick for callback signature compatibility.

        Args:
            tick: Tick object with .symbol attribute.

        Returns:
            List of account IDs that should receive this tick.
        """
        return self.route_tick(tick)

    def rebuild_mapping(self) -> None:
        """Rebuild the symbol → accounts mapping atomically.

        Uses copy-on-write pattern for thread safety - builds new
        mappings first, then atomically swaps references.

        Call this after account configuration changes.
        """
        logger.info("Rebuilding signal routing mapping")

        # Build new mappings (copy-on-write for thread safety)
        new_symbol_map: dict[str, set[str]] = {}
        new_wildcard_accounts: set[str] = set()

        for account_id, account in self._account_manager._accounts.items():
            if account.status != "active":
                continue

            signal_filter = account.signal_filter
            symbols = signal_filter.symbols if signal_filter else []

            if not symbols:
                new_wildcard_accounts.add(account_id)
            else:
                for symbol in symbols:
                    symbol_upper = symbol.upper()
                    if symbol_upper not in new_symbol_map:
                        new_symbol_map[symbol_upper] = set()
                    new_symbol_map[symbol_upper].add(account_id)

        # Atomic swap (Python GIL makes reference assignment atomic)
        self._symbol_map = new_symbol_map
        self._wildcard_accounts = new_wildcard_accounts

        logger.info(
            f"Signal mapping rebuilt: {len(self._symbol_map)} symbols, "
            f"{len(self._wildcard_accounts)} wildcard accounts"
        )

    def add_account(self, account: "AccountConfig") -> None:
        """Add an account to the routing mapping.

        More efficient than full rebuild for single account addition.

        Args:
            account: AccountConfig to add.
        """
        if account.status != "active":
            return

        account_id = account.id
        signal_filter = account.signal_filter
        symbols = signal_filter.symbols if signal_filter else []

        if not symbols:
            self._wildcard_accounts.add(account_id)
        else:
            for symbol in symbols:
                symbol_upper = symbol.upper()
                if symbol_upper not in self._symbol_map:
                    self._symbol_map[symbol_upper] = set()
                self._symbol_map[symbol_upper].add(account_id)

        logger.debug(f"Added account {account_id} to signal routing")

    def remove_account(self, account_id: str) -> None:
        """Remove an account from the routing mapping.

        Args:
            account_id: Account ID to remove.
        """
        # Remove from wildcard set
        self._wildcard_accounts.discard(account_id)

        # Remove from all symbol mappings
        for symbol_accounts in self._symbol_map.values():
            symbol_accounts.discard(account_id)

        # Clean up empty symbol entries
        self._symbol_map = {
            symbol: accounts
            for symbol, accounts in self._symbol_map.items()
            if accounts
        }

        logger.debug(f"Removed account {account_id} from signal routing")

    def get_routing_stats(self) -> dict:
        """Get routing statistics for monitoring.

        Returns:
            Dict with routing stats.
        """
        return {
            "symbol_count": len(self._symbol_map),
            "wildcard_account_count": len(self._wildcard_accounts),
            "symbols": list(self._symbol_map.keys()),
            "wildcard_accounts": list(self._wildcard_accounts),
        }

    def get_accounts_for_symbol(self, symbol: str) -> dict:
        """Get accounts that would receive a specific symbol (for debugging).

        Useful for troubleshooting routing configuration without sending
        actual market data.

        Args:
            symbol: Symbol to check routing for.

        Returns:
            Dict with routing details:
            - symbol: The normalized symbol
            - specific_accounts: Accounts with this symbol in filter
            - wildcard_accounts: Accounts receiving all symbols
            - total_accounts: Combined list
        """
        symbol_upper = symbol.upper()
        specific = list(self._symbol_map.get(symbol_upper, set()))
        wildcards = list(self._wildcard_accounts)
        return {
            "symbol": symbol_upper,
            "specific_accounts": specific,
            "wildcard_accounts": wildcards,
            "total_accounts": list(set(specific) | set(wildcards)),
        }
