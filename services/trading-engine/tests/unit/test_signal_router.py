"""Unit tests for SignalRouter - Multi-account signal routing.

Tests O(1) symbol-to-accounts routing based on SignalFilter configuration.
"""

import logging
import time

import pytest
from unittest.mock import Mock

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
    status: str = "active",
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

    def test_incoming_symbol_lowercase_matches_uppercase_filter(
        self, mock_account_manager
    ):
        """Incoming lowercase symbols match uppercase filters."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])  # UPPERCASE
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="xauusd")  # lowercase
        result = router.route_bar(bar)

        assert result == ["acc-a"]

    def test_mixed_case_symbols(self, mock_account_manager):
        """Mixed case symbols should all match."""
        account = create_test_account("acc-a", symbols=["XaUuSd"])  # mixed
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        for symbol in ["XAUUSD", "xauusd", "XauUsd", "xAuUsD"]:
            bar = Mock(symbol=symbol)
            result = router.route_bar(bar)
            assert result == ["acc-a"], f"Symbol {symbol} should match"


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

    def test_add_wildcard_account(self, mock_account_manager):
        """add_account() with empty filter adds to wildcards."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a}

        router = SignalRouter(mock_account_manager)

        # Add wildcard account
        acc_wild = create_test_account("acc-wild", symbols=[])
        router.add_account(acc_wild)

        # Wildcard should receive all symbols
        bar = Mock(symbol="EURUSD")
        result = router.route_bar(bar)
        assert "acc-wild" in result

    def test_remove_wildcard_account(self, mock_account_manager):
        """remove_account() removes from wildcard set."""
        acc_wild = create_test_account("acc-wild", symbols=[])
        mock_account_manager._accounts = {"acc-wild": acc_wild}

        router = SignalRouter(mock_account_manager)

        # Wildcard receives all
        bar = Mock(symbol="EURUSD")
        assert router.route_bar(bar) == ["acc-wild"]

        # Remove wildcard
        router.remove_account("acc-wild")
        assert router.route_bar(bar) == []


class TestSignalRouterInactiveAccounts:
    """Tests for handling inactive accounts."""

    def test_inactive_accounts_not_routed(self, mock_account_manager):
        """Inactive accounts should not receive signals."""
        acc_active = create_test_account(
            "acc-active", symbols=["XAUUSD"], status="active"
        )
        acc_paused = create_test_account(
            "acc-paused", symbols=["XAUUSD"], status="paused"
        )
        acc_stopped = create_test_account(
            "acc-stopped", symbols=["XAUUSD"], status="stopped"
        )
        mock_account_manager._accounts = {
            "acc-active": acc_active,
            "acc-paused": acc_paused,
            "acc-stopped": acc_stopped,
        }

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="XAUUSD")
        result = router.route_bar(bar)

        assert result == ["acc-active"]

    def test_add_inactive_account_not_added_to_routing(self, mock_account_manager):
        """add_account() with inactive status should not add to routing."""
        mock_account_manager._accounts = {}
        router = SignalRouter(mock_account_manager)

        # Add paused account
        acc_paused = create_test_account(
            "acc-paused", symbols=["XAUUSD"], status="paused"
        )
        router.add_account(acc_paused)

        bar = Mock(symbol="XAUUSD")
        result = router.route_bar(bar)

        assert result == []


class TestSignalRouterAsyncMethods:
    """Tests for async routing method variants."""

    @pytest.mark.asyncio
    async def test_route_bar_async(self, mock_account_manager):
        """route_bar_async() should return same result as route_bar()."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        bar = Mock(symbol="XAUUSD")

        sync_result = router.route_bar(bar)
        async_result = await router.route_bar_async(bar)

        assert sync_result == async_result

    @pytest.mark.asyncio
    async def test_route_tick_async(self, mock_account_manager):
        """route_tick_async() should return same result as route_tick()."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        tick = Mock(symbol="XAUUSD")

        sync_result = router.route_tick(tick)
        async_result = await router.route_tick_async(tick)

        assert sync_result == async_result


class TestSignalRouterPerformance:
    """Tests for O(1) routing performance."""

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
        bar = Mock(symbol="SYM2USD")

        start = time.perf_counter()
        for _ in range(1000):
            router.route_bar(bar)
        duration = time.perf_counter() - start

        # 1000 lookups should complete in < 10ms (O(1))
        assert duration < 0.01, f"Routing took {duration*1000:.2f}ms for 1000 lookups"

    def test_routing_with_many_symbols(self, mock_account_manager):
        """Routing should be O(1) even with many symbols."""
        # Create account with many symbols
        symbols = [f"SYM{i}USD" for i in range(100)]
        account = create_test_account("acc-a", symbols=symbols)
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        # Should find symbol quickly
        bar = Mock(symbol="SYM50USD")

        start = time.perf_counter()
        for _ in range(1000):
            router.route_bar(bar)
        duration = time.perf_counter() - start

        assert duration < 0.01, f"Routing took {duration*1000:.2f}ms for 1000 lookups"


class TestSignalRouterStats:
    """Tests for routing statistics and debugging methods."""

    def test_get_routing_stats(self, mock_account_manager):
        """get_routing_stats() should return correct statistics."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD", "EURUSD"])
        acc_b = create_test_account("acc-b", symbols=["BTCUSD"])
        acc_wild = create_test_account("acc-wild", symbols=[])
        mock_account_manager._accounts = {
            "acc-a": acc_a,
            "acc-b": acc_b,
            "acc-wild": acc_wild,
        }

        router = SignalRouter(mock_account_manager)

        stats = router.get_routing_stats()

        assert stats["symbol_count"] == 3  # XAUUSD, EURUSD, BTCUSD
        assert stats["wildcard_account_count"] == 1
        assert set(stats["symbols"]) == {"XAUUSD", "EURUSD", "BTCUSD"}
        assert stats["wildcard_accounts"] == ["acc-wild"]

    def test_get_accounts_for_symbol(self, mock_account_manager):
        """get_accounts_for_symbol() should return routing details."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        acc_wild = create_test_account("acc-wild", symbols=[])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-wild": acc_wild}

        router = SignalRouter(mock_account_manager)

        details = router.get_accounts_for_symbol("XAUUSD")

        assert details["symbol"] == "XAUUSD"
        assert details["specific_accounts"] == ["acc-a"]
        assert details["wildcard_accounts"] == ["acc-wild"]
        assert set(details["total_accounts"]) == {"acc-a", "acc-wild"}

    def test_get_accounts_for_symbol_case_insensitive(self, mock_account_manager):
        """get_accounts_for_symbol() should normalize symbol to uppercase."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        details = router.get_accounts_for_symbol("xauusd")

        assert details["symbol"] == "XAUUSD"  # Normalized to uppercase


class TestSignalRouterRouteTick:
    """Tests for tick routing methods."""

    def test_route_tick(self, mock_account_manager):
        """route_tick() should route based on tick symbol."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        tick = Mock(symbol="XAUUSD")
        result = router.route_tick(tick)

        assert result == ["acc-a"]


class TestSignalRouterMultipleSymbolsPerAccount:
    """Tests for accounts with multiple symbols in filter."""

    def test_account_with_multiple_symbols(self, mock_account_manager):
        """Account with multiple symbols should receive all of them."""
        account = create_test_account("acc-a", symbols=["XAUUSD", "EURUSD", "BTCUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        for symbol in ["XAUUSD", "EURUSD", "BTCUSD"]:
            bar = Mock(symbol=symbol)
            result = router.route_bar(bar)
            assert result == ["acc-a"], f"Account should receive {symbol}"

        # Should NOT receive unlisted symbol
        bar = Mock(symbol="USDJPY")
        result = router.route_bar(bar)
        assert result == []

    def test_overlapping_symbols_between_accounts(self, mock_account_manager):
        """Multiple accounts can share some symbols but not others."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD", "EURUSD"])
        acc_b = create_test_account("acc-b", symbols=["EURUSD", "BTCUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-b": acc_b}

        router = SignalRouter(mock_account_manager)

        # XAUUSD -> only acc-a
        bar = Mock(symbol="XAUUSD")
        assert router.route_bar(bar) == ["acc-a"]

        # EURUSD -> both
        bar = Mock(symbol="EURUSD")
        assert set(router.route_bar(bar)) == {"acc-a", "acc-b"}

        # BTCUSD -> only acc-b
        bar = Mock(symbol="BTCUSD")
        assert router.route_bar(bar) == ["acc-b"]


class TestSignalRouterRouteSymbol:
    """Tests for route_symbol() method directly."""

    def test_route_symbol_basic(self, mock_account_manager):
        """route_symbol() returns account IDs for matching symbol."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        result = router.route_symbol("XAUUSD")
        assert result == ["acc-a"]

    def test_route_symbol_case_insensitive(self, mock_account_manager):
        """route_symbol() handles case-insensitive matching."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        # All case variants should work
        for symbol in ["xauusd", "XAUUSD", "XauUsd"]:
            result = router.route_symbol(symbol)
            assert result == ["acc-a"], f"Symbol {symbol} should match"

    def test_route_symbol_no_match(self, mock_account_manager, caplog):
        """route_symbol() returns empty list and logs when no match."""
        caplog.set_level(logging.DEBUG)

        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        result = router.route_symbol("USDJPY")
        assert result == []
        assert "No accounts for symbol USDJPY" in caplog.text


class TestSignalRouterDefaultSignalFilter:
    """Tests for accounts with default signal_filter (empty symbols list)."""

    def test_default_filter_receives_all_symbols(self, mock_account_manager):
        """Account with default SignalFilter (empty symbols) receives all symbols."""
        # AccountConfig's signal_filter has default_factory=SignalFilter
        # which creates SignalFilter with empty symbols list (wildcard behavior)
        account = create_test_account("acc-default", symbols=[])
        mock_account_manager._accounts = {"acc-default": account}

        router = SignalRouter(mock_account_manager)

        # Should receive any symbol (empty symbols list = wildcard)
        for symbol in ["XAUUSD", "EURUSD", "BTCUSD", "USDJPY"]:
            result = router.route_symbol(symbol)
            assert "acc-default" in result, f"Account should receive {symbol}"

    def test_default_filter_combined_with_specific(self, mock_account_manager):
        """Default filter account receives symbols alongside specific accounts."""
        acc_default = create_test_account("acc-default", symbols=[])  # Wildcard
        acc_gold = create_test_account("acc-gold", symbols=["XAUUSD"])
        mock_account_manager._accounts = {
            "acc-default": acc_default,
            "acc-gold": acc_gold,
        }

        router = SignalRouter(mock_account_manager)

        # XAUUSD should go to both
        result = router.route_symbol("XAUUSD")
        assert set(result) == {"acc-default", "acc-gold"}


class TestSignalRouterRemoveAccountIdempotency:
    """Tests for remove_account() idempotency."""

    def test_remove_nonexistent_account(self, mock_account_manager):
        """remove_account() is safe for non-existent account IDs."""
        account = create_test_account("acc-a", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": account}

        router = SignalRouter(mock_account_manager)

        # Remove non-existent account - should not raise
        router.remove_account("does-not-exist")

        # Original routing should be unaffected
        result = router.route_symbol("XAUUSD")
        assert result == ["acc-a"]

    def test_remove_account_twice(self, mock_account_manager):
        """remove_account() can be called multiple times safely."""
        acc_a = create_test_account("acc-a", symbols=["XAUUSD"])
        acc_b = create_test_account("acc-b", symbols=["XAUUSD"])
        mock_account_manager._accounts = {"acc-a": acc_a, "acc-b": acc_b}

        router = SignalRouter(mock_account_manager)

        # Remove acc-b
        router.remove_account("acc-b")
        assert router.route_symbol("XAUUSD") == ["acc-a"]

        # Remove acc-b again - should not raise
        router.remove_account("acc-b")
        assert router.route_symbol("XAUUSD") == ["acc-a"]

    def test_remove_wildcard_account_twice(self, mock_account_manager):
        """remove_account() is idempotent for wildcard accounts."""
        acc_wild = create_test_account("acc-wild", symbols=[])
        mock_account_manager._accounts = {"acc-wild": acc_wild}

        router = SignalRouter(mock_account_manager)

        # Remove wildcard
        router.remove_account("acc-wild")
        assert router.route_symbol("XAUUSD") == []

        # Remove again - should not raise
        router.remove_account("acc-wild")
        assert router.route_symbol("XAUUSD") == []
