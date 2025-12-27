"""Unit tests for StrategyDataRouter."""

import pytest
from unittest.mock import Mock, MagicMock
from decimal import Decimal

from src.strategies.data_router import StrategyDataRouter


class TestStrategyDataRouterBarRouting:
    """Tests for bar data routing."""

    def test_routes_bar_to_active_account(self):
        """Should route bar to active account with matching symbol."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test_strategy"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    def test_skips_inactive_account(self):
        """Should not route bar to inactive account."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "paused"
        mock_account.strategy_instance = mock_strategy

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_not_called()

    def test_skips_unallowed_symbol(self):
        """Should not route bar if symbol not in filter."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["EURUSD"]

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_not_called()

    def test_routes_when_no_symbol_filter(self):
        """Should route bar when symbol filter is empty."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = []  # Empty = allow all

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    def test_routes_to_multiple_accounts(self):
        """Should route bar to multiple matching accounts."""
        strategy1 = Mock()
        account1 = Mock()
        account1.status = "active"
        account1.strategy = "strat1"
        account1.strategy_instance = strategy1
        account1.signal_filter.symbols = ["XAUUSD"]

        strategy2 = Mock()
        account2 = Mock()
        account2.status = "active"
        account2.strategy = "strat2"
        account2.strategy_instance = strategy2
        account2.signal_filter.symbols = ["XAUUSD", "EURUSD"]

        router = StrategyDataRouter([account1, account2])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        strategy1.on_bar.assert_called_once_with(mock_bar)
        strategy2.on_bar.assert_called_once_with(mock_bar)

    def test_handles_strategy_error_gracefully(self):
        """Should continue routing even if strategy raises error."""
        strategy1 = Mock()
        strategy1.on_bar.side_effect = Exception("Strategy error")
        account1 = Mock()
        account1.status = "active"
        account1.strategy = "strat1"
        account1.strategy_instance = strategy1
        account1.signal_filter.symbols = ["XAUUSD"]

        strategy2 = Mock()
        account2 = Mock()
        account2.status = "active"
        account2.strategy = "strat2"
        account2.strategy_instance = strategy2
        account2.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([account1, account2])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        # Should not raise despite strategy1 error
        router.route_bar(mock_bar)

        # strategy2 should still receive the bar
        strategy2.on_bar.assert_called_once_with(mock_bar)

    def test_symbol_matching_case_insensitive(self):
        """Symbol matching should be case-insensitive."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["xauusd"]  # lowercase

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"  # uppercase

        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    def test_skips_account_without_strategy_instance(self):
        """Should skip account without strategy_instance."""
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy_instance = None
        mock_account.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        # Should not raise
        router.route_bar(mock_bar)


class TestStrategyDataRouterTickRouting:
    """Tests for tick data routing."""

    def test_routes_tick_to_active_account(self):
        """Should route tick to active account with matching symbol."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([mock_account])

        mock_tick = Mock()
        mock_tick.symbol = "XAUUSD"

        router.route_tick(mock_tick)

        mock_strategy.on_tick.assert_called_once_with(mock_tick)

    def test_skips_tick_without_symbol(self):
        """Should skip tick without symbol attribute."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy_instance = mock_strategy

        router = StrategyDataRouter([mock_account])

        mock_tick = Mock(spec=[])  # No symbol attribute

        router.route_tick(mock_tick)

        mock_strategy.on_tick.assert_not_called()


class TestStrategyDataRouterCallbacks:
    """Tests for callback getters."""

    def test_get_bar_callback_returns_callable(self):
        """get_bar_callback should return callable."""
        router = StrategyDataRouter([])

        callback = router.get_bar_callback()

        assert callable(callback)
        assert callback == router.route_bar

    def test_get_tick_callback_returns_callable(self):
        """get_tick_callback should return callable."""
        router = StrategyDataRouter([])

        callback = router.get_tick_callback()

        assert callable(callback)
        assert callback == router.route_tick


class TestStrategyDataRouterAsync:
    """Tests for async routing methods."""

    @pytest.mark.asyncio
    async def test_route_bar_async(self):
        """Should route bar via async method."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([mock_account])

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        await router.route_bar_async(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    @pytest.mark.asyncio
    async def test_route_tick_async(self):
        """Should route tick via async method."""
        mock_strategy = Mock()
        mock_account = Mock()
        mock_account.status = "active"
        mock_account.strategy = "test"
        mock_account.strategy_instance = mock_strategy
        mock_account.signal_filter.symbols = ["XAUUSD"]

        router = StrategyDataRouter([mock_account])

        mock_tick = Mock()
        mock_tick.symbol = "XAUUSD"

        await router.route_tick_async(mock_tick)

        mock_strategy.on_tick.assert_called_once_with(mock_tick)
