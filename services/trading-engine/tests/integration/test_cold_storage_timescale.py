"""Integration tests for TimescaleDB cold storage persistence.

These tests require a running TimescaleDB instance with the state_snapshots table.
Set TEST_DATABASE_URL environment variable to point to your test TimescaleDB instance.

Run with:
    # Ensure TimescaleDB is running with schema from infra/timescaledb/init.sql:
    TEST_DATABASE_URL="postgresql+asyncpg://postgres:password@localhost:5432/trading" \
        uv run pytest tests/integration/test_cold_storage_timescaledb.py -v -m integration

Note: Run infra/timescaledb/init.sql on your test database first to create tables.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.state.cold_storage_writer import ColdStorageWriter
from src.state.snapshot import StateSnapshot


@pytest.fixture
def database_url():
    """Get TimescaleDB URL from environment or use default test URL."""
    return os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:password@localhost:5432/trading",
    )


@pytest.fixture
async def cold_storage_writer(database_url):
    """Create ColdStorageWriter for integration tests."""
    writer = ColdStorageWriter(database_url)
    await writer.start()
    yield writer
    await writer.stop()


@pytest.fixture
def sample_snapshot():
    """Create sample StateSnapshot for testing."""
    snapshot = StateSnapshot(
        account_id="test-cold-storage-001",
        timestamp=datetime.now(timezone.utc),
        positions=[
            {
                "symbol": "XAUUSD",
                "side": "BUY",
                "volume": "0.1",
                "entry_price": "1850.25",
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
class TestColdStorageWriteSnapshot:
    """Tests for write_snapshot TimescaleDB persistence (Story 5.7 AC1)."""

    @pytest.mark.asyncio
    async def test_write_snapshot_success(
        self, cold_storage_writer, sample_snapshot
    ):
        """write_snapshot should successfully persist to TimescaleDB."""
        await cold_storage_writer.write_snapshot(sample_snapshot)

        # Verify by reading back
        result = await cold_storage_writer.get_latest_snapshot(
            sample_snapshot.account_id
        )

        assert result is not None
        assert result.account_id == sample_snapshot.account_id
        assert result.account_balance == sample_snapshot.account_balance
        assert result.equity == sample_snapshot.equity
        assert result.checksum == sample_snapshot.checksum

    @pytest.mark.asyncio
    async def test_write_snapshot_preserves_positions(
        self, cold_storage_writer, sample_snapshot
    ):
        """write_snapshot should preserve positions JSONB correctly."""
        await cold_storage_writer.write_snapshot(sample_snapshot)

        result = await cold_storage_writer.get_latest_snapshot(
            sample_snapshot.account_id
        )

        assert result is not None
        assert len(result.positions) == 1
        assert result.positions[0]["symbol"] == "XAUUSD"
        assert result.positions[0]["side"] == "BUY"

    @pytest.mark.asyncio
    async def test_write_snapshot_preserves_checksum(
        self, cold_storage_writer, sample_snapshot
    ):
        """write_snapshot should preserve checksum for validation."""
        await cold_storage_writer.write_snapshot(sample_snapshot)

        result = await cold_storage_writer.get_latest_snapshot(
            sample_snapshot.account_id
        )

        assert result is not None
        assert result.validate_checksum() is True


@pytest.mark.integration
class TestColdStorageWriteSnapshots:
    """Tests for write_snapshots batch insert (Story 5.7 AC1)."""

    @pytest.mark.asyncio
    async def test_write_snapshots_batch(self, cold_storage_writer):
        """write_snapshots should batch insert multiple snapshots."""
        now = datetime.now(timezone.utc)
        snapshots = []

        for i in range(3):
            snapshot = StateSnapshot(
                account_id=f"test-batch-{i:03d}",
                timestamp=now + timedelta(seconds=i),
                positions=[],
                pending_orders=[],
                account_balance=Decimal("100000") + Decimal(i * 1000),
                equity=Decimal("100000") + Decimal(i * 1000),
                peak_balance=Decimal("100000") + Decimal(i * 1000),
                daily_starting_balance=Decimal("100000"),
                checksum="",
            )
            snapshot.checksum = snapshot.compute_checksum()
            snapshots.append(snapshot)

        await cold_storage_writer.write_snapshots(snapshots)

        # Verify all were written
        for snapshot in snapshots:
            result = await cold_storage_writer.get_latest_snapshot(
                snapshot.account_id
            )
            assert result is not None
            assert result.account_id == snapshot.account_id


@pytest.mark.integration
class TestColdStorageGetLatestSnapshot:
    """Tests for get_latest_snapshot retrieval (Story 5.7 AC2, AC4)."""

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_returns_most_recent(
        self, cold_storage_writer
    ):
        """get_latest_snapshot should return the most recent snapshot."""
        account_id = "test-latest-001"
        now = datetime.now(timezone.utc)

        # Write older snapshot
        old_snapshot = StateSnapshot(
            account_id=account_id,
            timestamp=now - timedelta(minutes=5),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("90000"),
            equity=Decimal("90000"),
            peak_balance=Decimal("90000"),
            daily_starting_balance=Decimal("90000"),
            checksum="",
        )
        old_snapshot.checksum = old_snapshot.compute_checksum()
        await cold_storage_writer.write_snapshot(old_snapshot)

        # Write newer snapshot
        new_snapshot = StateSnapshot(
            account_id=account_id,
            timestamp=now,
            positions=[{"symbol": "XAUUSD"}],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("100000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        new_snapshot.checksum = new_snapshot.compute_checksum()
        await cold_storage_writer.write_snapshot(new_snapshot)

        # Get latest should return newer
        result = await cold_storage_writer.get_latest_snapshot(account_id)

        assert result is not None
        assert result.account_balance == Decimal("100000")
        assert len(result.positions) == 1

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_returns_none_for_unknown(
        self, cold_storage_writer
    ):
        """get_latest_snapshot should return None for unknown account."""
        result = await cold_storage_writer.get_latest_snapshot(
            "nonexistent-account-xyz"
        )

        assert result is None


@pytest.mark.integration
class TestColdStorageDecimalPrecision:
    """Tests for Decimal precision preservation (Story 5.7 AC1)."""

    @pytest.mark.asyncio
    async def test_decimal_precision_preserved(self, cold_storage_writer):
        """TimescaleDB should preserve Decimal precision."""
        snapshot = StateSnapshot(
            account_id="test-precision-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.12"),
            equity=Decimal("99850.87"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.50"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        await cold_storage_writer.write_snapshot(snapshot)
        result = await cold_storage_writer.get_latest_snapshot(
            snapshot.account_id
        )

        assert result is not None
        assert result.account_balance == Decimal("100000.12")
        assert result.equity == Decimal("99850.87")
        assert result.peak_balance == Decimal("102500.00")
        assert result.daily_starting_balance == Decimal("100500.50")


@pytest.mark.integration
class TestColdStorageRoundTrip:
    """Tests for complete round-trip persistence (Story 5.7 AC1)."""

    @pytest.mark.asyncio
    async def test_round_trip_preserves_all_fields(self, cold_storage_writer):
        """Full write/read cycle should preserve all snapshot fields."""
        original = StateSnapshot(
            account_id="test-roundtrip-001",
            timestamp=datetime.now(timezone.utc),
            positions=[
                {
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "volume": "0.1",
                    "entry_price": "2000.50",
                },
                {
                    "symbol": "EURUSD",
                    "side": "SELL",
                    "volume": "1.0",
                    "entry_price": "1.0850",
                },
            ],
            pending_orders=[
                {"order_id": "pending-123", "symbol": "GBPUSD"}
            ],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="",
        )
        original.checksum = original.compute_checksum()

        await cold_storage_writer.write_snapshot(original)
        restored = await cold_storage_writer.get_latest_snapshot(
            original.account_id
        )

        assert restored is not None
        assert restored.account_id == original.account_id
        assert restored.positions == original.positions
        assert restored.pending_orders == original.pending_orders
        assert restored.account_balance == original.account_balance
        assert restored.equity == original.equity
        assert restored.peak_balance == original.peak_balance
        assert restored.daily_starting_balance == original.daily_starting_balance
        assert restored.checksum == original.checksum
        assert restored.validate_checksum() is True
