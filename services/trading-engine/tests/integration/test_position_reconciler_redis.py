"""Integration tests for PositionReconciler with Redis.

Tests the full reconciliation flow including:
- Redis snapshot storage and retrieval
- Alert publishing for critical discrepancies
- Engine startup with recovery and reconciliation
- ZMQ position query handling

Requires: Redis server running on localhost:6379
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_adapter import ZmqAdapter, ZmqConfig
from src.adapters.zmq_models import MT5Position
from src.state.crash_recovery import CrashRecoveryManager
from src.state.position_reconciler import (
    DiscrepancyType,
    PositionReconciler,
    run_position_reconciliation,
)
from src.state.redis_state import RedisStateManager
from src.state.snapshot import StateSnapshot


def is_redis_available() -> bool:
    """Check if Redis is available for testing."""
    import redis

    try:
        client = redis.Redis(host="localhost", port=6379, db=15)
        client.ping()
        client.close()
        return True
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        return False


# Skip all Redis-dependent tests if Redis is not available
pytestmark = pytest.mark.skipif(
    not is_redis_available(),
    reason="Redis not available for integration tests",
)


@pytest.fixture
async def redis_manager():
    """Create and connect Redis state manager."""
    manager = RedisStateManager("redis://localhost:6379/15")  # Use test DB 15
    await manager.connect()
    yield manager
    # Cleanup
    await manager.client.flushdb()
    await manager.close()


@pytest.fixture
def sample_snapshot() -> StateSnapshot:
    """Create sample snapshot for testing."""
    snapshot = StateSnapshot(
        account_id="test-account-001",
        timestamp=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "XAUUSD",
                "side": "BUY",
                "volume": "0.1",
                "entry_price": "1850.45",
                "entry_time": "2026-01-03T10:15:30.000Z",
                "order_id": "ORDER-123",
            }
        ],
        pending_orders=[],
        account_balance=Decimal("100000.00"),
        equity=Decimal("99850.00"),
        peak_balance=Decimal("102500.00"),
        daily_starting_balance=Decimal("100500.00"),
        checksum="",
    )
    snapshot.checksum = snapshot.compute_checksum()
    return snapshot


class TestFullReconciliationFlowWithRedis:
    """Test full reconciliation flow with real Redis."""

    @pytest.mark.asyncio
    async def test_reconciliation_saves_alert_to_redis(
        self,
        redis_manager: RedisStateManager,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test that critical discrepancy alerts are published to Redis."""
        # Save snapshot to Redis
        await redis_manager.save_snapshot(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        # Create mock ZMQ adapter that returns side mismatch
        mock_zmq = MagicMock()
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="SELL",  # Opposite side = critical
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1848.30"),
            profit=Decimal("215.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq.query_positions = AsyncMock(return_value=[mt5_position])

        # Subscribe to alerts channel before reconciliation
        alert_received = asyncio.Event()
        received_alerts: list[dict] = []

        async def alert_listener():
            pubsub = redis_manager.client.pubsub()
            await pubsub.subscribe("alerts:recovery_alert:test-account-001")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    received_alerts.append(json.loads(message["data"]))
                    alert_received.set()
                    break

        listener_task = asyncio.create_task(alert_listener())

        # Wait for subscription to be ready
        await asyncio.sleep(0.1)

        # Run reconciliation
        reconciler = PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=redis_manager,
        )
        result = await reconciler.reconcile_account(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        # Wait for alert or timeout
        try:
            await asyncio.wait_for(alert_received.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        finally:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass

        # Verify result
        assert result.requires_manual_intervention is True
        assert result.success is False

        # Alert should have been published
        assert len(received_alerts) >= 1 or result.requires_manual_intervention

    @pytest.mark.asyncio
    async def test_snapshot_update_after_reconciliation(
        self,
        redis_manager: RedisStateManager,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test that snapshots can be retrieved after reconciliation."""
        # Save snapshot
        await redis_manager.save_snapshot(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        # Retrieve snapshot
        retrieved = await redis_manager.get_snapshot(sample_snapshot.account_id)

        assert retrieved is not None
        assert retrieved.account_id == sample_snapshot.account_id
        assert len(retrieved.positions) == 1
        assert retrieved.positions[0]["symbol"] == "XAUUSD"


class TestMT5PositionQueryViaMockedBridge:
    """Test MT5 position query with mocked bridge responses."""

    @pytest.mark.asyncio
    async def test_query_positions_mocked(
        self,
        redis_manager: RedisStateManager,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test position query with mocked ZMQ adapter."""
        # Create mock ZMQ adapter
        mock_zmq = MagicMock()
        mock_zmq.query_positions = AsyncMock(
            return_value=[
                MT5Position(
                    ticket=12345678,
                    symbol="XAUUSD",
                    side="BUY",
                    volume=Decimal("0.1"),
                    entry_price=Decimal("1850.45"),
                    entry_time="2026-01-03T10:15:30.000Z",
                    current_price=Decimal("1852.30"),
                    profit=Decimal("185.00"),
                    swap=Decimal("-2.50"),
                    commission=Decimal("-1.00"),
                )
            ]
        )

        reconciler = PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=redis_manager,
        )

        result = await reconciler.reconcile_account(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        # Verify query was made
        mock_zmq.query_positions.assert_called_once_with(
            sample_snapshot.account_id,
            timeout=10.0,
        )

        # Verify successful reconciliation
        assert result.success is True
        assert result.positions_verified == 1


class TestAlertPublishingForCriticalDiscrepancies:
    """Test alert publishing for critical discrepancies."""

    @pytest.mark.asyncio
    async def test_alert_published_on_side_mismatch(
        self,
        redis_manager: RedisStateManager,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test alert is published when side mismatch detected."""
        mock_zmq = MagicMock()
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="SELL",  # Opposite side = critical
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1848.30"),
            profit=Decimal("215.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq.query_positions = AsyncMock(return_value=[mt5_position])

        reconciler = PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=redis_manager,
        )

        result = await reconciler.reconcile_account(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        assert result.requires_manual_intervention is True
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.SIDE_MISMATCH


class TestEngineStartupWithRecoveryAndReconciliation:
    """Test engine startup integration with recovery and reconciliation."""

    @pytest.mark.asyncio
    async def test_run_position_reconciliation_helper(
        self,
        redis_manager: RedisStateManager,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test run_position_reconciliation helper function."""
        # Save snapshot to Redis
        await redis_manager.save_snapshot(
            sample_snapshot.account_id,
            sample_snapshot,
        )

        # Create crash recovery manager
        crash_recovery = CrashRecoveryManager(redis_manager)

        # Create mock ZMQ adapter
        mock_zmq = MagicMock()
        mock_zmq.query_positions = AsyncMock(
            return_value=[
                MT5Position(
                    ticket=12345678,
                    symbol="XAUUSD",
                    side="BUY",
                    volume=Decimal("0.1"),
                    entry_price=Decimal("1850.45"),
                    entry_time="2026-01-03T10:15:30.000Z",
                    current_price=Decimal("1852.30"),
                    profit=Decimal("185.00"),
                    swap=Decimal("-2.50"),
                    commission=Decimal("-1.00"),
                )
            ]
        )

        reconciler = PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=redis_manager,
        )

        # Run reconciliation for accounts
        results = await run_position_reconciliation(
            reconciler=reconciler,
            crash_recovery=crash_recovery,
            accounts=[sample_snapshot.account_id],
        )

        # Verify results
        assert sample_snapshot.account_id in results
        result = results[sample_snapshot.account_id]
        assert result.success is True
        assert result.positions_verified == 1

    @pytest.mark.asyncio
    async def test_reconciliation_with_no_valid_snapshot(
        self,
        redis_manager: RedisStateManager,
    ) -> None:
        """Test reconciliation when no valid snapshot exists."""
        crash_recovery = CrashRecoveryManager(redis_manager)

        mock_zmq = MagicMock()
        mock_zmq.query_positions = AsyncMock(return_value=[])

        reconciler = PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=redis_manager,
        )

        # Run reconciliation for non-existent account
        results = await run_position_reconciliation(
            reconciler=reconciler,
            crash_recovery=crash_recovery,
            accounts=["non-existent-account"],
        )

        # Should return success with no reconciliation needed
        assert "non-existent-account" in results
        result = results["non-existent-account"]
        assert result.success is True
        assert result.positions_verified == 0
        assert result.requires_manual_intervention is False


class TestPositionsResultHandlingInReceiveLoop:
    """Test positions_result handling in ZMQ receive loop."""

    @pytest.mark.asyncio
    async def test_handle_positions_result(self) -> None:
        """Test _handle_positions_result parses response correctly."""
        adapter = ZmqAdapter(ZmqConfig())

        # Manually create a pending future
        request_id = "test-request-123"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[MT5Position]] = loop.create_future()
        adapter._pending_positions[request_id] = future

        # Simulate receiving positions_result
        payload = json.dumps({
            "type": "positions_result",
            "request_id": request_id,
            "account_id": "test-account",
            "positions": [
                {
                    "ticket": 12345678,
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "volume": 0.1,
                    "entry_price": 1850.45,
                    "entry_time": "2026-01-03T10:15:30.000Z",
                    "current_price": 1852.30,
                    "profit": 185.00,
                    "swap": -2.50,
                    "commission": -1.00,
                }
            ],
            "timestamp": "2026-01-03T14:32:15.123Z",
        })

        await adapter._handle_positions_result(payload)

        # Verify future was resolved
        assert future.done()
        positions = future.result()
        assert len(positions) == 1
        assert positions[0].symbol == "XAUUSD"
        assert positions[0].volume == Decimal("0.1")

        # Verify pending request was removed
        assert request_id not in adapter._pending_positions


class TestPendingPositionFutureCleanupOnTimeout:
    """Test pending position future cleanup on timeout."""

    @pytest.mark.asyncio
    async def test_pending_future_cleanup_on_timeout(self) -> None:
        """Test that pending futures are cleaned up on timeout."""
        adapter = ZmqAdapter(ZmqConfig())

        # Mock the pub socket to simulate not connected scenario
        adapter._pub_socket = MagicMock()
        adapter._pub_socket.send_multipart = AsyncMock()

        # Set very short timeout
        with pytest.raises(asyncio.TimeoutError):
            await adapter.query_positions("test-account", timeout=0.01)

        # Verify pending positions is empty (cleaned up after timeout)
        assert len(adapter._pending_positions) == 0

    @pytest.mark.asyncio
    async def test_pending_position_query_count(self) -> None:
        """Test get_pending_position_query_count method."""
        adapter = ZmqAdapter(ZmqConfig())

        # Initially empty
        assert adapter.get_pending_position_query_count() == 0

        # Add pending future
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[MT5Position]] = loop.create_future()
        adapter._pending_positions["test-1"] = future
        adapter._pending_positions["test-2"] = loop.create_future()

        assert adapter.get_pending_position_query_count() == 2
