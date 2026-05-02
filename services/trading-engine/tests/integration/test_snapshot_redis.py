"""Integration tests for Redis state snapshot persistence.

These tests require a running Redis instance. Set TEST_REDIS_URL
environment variable to point to your test Redis instance.

Run with:
    # Using standard Redis port (default):
    uv run pytest tests/integration/test_snapshot_redis.py -v -m integration

    # Or with custom port:
    docker run -d --name test-redis -p 6380:6379 redis:7-alpine
    TEST_REDIS_URL=redis://localhost:6380 uv run pytest tests/integration/test_snapshot_redis.py -v -m integration
    docker stop test-redis && docker rm test-redis
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.state.redis_state import RedisStateManager
from src.state.snapshot import StateSnapshot
from src.state.snapshot_service import SnapshotService


@pytest.fixture
def redis_url():
    """Get Redis URL from environment or use default test URL."""
    return os.getenv("TEST_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def redis_manager(redis_url):
    """Create real Redis connection for integration tests."""
    manager = RedisStateManager(redis_url)
    await manager.connect()
    yield manager
    # Cleanup test keys
    try:
        async for key in manager.client.scan_iter("snapshot:test-*:latest"):
            await manager.client.delete(key)
        async for key in manager.client.scan_iter("account:test-*:*"):
            await manager.client.delete(key)
    except Exception:
        pass
    await manager.close()


@pytest.fixture
def sample_snapshot():
    """Create sample StateSnapshot for testing."""
    snapshot = StateSnapshot(
        account_id="test-snapshot-001",
        timestamp=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "XAUUSD",
                "side": "BUY",
                "volume": "0.1",
                "entry_price": "1850.25",
                "entry_time": "2026-01-03T10:00:00+00:00",
                "order_id": "order-123",
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


@pytest.mark.integration
class TestSaveSnapshot:
    """Tests for save_snapshot Redis persistence (AC2)."""

    @pytest.mark.asyncio
    async def test_save_snapshot_writes_to_correct_key(
        self, redis_manager, sample_snapshot
    ):
        """Snapshot should be saved to snapshot:{account_id}:latest key."""
        await redis_manager.save_snapshot(
            "test-snapshot-001",
            sample_snapshot,
        )

        # Verify key exists
        key = "snapshot:test-snapshot-001:latest"
        exists = await redis_manager.client.exists(key)
        assert exists == 1

    @pytest.mark.asyncio
    async def test_save_snapshot_all_fields(self, redis_manager, sample_snapshot):
        """All snapshot fields should be saved to Redis hash."""
        await redis_manager.save_snapshot(
            "test-snapshot-001",
            sample_snapshot,
        )

        key = "snapshot:test-snapshot-001:latest"
        data = await redis_manager.client.hgetall(key)

        assert data["account_id"] == "test-snapshot-001"
        assert "timestamp" in data
        assert "positions" in data
        assert "pending_orders" in data
        assert data["account_balance"] == "100000.00"
        assert data["equity"] == "99850.00"
        assert data["peak_balance"] == "102500.00"
        assert data["daily_starting_balance"] == "100500.00"
        assert "checksum" in data

    @pytest.mark.asyncio
    async def test_save_snapshot_overwrites_existing(self, redis_manager):
        """Saving again should overwrite previous snapshot."""
        # First snapshot
        snapshot1 = StateSnapshot(
            account_id="test-snapshot-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot1.checksum = snapshot1.compute_checksum()
        await redis_manager.save_snapshot("test-snapshot-001", snapshot1)

        # Second snapshot with different balance
        snapshot2 = StateSnapshot(
            account_id="test-snapshot-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("99000"),  # Changed
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot2.checksum = snapshot2.compute_checksum()
        await redis_manager.save_snapshot("test-snapshot-001", snapshot2)

        # Verify second snapshot's balance is stored
        key = "snapshot:test-snapshot-001:latest"
        data = await redis_manager.client.hgetall(key)
        assert data["account_balance"] == "99000"


@pytest.mark.integration
class TestSnapshotTTL:
    """Tests for snapshot TTL (AC3)."""

    @pytest.mark.asyncio
    async def test_ttl_is_set(self, redis_manager, sample_snapshot):
        """Snapshot key should have TTL set."""
        await redis_manager.save_snapshot(
            "test-snapshot-001",
            sample_snapshot,
            ttl_seconds=3600,
        )

        ttl = await redis_manager.get_snapshot_ttl("test-snapshot-001")

        # TTL should be close to 3600 (within 5 seconds)
        assert ttl is not None
        assert 3595 <= ttl <= 3600

    @pytest.mark.asyncio
    async def test_ttl_3600_seconds(self, redis_manager, sample_snapshot):
        """Default TTL should be 3600 seconds (1 hour)."""
        await redis_manager.save_snapshot(
            "test-snapshot-001",
            sample_snapshot,
        )

        key = "snapshot:test-snapshot-001:latest"
        ttl = await redis_manager.client.ttl(key)

        assert ttl > 3590  # Within 10 seconds of 3600

    @pytest.mark.asyncio
    async def test_custom_ttl(self, redis_manager, sample_snapshot):
        """Custom TTL should be respected."""
        await redis_manager.save_snapshot(
            "test-snapshot-001",
            sample_snapshot,
            ttl_seconds=60,  # 1 minute
        )

        ttl = await redis_manager.get_snapshot_ttl("test-snapshot-001")
        assert ttl is not None
        assert 55 <= ttl <= 60

    @pytest.mark.asyncio
    async def test_get_ttl_nonexistent_key(self, redis_manager):
        """get_snapshot_ttl should return None for nonexistent key."""
        ttl = await redis_manager.get_snapshot_ttl("nonexistent-account")
        assert ttl is None


@pytest.mark.integration
class TestGetSnapshot:
    """Tests for get_snapshot deserialization."""

    @pytest.mark.asyncio
    async def test_get_snapshot_retrieves_correctly(
        self, redis_manager, sample_snapshot
    ):
        """get_snapshot should retrieve and deserialize correctly."""
        await redis_manager.save_snapshot("test-snapshot-001", sample_snapshot)

        result = await redis_manager.get_snapshot("test-snapshot-001")

        assert result is not None
        assert result.account_id == sample_snapshot.account_id
        assert result.account_balance == sample_snapshot.account_balance
        assert result.equity == sample_snapshot.equity
        assert result.peak_balance == sample_snapshot.peak_balance

    @pytest.mark.asyncio
    async def test_get_snapshot_nonexistent(self, redis_manager):
        """get_snapshot should return None for nonexistent account."""
        result = await redis_manager.get_snapshot("nonexistent-account")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_snapshot_positions_preserved(
        self, redis_manager, sample_snapshot
    ):
        """Position data should be preserved through save/get cycle."""
        await redis_manager.save_snapshot("test-snapshot-001", sample_snapshot)

        result = await redis_manager.get_snapshot("test-snapshot-001")

        assert len(result.positions) == 1
        assert result.positions[0]["symbol"] == "XAUUSD"
        assert result.positions[0]["side"] == "BUY"
        assert result.positions[0]["volume"] == "0.1"


@pytest.mark.integration
class TestRoundTrip:
    """Tests for complete save -> get -> validate round-trip (AC6)."""

    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_fields(
        self, redis_manager, sample_snapshot
    ):
        """Save -> Get should preserve all fields."""
        await redis_manager.save_snapshot("test-snapshot-001", sample_snapshot)
        result = await redis_manager.get_snapshot("test-snapshot-001")

        assert result.account_id == sample_snapshot.account_id
        assert result.account_balance == sample_snapshot.account_balance
        assert result.equity == sample_snapshot.equity
        assert result.peak_balance == sample_snapshot.peak_balance
        assert result.daily_starting_balance == sample_snapshot.daily_starting_balance
        assert result.positions == sample_snapshot.positions
        assert result.pending_orders == sample_snapshot.pending_orders
        assert result.checksum == sample_snapshot.checksum

    @pytest.mark.asyncio
    async def test_round_trip_checksum_validates(
        self, redis_manager, sample_snapshot
    ):
        """Checksum should validate after round-trip."""
        await redis_manager.save_snapshot("test-snapshot-001", sample_snapshot)
        result = await redis_manager.get_snapshot("test-snapshot-001")

        assert result.validate_checksum() is True

    @pytest.mark.asyncio
    async def test_decimal_precision_preserved(self, redis_manager):
        """Decimal precision should be preserved through round-trip."""
        snapshot = StateSnapshot(
            account_id="test-precision",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.123456789"),
            equity=Decimal("99850.987654321"),
            peak_balance=Decimal("102500.000000001"),
            daily_starting_balance=Decimal("100500.555555555"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        await redis_manager.save_snapshot("test-precision", snapshot)
        result = await redis_manager.get_snapshot("test-precision")

        assert result.account_balance == snapshot.account_balance
        assert result.equity == snapshot.equity
        assert result.peak_balance == snapshot.peak_balance
        assert result.daily_starting_balance == snapshot.daily_starting_balance


@pytest.mark.integration
class TestConcurrentSaves:
    """Tests for concurrent snapshot saves (AC5)."""

    @pytest.mark.asyncio
    async def test_concurrent_saves_different_accounts(self, redis_manager):
        """Concurrent saves for different accounts should succeed."""
        snapshots = []
        for i in range(5):
            s = StateSnapshot(
                account_id=f"test-concurrent-{i}",
                timestamp=datetime.now(timezone.utc),
                positions=[],
                pending_orders=[],
                account_balance=Decimal(str(100000 + i)),
                equity=Decimal(str(99000 + i)),
                peak_balance=Decimal("100000"),
                daily_starting_balance=Decimal("100000"),
                checksum="",
            )
            s.checksum = s.compute_checksum()
            snapshots.append(s)

        # Save all concurrently
        await asyncio.gather(
            *[
                redis_manager.save_snapshot(s.account_id, s)
                for s in snapshots
            ]
        )

        # Verify all saved correctly
        for s in snapshots:
            result = await redis_manager.get_snapshot(s.account_id)
            assert result is not None
            assert result.account_balance == s.account_balance


@pytest.mark.integration
class TestPerformance:
    """Tests for snapshot performance (AC7: < 10ms)."""

    @pytest.mark.asyncio
    async def test_single_snapshot_under_10ms(self, redis_manager, sample_snapshot):
        """Single snapshot save should complete in under 10ms."""
        # Warm up connection
        await redis_manager.save_snapshot("test-warmup", sample_snapshot)

        # Time actual save
        start = time.perf_counter()
        await redis_manager.save_snapshot("test-perf", sample_snapshot)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"Snapshot save took {elapsed_ms:.2f}ms"

    @pytest.mark.asyncio
    async def test_get_snapshot_fast(self, redis_manager, sample_snapshot):
        """Snapshot retrieval should be fast."""
        await redis_manager.save_snapshot("test-perf-get", sample_snapshot)

        start = time.perf_counter()
        await redis_manager.get_snapshot("test-perf-get")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"Snapshot get took {elapsed_ms:.2f}ms"


@pytest.mark.integration
class TestSnapshotServiceFullCycle:
    """Tests for SnapshotService with real Redis."""

    @pytest.fixture
    def mock_account_manager(self):
        """Create mock AccountManager."""
        manager = MagicMock()
        manager.get_all_accounts = MagicMock(
            return_value=["test-svc-001", "test-svc-002"]
        )
        manager.get_account_status = MagicMock(return_value="active")
        # Make get_account_status async
        async def get_status(account_id):
            return "active"
        manager.get_account_status = get_status
        return manager

    @pytest.fixture
    def mock_position_tracker(self):
        """Create mock PositionTracker."""
        tracker = MagicMock()
        tracker.get_positions_dict = MagicMock(return_value=[])
        return tracker

    @pytest.fixture
    def mock_risk_registry(self):
        """Create mock RiskStateRegistry."""
        registry = MagicMock()
        mock_state = MagicMock()
        mock_state.current_equity = Decimal("99000")
        mock_state.peak_equity = Decimal("100000")
        mock_state.daily_starting_balance = Decimal("100000")
        registry.get_risk_state = MagicMock(return_value=mock_state)
        return registry

    @pytest.mark.asyncio
    async def test_service_full_cycle(
        self,
        redis_manager,
        mock_account_manager,
        mock_position_tracker,
        mock_risk_registry,
    ):
        """Test complete snapshot service cycle with real Redis."""
        # Setup balance in Redis
        await redis_manager.save_account_balance("test-svc-001", Decimal("100000"))
        await redis_manager.save_account_balance("test-svc-002", Decimal("100000"))

        service = SnapshotService(
            redis_manager=redis_manager,
            account_manager=mock_account_manager,
            position_tracker=mock_position_tracker,
            risk_registry=mock_risk_registry,
            interval_seconds=0.1,
        )

        # Run one snapshot cycle
        await service._snapshot_all_accounts()

        # Verify snapshots were created
        snapshot1 = await redis_manager.get_snapshot("test-svc-001")
        snapshot2 = await redis_manager.get_snapshot("test-svc-002")

        assert snapshot1 is not None
        assert snapshot2 is not None
        assert snapshot1.validate_checksum()
        assert snapshot2.validate_checksum()

    @pytest.mark.asyncio
    async def test_service_ttl_applied(
        self,
        redis_manager,
        mock_account_manager,
        mock_position_tracker,
        mock_risk_registry,
    ):
        """Service should apply correct TTL to snapshots."""
        await redis_manager.save_account_balance("test-svc-001", Decimal("100000"))

        service = SnapshotService(
            redis_manager=redis_manager,
            account_manager=mock_account_manager,
            position_tracker=mock_position_tracker,
            risk_registry=mock_risk_registry,
        )

        await service._snapshot_all_accounts()

        ttl = await redis_manager.get_snapshot_ttl("test-svc-001")
        assert ttl is not None
        assert ttl > 3590  # Within 10 seconds of 3600
