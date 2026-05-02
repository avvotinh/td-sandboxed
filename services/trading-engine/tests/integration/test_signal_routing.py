"""Integration tests for SignalRouter with AccountManager.

Tests the integration between SignalRouter and AccountManager,
verifying that signal routing updates automatically when accounts change.
"""

import pytest
from unittest.mock import AsyncMock, Mock

from src.accounts.account_manager import AccountManager
from src.accounts.signal_router import SignalRouter
from src.accounts.models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)


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


@pytest.fixture
def mock_redis_manager():
    """Create mock Redis manager for AccountManager."""
    redis = AsyncMock()
    redis.save_account_status = AsyncMock()
    redis.get_account_status = AsyncMock(return_value="active")
    redis.update_account_health = AsyncMock()
    redis.clear_account_health = AsyncMock()
    redis.publish_alert = AsyncMock()
    redis.close = AsyncMock()
    return redis


class TestSignalRouterAccountManagerIntegration:
    """Integration tests for SignalRouter + AccountManager."""

    def test_signal_router_registers_with_account_manager(self, mock_redis_manager):
        """SignalRouter can be registered with AccountManager."""
        manager = AccountManager(mock_redis_manager)
        config = AccountsConfig(accounts=[create_test_account("acc-a", ["XAUUSD"])])
        manager.load_accounts(config)

        router = SignalRouter(manager)
        manager.set_signal_router(router)

        assert manager.get_signal_router() is router

    def test_get_signal_router_returns_none_when_not_set(self, mock_redis_manager):
        """get_signal_router() returns None when no router registered."""
        manager = AccountManager(mock_redis_manager)

        assert manager.get_signal_router() is None

    @pytest.mark.asyncio
    async def test_add_account_updates_signal_router(self, mock_redis_manager):
        """Adding account via AccountManager updates SignalRouter mapping."""
        manager = AccountManager(mock_redis_manager)
        initial_config = AccountsConfig(
            accounts=[create_test_account("acc-a", ["XAUUSD"])]
        )
        manager.load_accounts(initial_config)

        router = SignalRouter(manager)
        manager.set_signal_router(router)

        # Initially only acc-a routes XAUUSD
        bar = Mock(symbol="XAUUSD")
        assert router.route_bar(bar) == ["acc-a"]

        # BTCUSD has no routes
        bar_btc = Mock(symbol="BTCUSD")
        assert router.route_bar(bar_btc) == []

        # Add new account via AccountManager
        new_config = AccountsConfig(
            accounts=[
                create_test_account("acc-a", ["XAUUSD"]),
                create_test_account("acc-b", ["BTCUSD"]),
            ]
        )
        await manager.add_account("acc-b", new_config)

        # Now BTCUSD routes to acc-b automatically
        assert router.route_bar(bar_btc) == ["acc-b"]

    @pytest.mark.asyncio
    async def test_add_account_without_router_works(self, mock_redis_manager):
        """Adding account works even without SignalRouter registered."""
        manager = AccountManager(mock_redis_manager)
        initial_config = AccountsConfig(
            accounts=[create_test_account("acc-a", ["XAUUSD"])]
        )
        manager.load_accounts(initial_config)

        # No router set - add_account should still work
        new_config = AccountsConfig(
            accounts=[
                create_test_account("acc-a", ["XAUUSD"]),
                create_test_account("acc-b", ["BTCUSD"]),
            ]
        )
        await manager.add_account("acc-b", new_config)

        assert "acc-b" in manager._accounts

    @pytest.mark.asyncio
    async def test_signal_router_routes_after_account_manager_loads(
        self, mock_redis_manager
    ):
        """SignalRouter works correctly when created after AccountManager loads."""
        manager = AccountManager(mock_redis_manager)
        config = AccountsConfig(
            accounts=[
                create_test_account("gold", ["XAUUSD"]),
                create_test_account("forex", ["EURUSD", "GBPUSD"]),
                create_test_account("crypto", ["BTCUSD"]),
            ]
        )
        manager.load_accounts(config)

        # Create router after accounts loaded
        router = SignalRouter(manager)
        manager.set_signal_router(router)

        # Verify routing
        assert router.route_bar(Mock(symbol="XAUUSD")) == ["gold"]
        assert router.route_bar(Mock(symbol="EURUSD")) == ["forex"]
        assert router.route_bar(Mock(symbol="BTCUSD")) == ["crypto"]

    @pytest.mark.asyncio
    async def test_signal_router_with_wildcard_and_specific_accounts(
        self, mock_redis_manager
    ):
        """SignalRouter handles mix of wildcard and specific accounts."""
        manager = AccountManager(mock_redis_manager)
        config = AccountsConfig(
            accounts=[
                create_test_account("gold-only", ["XAUUSD"]),
                create_test_account("all-symbols", []),  # Wildcard
            ]
        )
        manager.load_accounts(config)

        router = SignalRouter(manager)
        manager.set_signal_router(router)

        # XAUUSD should go to both
        result = router.route_bar(Mock(symbol="XAUUSD"))
        assert set(result) == {"gold-only", "all-symbols"}

        # EURUSD should only go to wildcard
        result = router.route_bar(Mock(symbol="EURUSD"))
        assert result == ["all-symbols"]

    @pytest.mark.asyncio
    async def test_add_wildcard_account_updates_router(self, mock_redis_manager):
        """Adding wildcard account via AccountManager updates router."""
        manager = AccountManager(mock_redis_manager)
        initial_config = AccountsConfig(
            accounts=[create_test_account("acc-a", ["XAUUSD"])]
        )
        manager.load_accounts(initial_config)

        router = SignalRouter(manager)
        manager.set_signal_router(router)

        # EURUSD has no routes initially
        assert router.route_bar(Mock(symbol="EURUSD")) == []

        # Add wildcard account
        new_config = AccountsConfig(
            accounts=[
                create_test_account("acc-a", ["XAUUSD"]),
                create_test_account("catch-all", []),
            ]
        )
        await manager.add_account("catch-all", new_config)

        # Now EURUSD routes to wildcard
        assert router.route_bar(Mock(symbol="EURUSD")) == ["catch-all"]


class TestSignalRouterAccountManagerRebuild:
    """Tests for rebuild_mapping integration."""

    def test_rebuild_after_external_account_change(self, mock_redis_manager):
        """rebuild_mapping() picks up external account changes."""
        manager = AccountManager(mock_redis_manager)
        config = AccountsConfig(accounts=[create_test_account("acc-a", ["XAUUSD"])])
        manager.load_accounts(config)

        router = SignalRouter(manager)

        # Manually modify accounts dict (simulating external change)
        manager._accounts["acc-b"] = create_test_account("acc-b", ["BTCUSD"])

        # Before rebuild - acc-b not in routing
        assert router.route_bar(Mock(symbol="BTCUSD")) == []

        # Rebuild picks up change
        router.rebuild_mapping()
        assert router.route_bar(Mock(symbol="BTCUSD")) == ["acc-b"]
