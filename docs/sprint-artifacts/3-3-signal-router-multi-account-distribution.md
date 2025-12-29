# Story 3.3: Signal Router Multi-Account Distribution

Status: done

## Story

As a **developer**,
I want **signals routed to appropriate accounts based on symbol filters**,
So that **each account only receives relevant market data**.

## Acceptance Criteria

1. **AC1**: Given Account A filters for ["XAUUSD"] and Account B filters for ["BTCUSD"], when a bar for XAUUSD arrives, then only Account A receives the bar

2. **AC2**: Given Account A filters for ["XAUUSD"] and Account B filters for ["BTCUSD"], when a bar for BTCUSD arrives, then only Account B receives the bar

3. **AC3**: Given Account A and Account C both filter for ["EURUSD"], when a bar for EURUSD arrives, then both Account A and Account C receive the bar

4. **AC4**: Given a bar arrives for a symbol no account is trading, when the router processes the bar, then no accounts receive it and a DEBUG log is written

5. **AC5**: Symbol→accounts mapping is built on startup and updated on account changes (O(1) routing lookup via hash map)

## Tasks / Subtasks

### Task 1: Create SignalRouter Class (AC: 1, 2, 3, 4, 5)

- [x] 1.1: Create `src/accounts/signal_router.py` with `SignalRouter` class
- [x] 1.2: Constructor accepts `AccountManager` and builds symbol→accounts mapping
- [x] 1.3: Implement `_build_symbol_mapping()` that creates hash map from symbol → Set[account_id]
- [x] 1.4: Symbol normalization to uppercase for case-insensitive matching
- [x] 1.5: Handle empty filter (account receives all symbols) via special `"*"` entry or separate tracking

### Task 2: Implement O(1) Routing Logic (AC: 1, 2, 3, 4)

- [x] 2.1: Implement `route_bar(bar: Bar) -> list[str]` returns list of account_ids that should receive
- [x] 2.2: O(1) lookup: `symbol_map.get(symbol.upper(), set())`
- [x] 2.3: Handle wildcard accounts (empty filter = all symbols)
- [x] 2.4: Return combined set of matching accounts + wildcard accounts
- [x] 2.5: Async variant: `route_bar_async(bar: Bar) -> list[str]` (exists for callback signature compatibility - delegates to sync route_bar since hash lookups don't need await)

### Task 3: Implement DEBUG Logging for Unrouted Signals (AC: 4)

- [x] 3.1: Log when no accounts match: `DEBUG: No accounts for symbol {symbol}`
- [x] 3.2: Include available symbols in debug output for troubleshooting
- [x] 3.3: Ensure logging is DEBUG level only (no performance impact)

### Task 4: Implement Dynamic Mapping Updates (AC: 5)

- [x] 4.1: Implement `rebuild_mapping()` method to refresh symbol→accounts map
- [x] 4.2: Call rebuild on account add/remove (hook into AccountManager)
- [x] 4.3: Implement `add_account(account: AccountConfig)` for hot-reload
- [x] 4.4: Implement `remove_account(account_id: str)` for cleanup

### Task 5: Integration with AccountManager (AC: 1-5)

- [x] 5.1: Add `get_signal_router()` method to AccountManager or pass router to manager
- [x] 5.2: Ensure SignalRouter uses AccountManager's `_accounts` dict
- [x] 5.3: Hook `rebuild_mapping()` into AccountManager's `add_account()` method
- [x] 5.4: Document integration pattern in module docstring

### Task 6: Unit Tests for SignalRouter (AC: 1-5)

- [x] 6.1: Test single account single symbol routing
- [x] 6.2: Test multi-account different symbols (AC1, AC2)
- [x] 6.3: Test multi-account same symbol (AC3)
- [x] 6.4: Test no matching accounts with DEBUG log (AC4)
- [x] 6.5: Test mapping rebuild on account changes (AC5)
- [x] 6.6: Test empty filter routes all symbols
- [x] 6.7: Test case-insensitive symbol matching
- [x] 6.8: Test O(1) performance for 5 accounts (benchmark)

## Dev Notes

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Async:** asyncio for async routing
- **Pattern:** Hash map for O(1) symbol lookup

### Key Architecture Patterns

**Signal Router Role in Multi-Account System:**
```
┌───────────────────────┐
│    Signal Router      │
│  (filter per account) │
└───────────┬───────────┘
            ▲
            │ Incoming bars/ticks
            │
┌───────────────────────┐
│   Market Data Feed    │
│    (shared source)    │
└───────────────────────┘

Flow:
1. Market data arrives (XAUUSD bar)
2. SignalRouter.route_bar(bar) called
3. Router looks up symbol_map["XAUUSD"]
4. Returns [account_ids] that should receive
5. Each account processes independently
```

**Integration Flow: SignalRouter → StrategyDataRouter Pipeline:**
```
┌──────────────────────────────────────────────────────────────────────────┐
│                        SIGNAL ROUTING PIPELINE                            │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Redis Pub/Sub                                                           │
│  bars:XAUUSD:1m ──────────┐                                              │
│                           ▼                                              │
│                  ┌─────────────────┐                                     │
│                  │  RedisAdapter   │                                     │
│                  │  on_bar(bar)    │                                     │
│                  └────────┬────────┘                                     │
│                           │                                              │
│                           ▼                                              │
│                  ┌─────────────────────────────────────────┐             │
│                  │         SignalRouter.route_bar(bar)      │  ◄── NEW   │
│                  │  Returns: ["ftmo-gold-001", "5ers-001"] │             │
│                  └────────┬────────────────────────────────┘             │
│                           │                                              │
│              ┌────────────┴────────────┐                                 │
│              ▼                         ▼                                 │
│     ftmo-gold-001                5ers-001                                │
│              │                         │                                 │
│              ▼                         ▼                                 │
│  ┌─────────────────────┐   ┌─────────────────────┐                      │
│  │ StrategyDataRouter  │   │ StrategyDataRouter  │  ◄── EXISTING        │
│  │ route_bar(bar)      │   │ route_bar(bar)      │                      │
│  └──────────┬──────────┘   └──────────┬──────────┘                      │
│             ▼                         ▼                                  │
│     Strategy.on_bar(bar)      Strategy.on_bar(bar)                      │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

**Wiring SignalRouter into AccountManager Signal Handler:**
```python
# Example: Integrating SignalRouter with AccountManager
# In engine.py or main orchestration module:

from src.accounts.signal_router import SignalRouter
from src.accounts.account_manager import AccountManager
from src.strategies.data_router import StrategyDataRouter

# Setup
account_manager = AccountManager(redis_manager)
account_manager.load_accounts(config)

signal_router = SignalRouter(account_manager)
strategy_routers: dict[str, StrategyDataRouter] = {}  # Per-account

async def process_bar_for_accounts(bar: Bar) -> None:
    """Route bar to appropriate accounts via SignalRouter."""
    # Step 1: Get accounts that should receive this bar (O(1) lookup)
    account_ids = signal_router.route_bar(bar)

    # Step 2: For each account, route to its strategy
    for account_id in account_ids:
        if account_id in strategy_routers:
            strategy_routers[account_id].route_bar(bar)

# Connect to Redis adapter
redis_adapter.set_bar_callback(process_bar_for_accounts)
```

**From redis-py Context7 Research (2025-12-30):**
```python
# Async pub/sub pattern for signal distribution
import redis.asyncio as redis

async def reader(channel: redis.client.PubSub):
    while True:
        message = await channel.get_message(ignore_subscribe_messages=True, timeout=None)
        if message is not None:
            # Route to appropriate accounts
            accounts = signal_router.route_bar(parse_bar(message))
            for account_id in accounts:
                await process_for_account(account_id, message)
```

**From pyzmq Context7 Research (2025-12-30):**
```python
# PUB/SUB topic filtering (for future ZeroMQ integration)
# SUB sockets filter messages based on topic prefixes
# Example: sub.setsockopt(zmq.SUBSCRIBE, b'XAUUSD')
```

### File Locations

| File | Action | Purpose |
|------|--------|---------|
| `src/accounts/signal_router.py` | CREATE | SignalRouter class implementation |
| `src/accounts/__init__.py` | MODIFY | Export SignalRouter |
| `src/accounts/account_manager.py` | MODIFY | Optional: Add signal router integration |
| `tests/unit/test_signal_router.py` | CREATE | Unit tests for SignalRouter |
| `tests/integration/test_signal_routing.py` | CREATE | Integration tests with AccountManager |

### Existing Code Analysis

**Current StrategyDataRouter (src/strategies/data_router.py):**
- Already implements `_should_route_to_account()` for filtering
- Routes to strategies, not just accounts
- DEBUG logging for filtered signals already exists
- **DO NOT DUPLICATE** - SignalRouter is higher-level, routes to accounts

**Key Difference from data_router.py:**
- `StrategyDataRouter`: Routes bars to strategy instances (has `HasStrategy` protocol)
- `SignalRouter`: Routes symbols to account IDs (pure routing, no strategy execution)
- SignalRouter is called BEFORE StrategyDataRouter - determines which accounts
- StrategyDataRouter then handles per-account strategy execution

**Current AccountManager (src/accounts/account_manager.py:46-57):**
```python
def __init__(self, redis_manager: "RedisStateManager") -> None:
    self._redis = redis_manager
    self._accounts: dict[str, AccountConfig] = {}
    self._tasks: dict[str, asyncio.Task[None]] = {}
    self._signal_handler: SignalHandler | None = None
    self._error_counts: dict[str, int] = {}
    self._accounts_lock = asyncio.Lock()
```
- `_accounts` dict maps account_id → AccountConfig
- SignalRouter can access this for building symbol mapping

**SignalFilter Model (src/accounts/models.py:55-70):**
```python
class SignalFilter(BaseModel):
    """Signal filtering configuration."""
    symbols: list[str] = Field(default_factory=list, description="Allowed symbols")
    sessions: list[str] = Field(default_factory=list, description="Allowed sessions")
    max_spread_pips: Optional[float] = Field(default=None, ge=0)
```
- `symbols: list[str]` - allowed trading symbols
- Empty list means ALL symbols allowed

### Reference Implementation

**SignalRouter Class:**

```python
# src/accounts/signal_router.py
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .account_manager import AccountManager
    from .models import AccountConfig
    from ..adapters.redis_models import Bar

logger = logging.getLogger(__name__)


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
                logger.debug(
                    f"Account {account_id} filters for symbols: {symbols}"
                )

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

    def route_tick(self, tick) -> list[str]:
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

    async def route_tick_async(self, tick) -> list[str]:
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
```

### Testing Requirements

**Framework:** pytest + pytest-asyncio | **Location:** `tests/unit/`

```python
# tests/unit/test_signal_router.py

import pytest
from unittest.mock import Mock, MagicMock

from src.accounts.signal_router import SignalRouter
from src.accounts.models import AccountConfig, SignalFilter, MT5Config, AccountType


@pytest.fixture
def mock_account_manager():
    """Create mock AccountManager with test accounts."""
    manager = Mock()
    manager._accounts = {}
    return manager


def create_test_account(
    account_id: str,
    symbols: list[str] | None = None,
    status: str = "active"
) -> AccountConfig:
    """Create test account with given filters."""
    return AccountConfig(
        id=account_id,
        name=f"Test {account_id}",
        type=AccountType.DEMO,
        mt5=MT5Config(server="test", login=12345, password_env="TEST_PASS"),
        strategy="ma_crossover",
        signal_filter=SignalFilter(symbols=symbols or []),
        status=status,
    )


class TestSignalRouterBasicRouting:
    """Tests for basic signal routing functionality."""

    def test_routes_to_single_account_with_matching_symbol(self, mock_account_manager):
        """AC1: Route to account when symbol matches filter."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="XAUUSD")
        result = router.route_bar(bar)

        assert result == ["acc-a"]

    def test_routes_to_correct_account_among_multiple(self, mock_account_manager):
        """AC1, AC2: Route to correct account when multiple have different symbols."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        acc_b = create_test_account("acc-b", symbols=["BTCUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-b": acc_b}

        router = SignalRouter(mock_account_manager)

        # XAUUSD goes to acc-a only
        bar_gold = Mock(symbol="XAUUSD")
        result_gold = router.route_bar(bar_gold)
        assert result_gold == ["acc-a"]

        # BTCUSD goes to acc-b only
        bar_btc = Mock(symbol="BTCUSD")
        result_btc = router.route_bar(bar_btc)
        assert result_btc == ["acc-b"]

    def test_routes_to_multiple_accounts_same_symbol(self, mock_account_manager):
        """AC3: Route to multiple accounts when both filter for same symbol."""
        acc_a = create_test_account("acc-a", symbols=["EURUSD"])
        acc_c = create_test_account("acc-c", symbols=["EURUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-c": acc_c}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="EURUSD")
        result = router.route_bar(bar)

        assert set(result) == {"acc-a", "acc-c"}

    def test_no_accounts_for_untraded_symbol(self, mock_account_manager, caplog):
        """AC4: No accounts receive symbol none are trading, DEBUG logged."""
        import logging
        caplog.set_level(logging.DEBUG)

        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="USDJPY")
        result = router.route_bar(bar)

        assert result == []
        assert "No accounts for symbol USDJPY" in caplog.text


class TestSignalRouterWildcardAccounts:
    """Tests for accounts with empty symbol filters (receive all)."""

    def test_empty_filter_receives_all_symbols(self, mock_account_manager):
        """Empty symbol filter means account receives all symbols."""
        account = create_test_account("acc-a", symbols=[])  # Empty = all
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        for symbol in ["XAUUSD", "BTCUSD", "EURUSD", "USDJPY"]:
            bar = Mock(symbol=symbol)
            result = router.route_bar(bar)
            assert "acc-a" in result, f"Wildcard account should receive {symbol}"

    def test_wildcard_combined_with_specific(self, mock_account_manager):
        """Wildcard accounts receive symbols along with specific accounts."""
        acc_wild = create_test_account("acc-wild", symbols=[])
        acc_gold = create_test_account("acc-gold", symbols=["XAUUSD"])
        mock_account_manager._accounts = {
            "acc-wild": acc_wild,
            "acc-gold": acc_gold,
        }

        router = SignalRouter(mock_account_manager)

        # XAUUSD should go to both wildcard and gold-specific
        bar_gold = Mock(symbol="XAUUSD")
        result = router.route_bar(bar_gold)
        assert set(result) == {"acc-wild", "acc-gold"}

        # BTCUSD should go to wildcard only
        bar_btc = Mock(symbol="BTCUSD")
        result = router.route_bar(bar_btc)
        assert result == ["acc-wild"]


class TestSignalRouterCaseInsensitive:
    """Tests for case-insensitive symbol matching."""

    def test_symbol_matching_case_insensitive(self, mock_account_manager):
        """Symbol matching should be case-insensitive."""
        account = create_test_account("acc-a", symbols=["xauusd"])  # lowercase
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="XAUUSD")  # UPPERCASE
        result = router.route_bar(bar)

        assert result == ["acc-a"]


class TestSignalRouterDynamicUpdates:
    """Tests for dynamic mapping updates (AC5)."""

    def test_rebuild_mapping_updates_routes(self, mock_account_manager):
        """rebuild_mapping() should update routes after account changes."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a}

        router = SignalRouter(mock_account_manager)

        # Initially routes to acc-a
        bar = Mock(symbol="XAUUSD")
        assert router.route_bar(bar) == ["acc-a"]

        # Add new account externally
        acc_b = create_test_account("acc-b", symbols=["XAUUSD"])
        mock_account_manager._accounts["acc-b"] = acc_b

        # Before rebuild, still only acc-a
        assert router.route_bar(bar) == ["acc-a"]

        # After rebuild, both accounts
        router.rebuild_mapping()
        assert set(router.route_bar(bar)) == {"acc-a", "acc-b"}

    def test_add_account_updates_mapping(self, mock_account_manager):
        """add_account() should incrementally update mapping."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a}

        router = SignalRouter(mock_account_manager)

        # Add account directly
        acc_b = create_test_account("acc-b", symbols=["BTCUSD"])
        router.add_account(acc_b)

        bar = Mock(symbol="BTCUSD")
        assert router.route_bar(bar) == ["acc-b"]

    def test_remove_account_updates_mapping(self, mock_account_manager):
        """remove_account() should remove from mapping."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        acc_b = create_test_account("acc-b", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-b": acc_b}

        router = SignalRouter(mock_account_manager)

        # Both receive initially
        bar = Mock(symbol="XAUUSD")
        assert set(router.route_bar(bar)) == {"acc-a", "acc-b"}

        # Remove acc-b
        router.remove_account("acc-b")
        assert router.route_bar(bar) == ["acc-a"]


class TestSignalRouterInactiveAccounts:
    """Tests for handling inactive accounts."""

    def test_inactive_accounts_not_routed(self, mock_account_manager):
        """Inactive accounts should not receive signals."""
        acc_active = create_test_account("acc-active", symbols=["XAUUSD"], status="active")
        acc_paused = create_test_account("acc-paused", symbols=["XAUUSD"], status="paused")
        acc_stopped = create_test_account("acc-stopped", symbols=["XAUUSD"], status="stopped")
        mock_account_manager._accounts = {
            "acc-active": acc_active,
            "acc-paused": acc_paused,
            "acc-stopped": acc_stopped,
        }

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="XAUUSD")
        result = router.route_bar(bar)

        assert result == ["acc-active"]


class TestSignalRouterPerformance:
    """Tests for O(1) routing performance."""

    @pytest.mark.benchmark
    def test_routing_is_o1(self, mock_account_manager):
        """Routing should be O(1) regardless of account count."""
        # Create 5 accounts with different symbols
        accounts = {}
        for i in range(5):
            acc = create_test_account(f"acc-{i}", symbols=[f"SYM{i}USD"])
            accounts[f"acc-{i}"] = acc
        mock_account_manager._accounts = accounts

        router = SignalRouter(mock_account_manager)

        # Routing should be constant time
        import time
        bar = Mock(symbol="SYM2USD")

        start = time.perf_counter()
        for _ in range(1000):
            router.route_bar(bar)
        duration = time.perf_counter() - start

        # 1000 lookups should complete in < 10ms (O(1))
        assert duration < 0.01, f"Routing took {duration*1000:.2f}ms for 1000 lookups"
```

### Context from Previous Stories

**From Story 3.2 (Account Manager Multi-Account Orchestration):**
- `AccountManager._accounts: dict[str, AccountConfig]` - accounts accessible
- Task orchestration with isolated error handling
- Hot-reload via `add_account()` method
- `_accounts_lock` for atomic operations

**From Story 2.9 (Signal Filtering by Symbol):**
- `StrategyDataRouter._should_route_to_account()` implements per-account filtering
- DEBUG logging pattern: `logger.debug(f"Filtered data for {symbol}...")`
- Case-insensitive matching via `.upper()` normalization
- Empty filter = allow all symbols

**Key Pattern from Story 2.9:**
```python
# Signal filtering is already implemented in data_router.py
# SignalRouter adds multi-account O(1) lookup layer ABOVE this
# Do NOT duplicate the filtering logic - use SignalRouter for account selection
```

### Anti-Patterns (DO NOT)

- **DO NOT** duplicate `_should_route_to_account()` logic from data_router.py
- **DO NOT** iterate over all accounts for each signal - use hash map O(1) lookup
- **DO NOT** forget case-insensitive matching - normalize symbols to uppercase
- **DO NOT** block on mapping rebuild - it should be fast
- **DO NOT** share mutable state without proper synchronization
- **DO NOT** forget to handle empty filters (wildcard accounts)

### Logging Considerations

**Production Logging Strategy:**
- **DEBUG level:** Use for "No accounts for symbol X" messages (current implementation)
- **INFO level:** Use for mapping rebuilds and account add/remove operations
- **Future consideration:** For high-frequency routing decisions (every bar), consider TRACE level logging (lower than DEBUG) to avoid log spam while maintaining troubleshooting capability. Python's logging doesn't have TRACE by default, but can be added:
```python
TRACE = 5
logging.addLevelName(TRACE, "TRACE")
logger.log(TRACE, f"Routed {symbol} to {len(accounts)} accounts")
```

### Redis Key Patterns (For Future Integration)

| Key Pattern | Type | Purpose |
|-------------|------|---------|
| `bars:{symbol}:{timeframe}` | Pub/Sub | Incoming bar data from tv-api |
| `ticks:{symbol}` | Pub/Sub | Incoming tick data |
| `account:{id}:status` | String | Account state (active/paused/stopped) |

### CLI Commands for Testing

```bash
# From services/trading-engine directory
cd services/trading-engine

# Run signal router tests
uv run pytest tests/unit/test_signal_router.py -v

# Run with coverage
uv run pytest tests/unit/test_signal_router.py -v --cov=src/accounts/signal_router

# Check code quality
uv run ruff check src/accounts/signal_router.py

# Run all tests to verify no regressions
uv run pytest tests/ -v
```

### References

- [Source: docs/architecture.md#Signal-Router] - Signal Router architecture
- [Source: docs/architecture.md#Trading-Engine-Service] - Service structure
- [Source: docs/epics.md#Story-3.3] - Story requirements and acceptance criteria
- [Source: docs/sprint-artifacts/3-2-account-manager-multi-account-orchestration.md] - Previous story patterns
- [Source: docs/sprint-artifacts/2-9-signal-filtering-by-symbol.md] - Signal filtering foundation
- [Source: services/trading-engine/src/strategies/data_router.py] - Existing routing (do not duplicate)
- [Source: services/trading-engine/src/accounts/account_manager.py] - AccountManager integration
- [Source: services/trading-engine/src/accounts/models.py] - SignalFilter model
- [Source: Context7 redis-py 2025-12-30] - Async pub/sub patterns
- [Source: Context7 pyzmq 2025-12-30] - PUB/SUB topic filtering patterns

## Dev Agent Record

### Context Reference

Story created via create-story workflow with:
- Architecture analysis from docs/architecture.md
- Previous story 3.2 implementation analysis (multi-account orchestration)
- Previous story 2.9 implementation analysis (signal filtering by symbol)
- Existing codebase analysis from services/trading-engine/src/accounts/
- Context7 MCP research: redis-py async pub/sub patterns (2025-12-30)
- Context7 MCP research: pyzmq topic filtering patterns (2025-12-30)

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Initial story creation

### Completion Notes List

- Story context created with comprehensive developer guidance
- SignalRouter is NEW component - file does not exist yet
- Builds on existing AccountManager._accounts dict
- Does NOT duplicate data_router.py logic - higher-level routing
- O(1) hash map lookup for symbol → accounts mapping
- Wildcard accounts (empty filter) tracked separately
- Dynamic rebuild on account changes
- Comprehensive test suite specified

### Validation Notes (2025-12-30)

**Story validated via validate-create-story workflow. Applied improvements:**

| ID | Type | Description |
|----|------|-------------|
| C1 | Critical | Added `Bar` type import from `src.adapters.redis_models` to reference implementation |
| C2 | Critical | Updated `rebuild_mapping()` to use copy-on-write pattern for thread safety |
| E1 | Enhancement | Added integration flow diagram showing SignalRouter → StrategyDataRouter pipeline |
| E2 | Enhancement | Added explicit code example wiring SignalRouter into AccountManager's signal handler |
| E3 | Enhancement | Added async variants (`route_bar_async`, `route_tick_async`) with callback compatibility comments |
| O1 | Optimization | Added `get_accounts_for_symbol()` convenience method for debugging |
| O2 | Optimization | Added Logging Considerations section with TRACE-level logging guidance |

**Validation Score:** 24/28 (86%) → Improved to 28/28 (100%)

### File List

Files created:
- `services/trading-engine/src/accounts/signal_router.py` - SignalRouter class (NEW)
- `services/trading-engine/tests/unit/test_signal_router.py` - Unit tests (NEW)
- `services/trading-engine/tests/integration/test_signal_routing.py` - Integration tests (NEW)

Files modified:
- `services/trading-engine/src/accounts/__init__.py` - Export SignalRouter
- `services/trading-engine/src/accounts/account_manager.py` - Added SignalRouter integration

### Change Log

| Date | Change |
|------|--------|
| 2025-12-30 | Implemented SignalRouter with O(1) symbol-to-accounts routing |
| 2025-12-30 | Added 26 unit tests covering all acceptance criteria |
| 2025-12-30 | Updated __init__.py to export SignalRouter |
| 2025-12-30 | **Code Review Fixes:** Added SignalRouter integration to AccountManager (set_signal_router, get_signal_router methods) |
| 2025-12-30 | **Code Review Fixes:** Hooked SignalRouter.add_account() into AccountManager.add_account() for automatic updates |
| 2025-12-30 | **Code Review Fixes:** Created integration tests (tests/integration/test_signal_routing.py) - 8 tests |
| 2025-12-30 | **Code Review Fixes:** Added 9 additional unit tests (route_symbol, default filter, remove idempotency) |
| 2025-12-30 | **Code Review Fixes:** Added HasSymbol Protocol for tick type annotations |

### Implementation Notes (2025-12-30)

**Implementation Summary:**
- Created `SignalRouter` class with O(1) hash map lookup for symbol → accounts routing
- Wildcard accounts (empty symbol filter) tracked in separate `_wildcard_accounts` set
- Case-insensitive matching via `.upper()` normalization
- DEBUG logging when no accounts match incoming symbol
- Dynamic mapping updates via `add_account()`, `remove_account()`, and `rebuild_mapping()`
- Copy-on-write pattern in `rebuild_mapping()` for thread safety
- Async variants (`route_bar_async`, `route_tick_async`) for callback compatibility
- Convenience methods: `get_routing_stats()`, `get_accounts_for_symbol()`

**Test Results:**
- 26 unit tests - ALL PASSED
- 610 total unit tests - ALL PASSED (no regressions)
- Ruff linting - PASSED
- 9 Redis integration tests skipped (require Redis connection)

---

## Definition of Done

- [x] `signal_router.py` created with SignalRouter class
- [x] O(1) symbol→accounts lookup via hash map
- [x] Wildcard accounts (empty filter) receive all symbols
- [x] Case-insensitive symbol matching
- [x] DEBUG logging when no accounts match symbol
- [x] Dynamic mapping updates (add/remove account)
- [x] Unit tests cover all acceptance criteria
- [x] All existing tests still pass
- [x] Code passes: `uv run ruff check src/accounts/`
- [x] Story status updated to `done` after code review
