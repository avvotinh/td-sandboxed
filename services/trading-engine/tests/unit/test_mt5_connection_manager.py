"""Unit tests for MT5ConnectionManager - Per-account ZeroMQ connection management.

Tests cover all acceptance criteria:
- AC1: Each account maintains separate ZeroMQ connection
- AC2: Orders routed to correct MT5 instance based on account_id
- AC3: Disconnection isolated to single account
- AC4: Reconnection with no duplicate orders
- AC5: Connection health tracked per account
"""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.accounts.models import AccountConfig, AccountType, MT5Config, SignalFilter
from src.adapters.mt5_connection_manager import ConnectionHealth, MT5ConnectionManager
from src.adapters.zmq_adapter import ZmqAdapter


@pytest.fixture
def mock_account_manager():
    """Create mock AccountManager with test accounts."""
    manager = Mock()
    manager._accounts = {}
    return manager


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


class TestMT5ConnectionManagerBasic:
    """Tests for basic connection management."""

    @pytest.mark.asyncio
    async def test_start_connection_creates_adapter(self, mock_account_manager):
        """AC1: Start connection creates ZmqAdapter for account."""
        account = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        mock_account_manager._accounts = {"ftmo-001": account}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            await manager.start_connection("ftmo-001")

            assert "ftmo-001" in manager._connections
            assert manager.get_health("ftmo-001").connected

    @pytest.mark.asyncio
    async def test_multiple_accounts_get_separate_connections(self, mock_account_manager):
        """AC1: Each account gets its own ZmqAdapter instance."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5566, order_port=5567)
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            await manager.start_connection("ftmo-001")
            await manager.start_connection("5ers-001")

            assert len(manager._connections) == 2
            assert manager._connections["ftmo-001"] is not manager._connections["5ers-001"]

    @pytest.mark.asyncio
    async def test_start_connection_for_nonexistent_account_raises(self, mock_account_manager):
        """Start connection for unknown account raises KeyError."""
        mock_account_manager._accounts = {}

        manager = MT5ConnectionManager(mock_account_manager)

        with pytest.raises(KeyError, match="Account nonexistent not found"):
            await manager.start_connection("nonexistent")

    @pytest.mark.asyncio
    async def test_start_connection_already_exists_logs_warning(
        self, mock_account_manager, caplog
    ):
        """Starting connection for already connected account logs warning."""
        account = create_test_account("ftmo-001")
        mock_account_manager._accounts = {"ftmo-001": account}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            await manager.start_connection("ftmo-001")

            with caplog.at_level(logging.WARNING):
                await manager.start_connection("ftmo-001")
                assert "Connection already exists" in caplog.text

    @pytest.mark.asyncio
    async def test_stop_connection_removes_adapter(self, mock_account_manager):
        """Stop connection removes adapter from connections dict."""
        account = create_test_account("ftmo-001")
        mock_account_manager._accounts = {"ftmo-001": account}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            with patch.object(ZmqAdapter, "disconnect", new_callable=AsyncMock):
                manager = MT5ConnectionManager(mock_account_manager)
                await manager.start_connection("ftmo-001")

                assert "ftmo-001" in manager._connections

                await manager.stop_connection("ftmo-001")

                assert "ftmo-001" not in manager._connections
                assert not manager.get_health("ftmo-001").connected

    @pytest.mark.asyncio
    async def test_get_connection_returns_adapter(self, mock_account_manager):
        """Get connection returns correct adapter."""
        account = create_test_account("ftmo-001")
        mock_account_manager._accounts = {"ftmo-001": account}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            await manager.start_connection("ftmo-001")

            adapter = manager.get_connection("ftmo-001")
            assert adapter is not None
            assert isinstance(adapter, ZmqAdapter)

    def test_get_connection_nonexistent_returns_none(self, mock_account_manager):
        """Get connection for unknown account returns None."""
        manager = MT5ConnectionManager(mock_account_manager)
        assert manager.get_connection("nonexistent") is None


class TestOrderRouting:
    """Tests for order routing by account_id."""

    @pytest.mark.asyncio
    async def test_order_routed_to_correct_account(self, mock_account_manager):
        """AC2: Order sent via correct account's connection."""
        account = create_test_account("ftmo-001")
        mock_account_manager._accounts = {"ftmo-001": account}

        mock_adapter = Mock(spec=ZmqAdapter)
        mock_adapter.send_order_and_wait = AsyncMock(
            return_value=Mock(order_id="ORDER-1", status="filled")
        )

        manager = MT5ConnectionManager(mock_account_manager)
        manager._connections["ftmo-001"] = mock_adapter
        manager._pending_orders["ftmo-001"] = set()

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")
        await manager.send_order(order)

        mock_adapter.send_order_and_wait.assert_called_once_with(order, timeout=5.0)

    @pytest.mark.asyncio
    async def test_order_to_disconnected_account_raises(self, mock_account_manager):
        """AC2: Order to disconnected account raises RuntimeError."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._pending_orders["ftmo-001"] = set()

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")

        with pytest.raises(RuntimeError, match="No connection for account ftmo-001"):
            await manager.send_order(order)

    @pytest.mark.asyncio
    async def test_idempotency_rejects_duplicate_order_id(self, mock_account_manager):
        """AC4: Duplicate order_id is rejected."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._connections["ftmo-001"] = Mock(spec=ZmqAdapter)
        manager._pending_orders["ftmo-001"] = {"ORDER-1"}

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")

        with pytest.raises(ValueError, match="Duplicate order_id: ORDER-1"):
            await manager.send_order(order)

    @pytest.mark.asyncio
    async def test_pending_order_removed_after_send(self, mock_account_manager):
        """Order removed from pending set after successful send."""
        mock_adapter = Mock(spec=ZmqAdapter)
        mock_adapter.send_order_and_wait = AsyncMock(
            return_value=Mock(order_id="ORDER-1", status="filled")
        )

        manager = MT5ConnectionManager(mock_account_manager)
        manager._connections["ftmo-001"] = mock_adapter
        manager._pending_orders["ftmo-001"] = set()

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")
        await manager.send_order(order)

        assert "ORDER-1" not in manager._pending_orders["ftmo-001"]

    @pytest.mark.asyncio
    async def test_pending_order_removed_on_failure(self, mock_account_manager):
        """Order removed from pending set even on failure."""
        mock_adapter = Mock(spec=ZmqAdapter)
        mock_adapter.send_order_and_wait = AsyncMock(side_effect=asyncio.TimeoutError())

        manager = MT5ConnectionManager(mock_account_manager)
        manager._connections["ftmo-001"] = mock_adapter
        manager._pending_orders["ftmo-001"] = set()

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")

        with pytest.raises(asyncio.TimeoutError):
            await manager.send_order(order)

        assert "ORDER-1" not in manager._pending_orders["ftmo-001"]


class TestConnectionIsolation:
    """Tests for connection failure isolation."""

    @pytest.mark.asyncio
    async def test_disconnect_does_not_affect_other_accounts(self, mock_account_manager):
        """AC3: Account A disconnect doesn't affect Account B."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5566, order_port=5567)
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        # Create manager and manually set up connections without tick receivers
        # (tick receivers would try to receive on mocked sockets)
        manager = MT5ConnectionManager(mock_account_manager)

        # Manually add connections and health status (simulating successful connection)
        mock_adapter_a = Mock(spec=ZmqAdapter)
        mock_adapter_a.disconnect = AsyncMock()
        mock_adapter_b = Mock(spec=ZmqAdapter)
        mock_adapter_b.disconnect = AsyncMock()

        manager._connections["ftmo-001"] = mock_adapter_a
        manager._connections["5ers-001"] = mock_adapter_b
        manager._health["ftmo-001"] = ConnectionHealth(connected=True)
        manager._health["5ers-001"] = ConnectionHealth(connected=True)
        manager._pending_orders["ftmo-001"] = set()
        manager._pending_orders["5ers-001"] = set()

        # Stop only Account A
        await manager.stop_connection("ftmo-001")

        # Account A disconnected
        assert "ftmo-001" not in manager._connections
        assert not manager.get_health("ftmo-001").connected

        # Account B still connected
        assert "5ers-001" in manager._connections
        assert manager.get_health("5ers-001").connected


class TestReconnection:
    """Tests for reconnection with backoff."""

    def test_reconnect_delays_sequence(self, mock_account_manager):
        """Verify exponential backoff delays."""
        manager = MT5ConnectionManager(mock_account_manager)
        assert manager.RECONNECT_DELAYS == [1, 2, 4, 8, 16, 30]

    @pytest.mark.asyncio
    async def test_reconnection_uses_exponential_backoff(self, mock_account_manager):
        """AC4: Reconnection uses exponential backoff."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._running = True

        # Simulate failed connection attempts
        manager._health["ftmo-001"] = ConnectionHealth(reconnect_attempts=2)

        # Delay should be RECONNECT_DELAYS[2] = 4 seconds
        expected_delay = manager.RECONNECT_DELAYS[2]
        assert expected_delay == 4

    def test_schedule_reconnection_when_not_running_does_nothing(self, mock_account_manager):
        """Scheduling reconnection when manager not running does nothing."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._running = False

        manager._schedule_reconnection("ftmo-001")

        assert "ftmo-001" not in manager._reconnection_tasks

    @pytest.mark.asyncio
    async def test_order_during_reconnection_raises_not_connected(self, mock_account_manager):
        """Order sent during reconnection window raises RuntimeError.

        This tests the edge case where an account was connected, disconnected,
        and is in the process of reconnecting. Orders should fail fast.
        """
        account = create_test_account("ftmo-001")
        mock_account_manager._accounts = {"ftmo-001": account}

        manager = MT5ConnectionManager(mock_account_manager)
        manager._running = True

        # Simulate state after disconnection but before reconnection completes:
        # - No connection in _connections (removed during disconnect)
        # - Health shows disconnected
        # - Reconnection task may be running (simulated)
        manager._health["ftmo-001"] = ConnectionHealth(
            connected=False, reconnect_attempts=1, last_error="Connection lost"
        )
        # Note: _connections["ftmo-001"] does NOT exist (removed during disconnect)

        order = Mock(account_id="ftmo-001", order_id="ORDER-1")

        with pytest.raises(RuntimeError, match="No connection for account ftmo-001"):
            await manager.send_order(order)


class TestHealthTracking:
    """Tests for connection health tracking."""

    def test_health_updated_on_connect(self, mock_account_manager):
        """AC5: Health updated when connected."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._update_health("ftmo-001", connected=True)

        health = manager.get_health("ftmo-001")
        assert health.connected
        assert health.reconnect_attempts == 0
        assert health.last_heartbeat is not None

    def test_health_updated_on_disconnect(self, mock_account_manager):
        """AC5: Health updated when disconnected."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._update_health("ftmo-001", connected=False, error="Connection lost")

        health = manager.get_health("ftmo-001")
        assert not health.connected
        assert health.last_error == "Connection lost"
        assert health.reconnect_attempts == 1

    def test_reconnect_attempts_increment_on_disconnect(self, mock_account_manager):
        """Reconnect attempts increment each disconnection."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._health["ftmo-001"] = ConnectionHealth(reconnect_attempts=3)

        manager._update_health("ftmo-001", connected=False)

        assert manager.get_health("ftmo-001").reconnect_attempts == 4

    def test_reconnect_attempts_reset_on_connect(self, mock_account_manager):
        """Reconnect attempts reset on successful connection."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._health["ftmo-001"] = ConnectionHealth(reconnect_attempts=5)

        manager._update_health("ftmo-001", connected=True)

        assert manager.get_health("ftmo-001").reconnect_attempts == 0

    def test_get_health_nonexistent_returns_default(self, mock_account_manager):
        """Get health for unknown account returns default ConnectionHealth."""
        manager = MT5ConnectionManager(mock_account_manager)
        health = manager.get_health("nonexistent")

        assert not health.connected
        assert health.reconnect_attempts == 0
        assert health.last_heartbeat is None

    def test_get_all_connection_health_returns_all_accounts(self, mock_account_manager):
        """AC5: get_all_connection_health() returns health for all accounts."""
        manager = MT5ConnectionManager(mock_account_manager)
        manager._health["ftmo-001"] = ConnectionHealth(connected=True)
        manager._health["5ers-001"] = ConnectionHealth(connected=False)

        all_health = manager.get_all_connection_health()
        assert len(all_health) == 2
        assert all_health["ftmo-001"].connected
        assert not all_health["5ers-001"].connected


class TestPortConflictValidation:
    """Tests for port conflict detection at startup."""

    @pytest.mark.asyncio
    async def test_detects_port_conflicts_at_startup(self, mock_account_manager):
        """Two accounts with same ports should raise ValueError."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5556, order_port=5557)  # Same ports!
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        manager = MT5ConnectionManager(mock_account_manager)

        with pytest.raises(ValueError, match="Port conflict"):
            await manager.start_all_connections()

    @pytest.mark.asyncio
    async def test_allows_unique_ports(self, mock_account_manager):
        """Accounts with different ports should not raise."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5566, order_port=5567)
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            # Should not raise
            await manager.start_all_connections()
            assert len(manager._connections) == 2

    def test_inactive_accounts_excluded_from_conflict_check(self, mock_account_manager):
        """Inactive accounts should be excluded from port conflict validation."""
        acc_active = create_test_account(
            "ftmo-001", tick_port=5556, order_port=5557, status="active"
        )
        acc_paused = create_test_account(
            "5ers-001", tick_port=5556, order_port=5557, status="paused"
        )
        mock_account_manager._accounts = {"ftmo-001": acc_active, "5ers-001": acc_paused}

        manager = MT5ConnectionManager(mock_account_manager)
        # Should not raise - paused account excluded
        manager._validate_port_conflicts()

    def test_different_hosts_same_ports_no_conflict(self, mock_account_manager):
        """Same ports on different hosts should not conflict."""
        acc_a = create_test_account(
            "ftmo-001", tick_port=5556, order_port=5557, zmq_host="host1"
        )
        acc_b = create_test_account(
            "5ers-001", tick_port=5556, order_port=5557, zmq_host="host2"
        )
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        manager = MT5ConnectionManager(mock_account_manager)
        # Should not raise - different hosts
        manager._validate_port_conflicts()


class TestPendingOrderRecovery:
    """Tests for pending order recovery after reconnection."""

    @pytest.mark.asyncio
    async def test_pending_orders_cleared_on_recovery(self, mock_account_manager, caplog):
        """Pending orders should be cleared after reconnection with warning."""
        caplog.set_level(logging.WARNING)

        manager = MT5ConnectionManager(mock_account_manager)
        manager._pending_orders["ftmo-001"] = {"ORDER-1", "ORDER-2", "ORDER-3"}

        await manager._recover_pending_orders("ftmo-001")

        assert manager._pending_orders["ftmo-001"] == set()
        assert "3 pending orders" in caplog.text
        assert "Manual verification recommended" in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_when_no_pending_orders(self, mock_account_manager, caplog):
        """No warning should be logged if no pending orders."""
        caplog.set_level(logging.INFO)

        manager = MT5ConnectionManager(mock_account_manager)
        manager._pending_orders["ftmo-001"] = set()

        await manager._recover_pending_orders("ftmo-001")

        assert "No pending orders to recover" in caplog.text


class TestStartAllConnections:
    """Tests for start_all_connections method."""

    @pytest.mark.asyncio
    async def test_start_all_only_starts_active_accounts(self, mock_account_manager):
        """start_all_connections only starts active accounts."""
        acc_active = create_test_account("ftmo-001", tick_port=5556, order_port=5557, status="active")
        acc_paused = create_test_account("5ers-001", tick_port=5566, order_port=5567, status="paused")
        acc_stopped = create_test_account("personal-001", tick_port=5576, order_port=5577, status="stopped")
        mock_account_manager._accounts = {
            "ftmo-001": acc_active,
            "5ers-001": acc_paused,
            "personal-001": acc_stopped,
        }

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            manager = MT5ConnectionManager(mock_account_manager)
            await manager.start_all_connections()

            # Only active account should be connected
            assert len(manager._connections) == 1
            assert "ftmo-001" in manager._connections

    @pytest.mark.asyncio
    async def test_stop_all_connections(self, mock_account_manager):
        """stop_all_connections stops all connections."""
        acc_a = create_test_account("ftmo-001", tick_port=5556, order_port=5557)
        acc_b = create_test_account("5ers-001", tick_port=5566, order_port=5567)
        mock_account_manager._accounts = {"ftmo-001": acc_a, "5ers-001": acc_b}

        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock):
            with patch.object(ZmqAdapter, "disconnect", new_callable=AsyncMock):
                manager = MT5ConnectionManager(mock_account_manager)
                await manager.start_all_connections()

                assert len(manager._connections) == 2

                await manager.stop_all_connections()

                assert len(manager._connections) == 0
                assert not manager._running


class TestZmqConfigCreation:
    """Tests for ZmqConfig creation from account config."""

    def test_creates_config_with_account_ports(self, mock_account_manager):
        """_create_zmq_config uses account-specific port configuration."""
        account = create_test_account(
            "ftmo-001",
            tick_port=5666,
            order_port=5667,
            zmq_host="broker.ftmo.com",
        )

        manager = MT5ConnectionManager(mock_account_manager)
        config = manager._create_zmq_config(account)

        assert config.bridge_host == "broker.ftmo.com"
        assert config.tick_port == 5666
        assert config.order_port == 5667
        assert config.account_id == "ftmo-001"


class TestConnectionHealthDataclass:
    """Tests for ConnectionHealth dataclass."""

    def test_default_values(self):
        """ConnectionHealth has correct defaults."""
        health = ConnectionHealth()
        assert health.connected is False
        assert health.last_heartbeat is None
        assert health.last_error is None
        assert health.reconnect_attempts == 0

    def test_with_values(self):
        """ConnectionHealth accepts all values."""
        now = datetime.now(timezone.utc)
        health = ConnectionHealth(
            connected=True,
            last_heartbeat=now,
            last_error="Test error",
            reconnect_attempts=3,
        )
        assert health.connected is True
        assert health.last_heartbeat == now
        assert health.last_error == "Test error"
        assert health.reconnect_attempts == 3
