"""Unit tests for StateSnapshotModel SQLAlchemy model."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.state.snapshot import StateSnapshot
from src.state.snapshot_db_model import StateSnapshotModel


@pytest.fixture
def sample_snapshot() -> StateSnapshot:
    """Create a sample StateSnapshot for testing."""
    snapshot = StateSnapshot(
        account_id="ftmo-gold-001",
        timestamp=datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
        positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
        pending_orders=[],
        account_balance=Decimal("100000.00"),
        equity=Decimal("99850.00"),
        peak_balance=Decimal("102500.00"),
        daily_starting_balance=Decimal("100500.00"),
        checksum="",
    )
    snapshot.checksum = snapshot.compute_checksum()
    return snapshot


class TestFromSnapshot:
    """Tests for StateSnapshotModel.from_snapshot() conversion."""

    def test_from_snapshot_creates_model(self, sample_snapshot: StateSnapshot):
        """from_snapshot should create a valid model from StateSnapshot."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)

        assert model.account_id == sample_snapshot.account_id
        assert model.timestamp == sample_snapshot.timestamp
        assert model.positions == sample_snapshot.positions
        assert model.pending_orders == sample_snapshot.pending_orders
        assert model.account_balance == sample_snapshot.account_balance
        assert model.equity == sample_snapshot.equity
        assert model.peak_balance == sample_snapshot.peak_balance
        assert model.daily_starting_balance == sample_snapshot.daily_starting_balance
        assert model.checksum == sample_snapshot.checksum

    def test_from_snapshot_generates_uuid(self, sample_snapshot: StateSnapshot):
        """from_snapshot should generate a new UUID."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)

        assert model.id is not None
        assert isinstance(model.id, uuid.UUID)

    def test_from_snapshot_preserves_positions(self, sample_snapshot: StateSnapshot):
        """from_snapshot should preserve positions as JSONB-compatible list."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)

        assert len(model.positions) == 1
        assert model.positions[0]["symbol"] == "XAUUSD"
        assert model.positions[0]["side"] == "BUY"

    def test_from_snapshot_converts_decimals(self, sample_snapshot: StateSnapshot):
        """from_snapshot should convert Decimal values correctly."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)

        assert model.account_balance == Decimal("100000.00")
        assert model.equity == Decimal("99850.00")

    def test_from_snapshot_empty_lists(self):
        """from_snapshot should handle empty positions and pending_orders."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("0"),
            equity=Decimal("0"),
            peak_balance=Decimal("0"),
            daily_starting_balance=Decimal("0"),
            checksum="test",
        )

        model = StateSnapshotModel.from_snapshot(snapshot)

        assert model.positions == []
        assert model.pending_orders == []


class TestToSnapshot:
    """Tests for StateSnapshotModel.to_snapshot() conversion."""

    def test_to_snapshot_creates_snapshot(self, sample_snapshot: StateSnapshot):
        """to_snapshot should create a valid StateSnapshot from model."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)
        restored = model.to_snapshot()

        assert restored.account_id == sample_snapshot.account_id
        assert restored.timestamp == sample_snapshot.timestamp
        assert restored.positions == sample_snapshot.positions
        assert restored.pending_orders == sample_snapshot.pending_orders
        assert restored.account_balance == sample_snapshot.account_balance
        assert restored.equity == sample_snapshot.equity
        assert restored.peak_balance == sample_snapshot.peak_balance
        assert restored.daily_starting_balance == sample_snapshot.daily_starting_balance
        assert restored.checksum == sample_snapshot.checksum

    def test_to_snapshot_preserves_checksum(self, sample_snapshot: StateSnapshot):
        """to_snapshot should preserve checksum for validation."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)
        restored = model.to_snapshot()

        assert restored.validate_checksum() is True

    def test_to_snapshot_decimal_types(self, sample_snapshot: StateSnapshot):
        """to_snapshot should return Decimal types."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)
        restored = model.to_snapshot()

        assert isinstance(restored.account_balance, Decimal)
        assert isinstance(restored.equity, Decimal)
        assert isinstance(restored.peak_balance, Decimal)
        assert isinstance(restored.daily_starting_balance, Decimal)


class TestRoundTrip:
    """Tests for StateSnapshot -> Model -> StateSnapshot round-trip."""

    def test_round_trip_preserves_values(self, sample_snapshot: StateSnapshot):
        """Round-trip conversion should preserve all values."""
        model = StateSnapshotModel.from_snapshot(sample_snapshot)
        restored = model.to_snapshot()

        # All fields should match
        assert restored.account_id == sample_snapshot.account_id
        assert restored.timestamp == sample_snapshot.timestamp
        assert restored.positions == sample_snapshot.positions
        assert restored.pending_orders == sample_snapshot.pending_orders
        assert restored.account_balance == sample_snapshot.account_balance
        assert restored.equity == sample_snapshot.equity
        assert restored.peak_balance == sample_snapshot.peak_balance
        assert restored.daily_starting_balance == sample_snapshot.daily_starting_balance
        assert restored.checksum == sample_snapshot.checksum

    def test_round_trip_with_multiple_positions(self):
        """Round-trip should preserve multiple positions."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1", "entry_price": "2000.50"},
            {"symbol": "EURUSD", "side": "SELL", "volume": "1.0", "entry_price": "1.0850"},
        ]
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=positions,
            pending_orders=[{"order_id": "123"}],
            account_balance=Decimal("50000"),
            equity=Decimal("49500"),
            peak_balance=Decimal("52000"),
            daily_starting_balance=Decimal("51000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        model = StateSnapshotModel.from_snapshot(snapshot)
        restored = model.to_snapshot()

        assert len(restored.positions) == 2
        assert restored.positions[0]["symbol"] == "XAUUSD"
        assert restored.positions[1]["symbol"] == "EURUSD"
        assert len(restored.pending_orders) == 1

    def test_round_trip_decimal_precision(self):
        """Round-trip should preserve Decimal precision."""
        snapshot = StateSnapshot(
            account_id="test",
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

        model = StateSnapshotModel.from_snapshot(snapshot)
        restored = model.to_snapshot()

        assert restored.account_balance == Decimal("100000.12")
        assert restored.equity == Decimal("99850.87")
        assert restored.peak_balance == Decimal("102500.00")
        assert restored.daily_starting_balance == Decimal("100500.50")


class TestModelAttributes:
    """Tests for StateSnapshotModel table attributes."""

    def test_tablename(self):
        """Model should have correct tablename."""
        assert StateSnapshotModel.__tablename__ == "state_snapshots"

    def test_composite_primary_key(self):
        """Model should have composite primary key (id, timestamp)."""
        # Check that both columns are marked as primary keys
        assert StateSnapshotModel.id.primary_key is True
        assert StateSnapshotModel.timestamp.primary_key is True
