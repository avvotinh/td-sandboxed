"""Integration tests for signal filtering with real AccountConfig models.

These tests verify the full integration between:
- AccountConfig model with SignalFilter configuration
- BoundAccount wrapper with strategy_instance
- StrategyDataRouter routing logic
- Bar callback integration pattern

Story 2.9: Signal Filtering by Symbol
"""

import logging
import pytest
from unittest.mock import Mock

from src.accounts.models import AccountConfig, AccountType, MT5Config, SignalFilter
from src.strategies.account_binding import BoundAccount
from src.strategies.data_router import StrategyDataRouter


class TestSignalFilteringWithRealModels:
    """Integration tests using real AccountConfig models."""

    @pytest.fixture
    def mt5_config(self):
        """Create a valid MT5 configuration."""
        return MT5Config(
            server="demo.broker.com",
            login=12345678,
            password_env="MT5_PASSWORD"
        )

    @pytest.fixture
    def mock_bar(self):
        """Create a mock bar with symbol attribute."""
        bar = Mock()
        bar.symbol = "XAUUSD"
        return bar

    def test_account_config_with_symbol_filter_routes_matching_bar(self, mt5_config, mock_bar):
        """AC1: Given account configured with symbols: ["XAUUSD"], when bar for XAUUSD arrives, strategy processes it."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="test-account-1",
            name="Test Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD"]),
            status="active"
        )
        # Use BoundAccount wrapper (as done by account manager)
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        router = StrategyDataRouter([bound_account])
        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    def test_account_config_with_symbol_filter_ignores_non_matching_bar(self, mt5_config):
        """AC2: Given account configured with symbols: ["XAUUSD"], when bar for BTCUSD arrives, strategy ignores it."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="test-account-1",
            name="Test Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD"]),
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        mock_bar = Mock()
        mock_bar.symbol = "BTCUSD"

        router = StrategyDataRouter([bound_account])
        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_not_called()

    def test_account_config_with_multiple_symbols(self, mt5_config):
        """AC3: Given account allows multiple symbols, all matching bars are processed."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="multi-symbol-account",
            name="Multi Symbol Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD", "EURUSD", "GBPUSD"]),
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        router = StrategyDataRouter([bound_account])

        # Test all three allowed symbols
        for symbol in ["XAUUSD", "EURUSD", "GBPUSD"]:
            mock_bar = Mock()
            mock_bar.symbol = symbol
            router.route_bar(mock_bar)

        assert mock_strategy.on_bar.call_count == 3

    def test_filtered_signal_logs_debug(self, mt5_config, caplog):
        """AC4: Given signal for non-allowed symbol, DEBUG log is emitted."""
        caplog.set_level(logging.DEBUG)
        mock_strategy = Mock()

        account = AccountConfig(
            id="filtered-account",
            name="Filtered Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD"]),
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        mock_bar = Mock()
        mock_bar.symbol = "USDJPY"  # Not in filter

        router = StrategyDataRouter([bound_account])
        router.route_bar(mock_bar)

        # Verify DEBUG log with account id and symbol info
        assert "Filtered" in caplog.text
        assert "USDJPY" in caplog.text
        assert "filtered-account" in caplog.text

    def test_case_insensitive_symbol_matching(self, mt5_config):
        """AC5: Symbol matching is case-insensitive."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="case-test-account",
            name="Case Test Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["xauusd"]),  # lowercase
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"  # uppercase

        router = StrategyDataRouter([bound_account])
        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    def test_empty_symbol_filter_allows_all(self, mt5_config):
        """AC6: Empty symbols filter allows all symbols."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="no-filter-account",
            name="No Filter Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=[]),  # Empty = allow all
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        router = StrategyDataRouter([bound_account])

        # Test multiple symbols - all should be processed
        for symbol in ["XAUUSD", "BTCUSD", "EURUSD", "USDJPY"]:
            mock_bar = Mock()
            mock_bar.symbol = symbol
            router.route_bar(mock_bar)

        assert mock_strategy.on_bar.call_count == 4

    def test_default_signal_filter_allows_all(self, mt5_config):
        """Default SignalFilter (no symbols specified) allows all symbols."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="default-filter-account",
            name="Default Filter Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            # Uses default SignalFilter which has empty symbols list
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        mock_bar = Mock()
        mock_bar.symbol = "ANYUSD"

        router = StrategyDataRouter([bound_account])
        router.route_bar(mock_bar)

        mock_strategy.on_bar.assert_called_once_with(mock_bar)


class TestRedisAdapterBarCallbackPattern:
    """Integration tests demonstrating RedisAdapter callback pattern.

    These tests document how the bar callback integration works:
    1. RedisAdapter.set_bar_callback() receives router.route_bar
    2. When bars are received via Redis, the callback is invoked
    3. StrategyDataRouter filters and routes to appropriate strategies
    """

    @pytest.fixture
    def mt5_config(self):
        """Create a valid MT5 configuration."""
        return MT5Config(
            server="demo.broker.com",
            login=12345678,
            password_env="MT5_PASSWORD"
        )

    def test_bar_callback_integration_pattern(self, mt5_config):
        """Demonstrate the bar callback integration pattern with RedisAdapter."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="callback-test-account",
            name="Callback Test Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD"]),
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        router = StrategyDataRouter([bound_account])

        # Get the callback (this is what would be passed to RedisAdapter)
        bar_callback = router.get_bar_callback()

        # Simulate RedisAdapter invoking the callback when a bar is received
        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"
        bar_callback(mock_bar)

        # Verify strategy received the bar
        mock_strategy.on_bar.assert_called_once_with(mock_bar)

    @pytest.mark.asyncio
    async def test_async_bar_callback_integration_pattern(self, mt5_config):
        """Demonstrate async bar callback integration pattern."""
        mock_strategy = Mock()

        account = AccountConfig(
            id="async-callback-account",
            name="Async Callback Account",
            type=AccountType.DEMO,
            mt5=mt5_config,
            strategy="ma_crossover",
            signal_filter=SignalFilter(symbols=["XAUUSD"]),
            status="active"
        )
        bound_account = BoundAccount(config=account, strategy_instance=mock_strategy)

        router = StrategyDataRouter([bound_account])

        # Get the async callback
        bar_callback_async = router.get_bar_callback_async()

        # Simulate async invocation
        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"
        await bar_callback_async(mock_bar)

        # Verify strategy received the bar
        mock_strategy.on_bar.assert_called_once_with(mock_bar)
