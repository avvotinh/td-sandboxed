"""Unit tests for StateSnapshot dataclass."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.state.snapshot import StateSnapshot


class TestStateSnapshotInitialization:
    """Tests for StateSnapshot initialization."""

    def test_create_snapshot(self):
        """StateSnapshot should initialize with all required fields."""
        now = datetime.now(timezone.utc)
        snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=now,
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="abc123",
        )

        assert snapshot.account_id == "ftmo-gold-001"
        assert snapshot.timestamp == now
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0]["symbol"] == "XAUUSD"
        assert snapshot.pending_orders == []
        assert snapshot.account_balance == Decimal("100000.00")
        assert snapshot.equity == Decimal("99850.00")
        assert snapshot.peak_balance == Decimal("102500.00")
        assert snapshot.daily_starting_balance == Decimal("100500.00")
        assert snapshot.checksum == "abc123"

    def test_create_empty_positions(self):
        """StateSnapshot should work with empty positions list."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("0"),
            equity=Decimal("0"),
            peak_balance=Decimal("0"),
            daily_starting_balance=Decimal("0"),
            checksum="",
        )

        assert snapshot.positions == []
        assert snapshot.pending_orders == []


class TestToDictSerialization:
    """Tests for to_dict() serialization."""

    def test_to_dict_all_values_are_strings(self):
        """to_dict should serialize all values as strings for Redis."""
        now = datetime.now(timezone.utc)
        snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=now,
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="testchecksum",
        )

        data = snapshot.to_dict()

        # All values should be strings
        for key, value in data.items():
            assert isinstance(value, str), f"{key} should be string"

    def test_to_dict_decimal_precision(self):
        """to_dict should preserve Decimal precision."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.12345678"),
            equity=Decimal("99850.87654321"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.50"),
            checksum="",
        )

        data = snapshot.to_dict()

        assert data["account_balance"] == "100000.12345678"
        assert data["equity"] == "99850.87654321"
        assert data["peak_balance"] == "102500.00"
        assert data["daily_starting_balance"] == "100500.50"

    def test_to_dict_lists_as_json(self):
        """to_dict should serialize lists as JSON strings."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
            {"symbol": "EURUSD", "side": "SELL", "volume": "1.0"},
        ]
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=positions,
            pending_orders=[{"order_id": "123"}],
            account_balance=Decimal("0"),
            equity=Decimal("0"),
            peak_balance=Decimal("0"),
            daily_starting_balance=Decimal("0"),
            checksum="",
        )

        data = snapshot.to_dict()

        # Should be valid JSON strings
        parsed_positions = json.loads(data["positions"])
        parsed_orders = json.loads(data["pending_orders"])

        assert len(parsed_positions) == 2
        assert parsed_positions[0]["symbol"] == "XAUUSD"
        assert len(parsed_orders) == 1

    def test_to_dict_timestamp_isoformat(self):
        """to_dict should serialize timestamp as ISO format."""
        now = datetime(2026, 1, 3, 14, 30, 0, tzinfo=timezone.utc)
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("0"),
            equity=Decimal("0"),
            peak_balance=Decimal("0"),
            daily_starting_balance=Decimal("0"),
            checksum="",
        )

        data = snapshot.to_dict()

        assert data["timestamp"] == "2026-01-03T14:30:00+00:00"


class TestFromDictDeserialization:
    """Tests for from_dict() deserialization."""

    def test_from_dict_basic(self):
        """from_dict should deserialize all fields correctly."""
        data = {
            "account_id": "ftmo-gold-001",
            "timestamp": "2026-01-03T14:30:00+00:00",
            "positions": '[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}]',
            "pending_orders": "[]",
            "account_balance": "100000.00",
            "equity": "99850.00",
            "peak_balance": "102500.00",
            "daily_starting_balance": "100500.00",
            "checksum": "abc123",
        }

        snapshot = StateSnapshot.from_dict(data)

        assert snapshot.account_id == "ftmo-gold-001"
        assert snapshot.timestamp.year == 2026
        assert snapshot.timestamp.month == 1
        assert snapshot.timestamp.day == 3
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0]["symbol"] == "XAUUSD"
        assert snapshot.pending_orders == []
        assert snapshot.account_balance == Decimal("100000.00")
        assert snapshot.equity == Decimal("99850.00")
        assert snapshot.peak_balance == Decimal("102500.00")
        assert snapshot.daily_starting_balance == Decimal("100500.00")
        assert snapshot.checksum == "abc123"

    def test_from_dict_decimal_types(self):
        """from_dict should convert strings to Decimal."""
        data = {
            "account_id": "test",
            "timestamp": "2026-01-03T14:30:00+00:00",
            "positions": "[]",
            "pending_orders": "[]",
            "account_balance": "100000.12345678",
            "equity": "99850.87654321",
            "peak_balance": "102500.00",
            "daily_starting_balance": "100500.50",
            "checksum": "",
        }

        snapshot = StateSnapshot.from_dict(data)

        assert isinstance(snapshot.account_balance, Decimal)
        assert isinstance(snapshot.equity, Decimal)
        assert snapshot.account_balance == Decimal("100000.12345678")
        assert snapshot.equity == Decimal("99850.87654321")

    def test_from_dict_missing_field_raises(self):
        """from_dict should raise KeyError for missing required fields."""
        data = {
            "account_id": "test",
            # missing other required fields
        }

        with pytest.raises(KeyError):
            StateSnapshot.from_dict(data)

    def test_from_dict_invalid_json_raises(self):
        """from_dict should raise ValueError for invalid JSON."""
        data = {
            "account_id": "test",
            "timestamp": "2026-01-03T14:30:00+00:00",
            "positions": "not valid json",
            "pending_orders": "[]",
            "account_balance": "0",
            "equity": "0",
            "peak_balance": "0",
            "daily_starting_balance": "0",
            "checksum": "",
        }

        with pytest.raises(json.JSONDecodeError):
            StateSnapshot.from_dict(data)


class TestRoundTrip:
    """Tests for to_dict -> from_dict round-trip."""

    def test_round_trip_preserves_values(self):
        """to_dict -> from_dict should preserve all values."""
        original = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime(2026, 1, 3, 14, 30, 0, tzinfo=timezone.utc),
            positions=[
                {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
                {"symbol": "EURUSD", "side": "SELL", "volume": "1.0"},
            ],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="",
        )
        original.checksum = original.compute_checksum()

        restored = StateSnapshot.from_dict(original.to_dict())

        assert restored.account_id == original.account_id
        assert restored.timestamp == original.timestamp
        assert restored.positions == original.positions
        assert restored.pending_orders == original.pending_orders
        assert restored.account_balance == original.account_balance
        assert restored.equity == original.equity
        assert restored.peak_balance == original.peak_balance
        assert restored.daily_starting_balance == original.daily_starting_balance
        assert restored.checksum == original.checksum

    def test_round_trip_decimal_precision(self):
        """Round-trip should preserve Decimal precision."""
        original = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.123456789012345"),
            equity=Decimal("0.000000000000001"),
            peak_balance=Decimal("999999999999999.99"),
            daily_starting_balance=Decimal("-12345.6789"),
            checksum="",
        )

        restored = StateSnapshot.from_dict(original.to_dict())

        assert restored.account_balance == original.account_balance
        assert restored.equity == original.equity
        assert restored.peak_balance == original.peak_balance
        assert restored.daily_starting_balance == original.daily_starting_balance


class TestChecksumComputation:
    """Tests for compute_checksum() method."""

    def test_compute_checksum_returns_hex_string(self):
        """compute_checksum should return a 64-character hex string."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )

        checksum = snapshot.compute_checksum()

        assert len(checksum) == 64
        assert all(c in "0123456789abcdef" for c in checksum)

    def test_compute_checksum_deterministic(self):
        """compute_checksum should be deterministic (same input = same output)."""
        now = datetime(2026, 1, 3, 14, 30, 0, tzinfo=timezone.utc)

        snapshot1 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[{"a": "1", "b": "2"}],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )

        snapshot2 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[{"a": "1", "b": "2"}],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )

        assert snapshot1.compute_checksum() == snapshot2.compute_checksum()

    def test_compute_checksum_different_for_different_data(self):
        """compute_checksum should differ when data changes."""
        now = datetime(2026, 1, 3, 14, 30, 0, tzinfo=timezone.utc)

        snapshot1 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )

        snapshot2 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100001"),  # Changed
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )

        assert snapshot1.compute_checksum() != snapshot2.compute_checksum()

    def test_compute_checksum_ignores_checksum_field(self):
        """compute_checksum should not include the checksum field itself."""
        now = datetime(2026, 1, 3, 14, 30, 0, tzinfo=timezone.utc)

        snapshot1 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="different1",
        )

        snapshot2 = StateSnapshot(
            account_id="test",
            timestamp=now,
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="different2",
        )

        assert snapshot1.compute_checksum() == snapshot2.compute_checksum()


class TestChecksumValidation:
    """Tests for validate_checksum() method."""

    def test_validate_checksum_valid(self):
        """validate_checksum should return True for valid checksum."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        assert snapshot.validate_checksum() is True

    def test_validate_checksum_invalid(self):
        """validate_checksum should return False for invalid checksum."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="invalid_checksum",
        )

        assert snapshot.validate_checksum() is False

    def test_validate_checksum_detects_tampering(self):
        """validate_checksum should detect data tampering."""
        snapshot = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

        # Tamper with data
        snapshot.account_balance = Decimal("999999")

        assert snapshot.validate_checksum() is False

    def test_validate_checksum_after_round_trip(self):
        """Checksum should remain valid after to_dict -> from_dict."""
        original = StateSnapshot(
            account_id="test",
            timestamp=datetime.now(timezone.utc),
            positions=[{"symbol": "XAUUSD"}],
            pending_orders=[],
            account_balance=Decimal("100000"),
            equity=Decimal("99000"),
            peak_balance=Decimal("100000"),
            daily_starting_balance=Decimal("100000"),
            checksum="",
        )
        original.checksum = original.compute_checksum()

        restored = StateSnapshot.from_dict(original.to_dict())

        assert restored.validate_checksum() is True
