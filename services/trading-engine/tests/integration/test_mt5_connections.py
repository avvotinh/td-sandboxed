"""Integration tests for multi-account MT5 connections.

Tests verify end-to-end behavior of per-account MT5 connection management:
- AC1: Each account maintains separate ZeroMQ connection
- AC2: Orders routed to correct MT5 instance based on account_id
- AC3: Disconnection isolated to single account
- AC4: Reconnection with no duplicate orders
- AC5: Connection health tracked per account

Note: These tests use mocked ZMQ adapters to avoid requiring real mt5-bridge instances.
For full integration testing with real MT5 bridges, use the manual testing procedures
documented in the story file.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config, SignalFilter
from src.adapters.mt5_connection_manager import ConnectionHealth, MT5ConnectionManager
from src.adapters.zmq_adapter import ZmqAdapter


def create_test_account(
    account_id: str,
    tick_port: int = 5556,
    order_port: int = 5557,
    status: str = "active",
    zmq_host: str = "localhost",
) -> AccountConfig:
    """Create test account with port config."""
    mt5 = MT5Config(
        server="test-server",
        login=12345,
        password_env="TEST_PASS",
        zmq_host=zmq_host,
        zmq_tick_port=tick_port,
        zmq_order_port=order_port,
    )

    return AccountConfig(
        id=account_id,
        name=f"Test {account_id}",
        type=AccountType.DEMO,
        mt5=mt5,
        strategy="ma_crossover",
        signal_filter=SignalFilter(symbols=["XAUUSD"]),
        status=status,
    )


@pytest.fixture
def mock_redis_manager():
    """Create mock Redis state manager."""
    manager = Mock()
    manager.save_account_status = AsyncMock()
    manager.get_account_status = AsyncMock(return_value=None)
    manager.update_account_health = AsyncMock()
    manager.clear_account_health = AsyncMock()
    manager.publish_alert = AsyncMock()
    manager.close = AsyncMock()
    return manager


@pytest.fixture
def account_manager_with_two_accounts(mock_redis_manager):
    """Create AccountManager with two test accounts on different ports."""
    manager = AccountManager(mock_redis_manager)

    acc_ftmo = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
    acc_5ers = create_test_account("5ers-001", tick_port=5566, order_port=5567)

    config = AccountsConfig(accounts=[acc_ftmo, acc_5ers])
    manager.load_accounts(config)

    return manager


@pytest.mark.integration
class TestMT5ConnectionsIntegration:
    """Integration tests for multi-account MT5 connections.

    Note: These tests use mocked ZMQ adapters since real mt5-bridge
    instances are not available in CI/CD environments.
    """

    @pytest.mark.asyncio
    async def test_two_accounts_independent_order_routing(
        self, account_manager_with_two_accounts
    ):
        """AC2: Orders routed to correct account's connection."""
        conn_manager = MT5ConnectionManager(account_manager_with_two_accounts)

        # Track which adapter received each order
        received_orders: dict[str, list[str]] = {"ftmo-001": [], "5ers-001": []}

        async def mock_send(order, timeout=5.0):
            account_id = order.account_id
            received_orders[account_id].append(order.order_id)
            return Mock(order_id=order.order_id, status="filled")

        # Set up mock adapters manually (simulating successful connection)
        mock_adapter_ftmo = Mock(spec=ZmqAdapter)
        mock_adapter_ftmo.send_order_and_wait = AsyncMock(side_effect=mock_send)
        mock_adapter_ftmo.disconnect = AsyncMock()

        mock_adapter_5ers = Mock(spec=ZmqAdapter)
        mock_adapter_5ers.send_order_and_wait = AsyncMock(side_effect=mock_send)
        mock_adapter_5ers.disconnect = AsyncMock()

        conn_manager._connections["ftmo-001"] = mock_adapter_ftmo
        conn_manager._connections["5ers-001"] = mock_adapter_5ers
        conn_manager._health["ftmo-001"] = ConnectionHealth(connected=True)
        conn_manager._health["5ers-001"] = ConnectionHealth(connected=True)
        conn_manager._pending_orders["ftmo-001"] = set()
        conn_manager._pending_orders["5ers-001"] = set()

        # Send orders to different accounts
        await conn_manager.send_order(Mock(account_id="ftmo-001", order_id="O1"))
        await conn_manager.send_order(Mock(account_id="5ers-001", order_id="O2"))
        await conn_manager.send_order(Mock(account_id="ftmo-001", order_id="O3"))

        assert received_orders["ftmo-001"] == ["O1", "O3"]
        assert received_orders["5ers-001"] == ["O2"]

    @pytest.mark.asyncio
    async def test_disconnect_isolation(self, account_manager_with_two_accounts):
        """AC3: One account disconnecting doesn't affect the other."""
        conn_manager = MT5ConnectionManager(account_manager_with_two_accounts)

        # Set up mock adapters manually
        mock_adapter_ftmo = Mock(spec=ZmqAdapter)
        mock_adapter_ftmo.disconnect = AsyncMock()

        mock_adapter_5ers = Mock(spec=ZmqAdapter)
        mock_adapter_5ers.disconnect = AsyncMock()

        conn_manager._connections["ftmo-001"] = mock_adapter_ftmo
        conn_manager._connections["5ers-001"] = mock_adapter_5ers
        conn_manager._health["ftmo-001"] = ConnectionHealth(connected=True)
        conn_manager._health["5ers-001"] = ConnectionHealth(connected=True)
        conn_manager._pending_orders["ftmo-001"] = set()
        conn_manager._pending_orders["5ers-001"] = set()

        # Simulate ftmo-001 disconnect
        await conn_manager.stop_connection("ftmo-001")

        # 5ers-001 should still be connected
        assert conn_manager.get_health("5ers-001").connected
        assert not conn_manager.get_health("ftmo-001").connected
        assert "5ers-001" in conn_manager._connections
        assert "ftmo-001" not in conn_manager._connections

    @pytest.mark.asyncio
    async def test_concurrent_orders_to_different_accounts(
        self, account_manager_with_two_accounts
    ):
        """AC2: Concurrent orders to different accounts are handled correctly."""
        conn_manager = MT5ConnectionManager(account_manager_with_two_accounts)

        # Track order timing
        order_times: dict[str, float] = {}

        async def mock_send(order, timeout=5.0):
            order_times[order.order_id] = asyncio.get_event_loop().time()
            await asyncio.sleep(0.01)  # Simulate network delay
            return Mock(order_id=order.order_id, status="filled")

        # Set up mock adapters
        mock_adapter_ftmo = Mock(spec=ZmqAdapter)
        mock_adapter_ftmo.send_order_and_wait = AsyncMock(side_effect=mock_send)

        mock_adapter_5ers = Mock(spec=ZmqAdapter)
        mock_adapter_5ers.send_order_and_wait = AsyncMock(side_effect=mock_send)

        conn_manager._connections["ftmo-001"] = mock_adapter_ftmo
        conn_manager._connections["5ers-001"] = mock_adapter_5ers
        conn_manager._pending_orders["ftmo-001"] = set()
        conn_manager._pending_orders["5ers-001"] = set()

        # Send concurrent orders
        await asyncio.gather(
            conn_manager.send_order(Mock(account_id="ftmo-001", order_id="O1")),
            conn_manager.send_order(Mock(account_id="5ers-001", order_id="O2")),
            conn_manager.send_order(Mock(account_id="ftmo-001", order_id="O3")),
            conn_manager.send_order(Mock(account_id="5ers-001", order_id="O4")),
        )

        # All orders should be processed
        assert len(order_times) == 4
        assert all(order_id in order_times for order_id in ["O1", "O2", "O3", "O4"])


@pytest.mark.integration
class TestAccountManagerMT5Integration:
    """Integration tests for AccountManager with MT5ConnectionManager."""

    @pytest.mark.asyncio
    async def test_account_manager_starts_mt5_connections(self, mock_redis_manager):
        """AccountManager starts MT5 connections when manager is registered."""
        acc = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        config = AccountsConfig(accounts=[acc])

        account_manager = AccountManager(mock_redis_manager)
        account_manager.load_accounts(config)

        mt5_manager = MT5ConnectionManager(account_manager)
        account_manager.set_mt5_connection_manager(mt5_manager)

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            await account_manager.start_all_accounts()

            # MT5 connection should be started
            assert "ftmo-001" in mt5_manager._connections
            assert mt5_manager.get_health("ftmo-001").connected

    @pytest.mark.asyncio
    async def test_get_connection_health_via_account_manager(self, mock_redis_manager):
        """Connection health accessible via AccountManager."""
        acc = create_test_account("ftmo-001")
        config = AccountsConfig(accounts=[acc])

        account_manager = AccountManager(mock_redis_manager)
        account_manager.load_accounts(config)

        mt5_manager = MT5ConnectionManager(account_manager)
        account_manager.set_mt5_connection_manager(mt5_manager)

        # Manually set health
        mt5_manager._health["ftmo-001"] = ConnectionHealth(connected=True)

        health = account_manager.get_connection_health("ftmo-001")
        assert health is not None
        assert health.connected

    @pytest.mark.asyncio
    async def test_stop_account_stops_mt5_connection(self, mock_redis_manager):
        """Stopping account also stops MT5 connection."""
        acc = create_test_account("ftmo-001")
        config = AccountsConfig(accounts=[acc])

        account_manager = AccountManager(mock_redis_manager)
        account_manager.load_accounts(config)

        mt5_manager = MT5ConnectionManager(account_manager)
        account_manager.set_mt5_connection_manager(mt5_manager)

        # Manually set up connection
        mock_adapter = Mock(spec=ZmqAdapter)
        mock_adapter.disconnect = AsyncMock()
        mt5_manager._connections["ftmo-001"] = mock_adapter
        mt5_manager._health["ftmo-001"] = ConnectionHealth(connected=True)

        # Stop account
        await account_manager.stop_account("ftmo-001")

        # MT5 connection should be stopped
        assert "ftmo-001" not in mt5_manager._connections

    @pytest.mark.asyncio
    async def test_shutdown_stops_all_mt5_connections(self, mock_redis_manager):
        """Shutdown stops all MT5 connections."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5566, order_port=5567)
        config = AccountsConfig(accounts=[acc_a, acc_b])

        account_manager = AccountManager(mock_redis_manager)
        account_manager.load_accounts(config)

        mt5_manager = MT5ConnectionManager(account_manager)
        account_manager.set_mt5_connection_manager(mt5_manager)

        # Manually set up connections
        mock_adapter_a = Mock(spec=ZmqAdapter)
        mock_adapter_a.disconnect = AsyncMock()
        mock_adapter_b = Mock(spec=ZmqAdapter)
        mock_adapter_b.disconnect = AsyncMock()

        mt5_manager._connections["ftmo-001"] = mock_adapter_a
        mt5_manager._connections["5ers-001"] = mock_adapter_b

        # Shutdown
        await account_manager.shutdown()

        # All MT5 connections should be stopped
        assert len(mt5_manager._connections) == 0


@pytest.mark.integration
class TestPortConflictIntegration:
    """Integration tests for port conflict detection."""

    @pytest.mark.asyncio
    async def test_port_conflict_prevents_startup(self, mock_redis_manager):
        """Port conflicts detected at startup prevent connections."""
        # Two accounts with same ports = conflict
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5556, order_port=5557)
        config = AccountsConfig(accounts=[acc_a, acc_b])

        account_manager = AccountManager(mock_redis_manager)
        account_manager.load_accounts(config)

        mt5_manager = MT5ConnectionManager(account_manager)
        account_manager.set_mt5_connection_manager(mt5_manager)

        with pytest.raises(ValueError, match="Port conflict"):
            await account_manager.start_all_accounts()
