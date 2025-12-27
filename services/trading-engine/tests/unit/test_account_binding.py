"""Unit tests for account-strategy binding."""

import pytest
from decimal import Decimal
from unittest.mock import Mock

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType

from src.strategies.account_binding import (
    BoundAccount,
    bind_strategy_to_account,
    bind_strategies_to_accounts,
)
from src.strategies.base_strategy import BaseStrategy
from src.strategies.config import BaseStrategyConfig
from src.strategies.registry import StrategyRegistry
from src.orders.signal import SignalType


class MockStrategy(BaseStrategy):
    """Mock strategy for binding tests."""

    def generate_signal(self, bar) -> SignalType:
        return SignalType.NONE


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the registry before and after each test."""
    StrategyRegistry.clear()
    yield
    StrategyRegistry.clear()


@pytest.fixture
def mock_account_config():
    """Create a mock AccountConfig."""
    mock = Mock()
    mock.id = "ftmo-main"
    mock.name = "FTMO Main Account"
    mock.strategy = "test_strategy"
    mock.status = "active"
    mock.signal_filter = Mock()
    mock.signal_filter.symbols = ["XAUUSD", "EURUSD"]
    return mock


@pytest.fixture
def strategy_config():
    """Create a test strategy config."""
    return BaseStrategyConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        account_id="ftmo-main",
    )


class TestBoundAccount:
    """Tests for BoundAccount dataclass."""

    def test_bound_account_properties(self, mock_account_config):
        """BoundAccount should expose config properties."""
        bound = BoundAccount(config=mock_account_config)

        assert bound.id == "ftmo-main"
        assert bound.name == "FTMO Main Account"
        assert bound.strategy == "test_strategy"
        assert bound.status == "active"
        assert bound.signal_filter.symbols == ["XAUUSD", "EURUSD"]

    def test_strategy_instance_default_none(self, mock_account_config):
        """strategy_instance should default to None."""
        bound = BoundAccount(config=mock_account_config)

        assert bound.strategy_instance is None

    def test_strategy_instance_can_be_set(self, mock_account_config, strategy_config):
        """strategy_instance can be set."""
        StrategyRegistry.register("test_strategy", MockStrategy)
        strategy = MockStrategy(strategy_config)

        bound = BoundAccount(
            config=mock_account_config,
            strategy_instance=strategy,
        )

        assert bound.strategy_instance is strategy
        assert isinstance(bound.strategy_instance, BaseStrategy)


class TestBindStrategyToAccount:
    """Tests for bind_strategy_to_account function."""

    def test_binds_registered_strategy(self, mock_account_config, strategy_config):
        """Should bind registered strategy to account."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        bound = bind_strategy_to_account(mock_account_config, strategy_config)

        assert isinstance(bound, BoundAccount)
        assert bound.strategy_instance is not None
        assert isinstance(bound.strategy_instance, MockStrategy)

    def test_raises_for_unregistered_strategy(self, mock_account_config, strategy_config):
        """Should raise ValueError for unregistered strategy."""
        # Don't register the strategy

        with pytest.raises(ValueError, match="not registered"):
            bind_strategy_to_account(mock_account_config, strategy_config)

    def test_preserves_account_config(self, mock_account_config, strategy_config):
        """Should preserve original account config."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        bound = bind_strategy_to_account(mock_account_config, strategy_config)

        assert bound.config is mock_account_config
        assert bound.id == mock_account_config.id

    def test_strategy_receives_config(self, mock_account_config, strategy_config):
        """Strategy should receive the provided config."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        bound = bind_strategy_to_account(mock_account_config, strategy_config)

        assert bound.strategy_instance.config.account_id == "ftmo-main"
        assert bound.strategy_instance.config.trade_size == Decimal("0.1")


class TestBindStrategiesToAccounts:
    """Tests for bind_strategies_to_accounts function."""

    def test_binds_multiple_accounts(self, strategy_config):
        """Should bind strategies to multiple accounts."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        account1 = Mock()
        account1.id = "account-1"
        account1.strategy = "test_strategy"
        account1.status = "active"
        account1.signal_filter = Mock()

        account2 = Mock()
        account2.id = "account-2"
        account2.strategy = "test_strategy"
        account2.status = "active"
        account2.signal_filter = Mock()

        config1 = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id="account-1",
        )
        config2 = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("EURUSD.BROKER"),
            bar_type=BarType.from_str("EURUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id="account-2",
        )

        configs = {"account-1": config1, "account-2": config2}
        bound_accounts = bind_strategies_to_accounts([account1, account2], configs)

        assert len(bound_accounts) == 2
        assert all(isinstance(b, BoundAccount) for b in bound_accounts)
        assert all(b.strategy_instance is not None for b in bound_accounts)

    def test_raises_for_missing_config(self, mock_account_config):
        """Should raise KeyError for missing strategy config."""
        StrategyRegistry.register("test_strategy", MockStrategy)

        with pytest.raises(KeyError, match="No strategy config provided"):
            bind_strategies_to_accounts([mock_account_config], {})

    def test_empty_accounts_returns_empty_list(self):
        """Should return empty list for empty accounts."""
        result = bind_strategies_to_accounts([], {})

        assert result == []


class TestBoundAccountWithDataRouter:
    """Integration tests for BoundAccount with StrategyDataRouter."""

    def test_bound_account_works_with_data_router(
        self, mock_account_config, strategy_config
    ):
        """BoundAccount should work with StrategyDataRouter."""
        from src.strategies.data_router import StrategyDataRouter

        StrategyRegistry.register("test_strategy", MockStrategy)
        bound = bind_strategy_to_account(mock_account_config, strategy_config)

        # Should not raise
        router = StrategyDataRouter([bound])

        # Verify the router can access the strategy
        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        # Mock the strategy's on_bar to verify it gets called
        bound.strategy_instance.on_bar = Mock()

        router.route_bar(mock_bar)

        bound.strategy_instance.on_bar.assert_called_once_with(mock_bar)

    def test_multiple_bound_accounts_with_router(self, strategy_config):
        """Multiple BoundAccounts should work with StrategyDataRouter."""
        from src.strategies.data_router import StrategyDataRouter

        StrategyRegistry.register("test_strategy", MockStrategy)

        # Create two accounts
        account1 = Mock()
        account1.id = "acc-1"
        account1.strategy = "test_strategy"
        account1.status = "active"
        account1.signal_filter = Mock()
        account1.signal_filter.symbols = ["XAUUSD"]

        account2 = Mock()
        account2.id = "acc-2"
        account2.strategy = "test_strategy"
        account2.status = "active"
        account2.signal_filter = Mock()
        account2.signal_filter.symbols = ["XAUUSD"]

        config1 = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id="acc-1",
        )
        config2 = BaseStrategyConfig(
            instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
            bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
            account_id="acc-2",
        )

        bound1 = bind_strategy_to_account(account1, config1)
        bound2 = bind_strategy_to_account(account2, config2)

        router = StrategyDataRouter([bound1, bound2])

        # Mock on_bar
        bound1.strategy_instance.on_bar = Mock()
        bound2.strategy_instance.on_bar = Mock()

        mock_bar = Mock()
        mock_bar.symbol = "XAUUSD"

        router.route_bar(mock_bar)

        # Both should receive the bar
        bound1.strategy_instance.on_bar.assert_called_once_with(mock_bar)
        bound2.strategy_instance.on_bar.assert_called_once_with(mock_bar)
