"""Unit tests for PositionTracker."""

import pytest
from datetime import datetime, timezone

from src.adapters.zmq_models import OrderSide
from src.orders.order import InternalOrder, OrderState
from src.orders.position_tracker import Position, PositionTracker


class TestPosition:
    """Tests for Position model."""

    def test_create_long_position(self):
        """Should create a long position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        assert position.is_long is True
        assert position.is_short is False
        assert position.side == OrderSide.BUY

    def test_create_short_position(self):
        """Should create a short position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        assert position.is_short is True
        assert position.is_long is False
        assert position.side == OrderSide.SELL

    def test_unrealized_pnl_long_profit(self):
        """Unrealized PnL for profitable long position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        pnl = position.unrealized_pnl(1860.00)
        assert pnl == pytest.approx(1.0)  # (1860-1850) * 0.1

    def test_unrealized_pnl_long_loss(self):
        """Unrealized PnL for losing long position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        pnl = position.unrealized_pnl(1840.00)
        assert pnl == pytest.approx(-1.0)  # (1840-1850) * 0.1

    def test_unrealized_pnl_short_profit(self):
        """Unrealized PnL for profitable short position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        pnl = position.unrealized_pnl(1840.00)  # Price down = profit for short
        assert pnl == pytest.approx(1.0)

    def test_unrealized_pnl_short_loss(self):
        """Unrealized PnL for losing short position."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        pnl = position.unrealized_pnl(1860.00)  # Price up = loss for short
        assert pnl == pytest.approx(-1.0)

    def test_position_repr(self):
        """Position repr should contain key information."""
        position = Position(
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            order_id="order-123",
        )

        repr_str = repr(position)
        assert "Position" in repr_str
        assert "BUY" in repr_str
        assert "XAUUSD" in repr_str
        assert "0.1" in repr_str
        assert "ftmo-001" in repr_str


class TestPositionTracker:
    """Tests for PositionTracker."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh position tracker."""
        return PositionTracker()

    @pytest.fixture
    def filled_order(self):
        """Create a filled order for testing."""
        order = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            price=1850.00,
        )
        order.state = OrderState.FILLED
        order.fill_price = 1850.45
        order.filled_at = datetime.now(timezone.utc)
        return order

    def test_open_position(self, tracker, filled_order):
        """Should open a new position from filled order."""
        position = tracker.open_position(filled_order)

        assert position.account_id == "ftmo-001"
        assert position.symbol == "XAUUSD"
        assert position.side == OrderSide.BUY
        assert position.quantity == 0.1
        assert position.entry_price == 1850.45
        assert position.order_id == filled_order.order_id

    def test_open_position_stored(self, tracker, filled_order):
        """Opened position should be stored in tracker."""
        tracker.open_position(filled_order)

        assert tracker.has_position("ftmo-001", "XAUUSD") is True
        assert len(tracker) == 1

    def test_get_position(self, tracker, filled_order):
        """Should retrieve stored position."""
        tracker.open_position(filled_order)

        position = tracker.get_position("ftmo-001", "XAUUSD")

        assert position is not None
        assert position.symbol == "XAUUSD"

    def test_get_position_not_found(self, tracker):
        """Should return None for non-existent position."""
        position = tracker.get_position("ftmo-001", "XAUUSD")
        assert position is None

    def test_has_position_true(self, tracker, filled_order):
        """has_position should return True for existing position."""
        tracker.open_position(filled_order)
        assert tracker.has_position("ftmo-001", "XAUUSD") is True

    def test_has_position_false(self, tracker):
        """has_position should return False for non-existent position."""
        assert tracker.has_position("ftmo-001", "XAUUSD") is False

    def test_close_position(self, tracker, filled_order):
        """Should close and remove position."""
        tracker.open_position(filled_order)

        closed = tracker.close_position("ftmo-001", "XAUUSD")

        assert closed is not None
        assert closed.symbol == "XAUUSD"
        assert tracker.has_position("ftmo-001", "XAUUSD") is False
        assert len(tracker) == 0

    def test_close_position_not_found(self, tracker):
        """Closing non-existent position should return None."""
        closed = tracker.close_position("ftmo-001", "XAUUSD")
        assert closed is None

    def test_open_duplicate_position_raises_error(self, tracker, filled_order):
        """Opening duplicate position should raise ValueError."""
        tracker.open_position(filled_order)

        with pytest.raises(ValueError, match="Position already exists"):
            tracker.open_position(filled_order)

    def test_multiple_positions_different_symbols(self, tracker):
        """Should track multiple positions for different symbols."""
        order1 = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            price=1850.00,
        )
        order1.state = OrderState.FILLED
        order1.fill_price = 1850.00
        order1.filled_at = datetime.now(timezone.utc)

        order2 = InternalOrder(
            account_id="ftmo-001",
            symbol="EURUSD",
            action=OrderSide.SELL,
            volume=0.5,
            price=1.0850,
        )
        order2.state = OrderState.FILLED
        order2.fill_price = 1.0850
        order2.filled_at = datetime.now(timezone.utc)

        tracker.open_position(order1)
        tracker.open_position(order2)

        assert len(tracker) == 2
        assert tracker.has_position("ftmo-001", "XAUUSD") is True
        assert tracker.has_position("ftmo-001", "EURUSD") is True

    def test_multiple_positions_different_accounts(self, tracker):
        """Should track positions for different accounts."""
        order1 = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            price=1850.00,
        )
        order1.state = OrderState.FILLED
        order1.fill_price = 1850.00
        order1.filled_at = datetime.now(timezone.utc)

        order2 = InternalOrder(
            account_id="ftmo-002",
            symbol="XAUUSD",
            action=OrderSide.SELL,
            volume=0.2,
            price=1851.00,
        )
        order2.state = OrderState.FILLED
        order2.fill_price = 1851.00
        order2.filled_at = datetime.now(timezone.utc)

        tracker.open_position(order1)
        tracker.open_position(order2)

        assert len(tracker) == 2
        assert tracker.has_position("ftmo-001", "XAUUSD") is True
        assert tracker.has_position("ftmo-002", "XAUUSD") is True


class TestPositionTrackerQueries:
    """Tests for PositionTracker query methods."""

    @pytest.fixture
    def populated_tracker(self):
        """Create tracker with multiple positions."""
        tracker = PositionTracker()

        orders = [
            InternalOrder(
                account_id="ftmo-001",
                symbol="XAUUSD",
                action=OrderSide.BUY,
                volume=0.1,
                price=1850.00,
            ),
            InternalOrder(
                account_id="ftmo-001",
                symbol="EURUSD",
                action=OrderSide.SELL,
                volume=0.5,
                price=1.0850,
            ),
            InternalOrder(
                account_id="ftmo-002",
                symbol="XAUUSD",
                action=OrderSide.SELL,
                volume=0.2,
                price=1851.00,
            ),
        ]

        for order in orders:
            order.state = OrderState.FILLED
            order.fill_price = order.price
            order.filled_at = datetime.now(timezone.utc)
            tracker.open_position(order)

        return tracker

    def test_get_all_positions(self, populated_tracker):
        """Should return all positions."""
        positions = populated_tracker.get_all_positions()
        assert len(positions) == 3

    def test_get_all_positions_filtered_by_account(self, populated_tracker):
        """Should filter positions by account."""
        positions = populated_tracker.get_all_positions(account_id="ftmo-001")
        assert len(positions) == 2

        positions = populated_tracker.get_all_positions(account_id="ftmo-002")
        assert len(positions) == 1

    def test_get_position_count(self, populated_tracker):
        """Should return total position count."""
        assert populated_tracker.get_position_count() == 3

    def test_get_position_count_filtered(self, populated_tracker):
        """Should filter position count by account."""
        assert populated_tracker.get_position_count(account_id="ftmo-001") == 2
        assert populated_tracker.get_position_count(account_id="ftmo-002") == 1
        assert populated_tracker.get_position_count(account_id="ftmo-003") == 0

    def test_clear(self, populated_tracker):
        """Should clear all positions."""
        count = populated_tracker.clear()

        assert count == 3
        assert len(populated_tracker) == 0

    def test_len(self, populated_tracker):
        """len() should return position count."""
        assert len(populated_tracker) == 3

    def test_repr(self, populated_tracker):
        """repr should show position count."""
        repr_str = repr(populated_tracker)
        assert "PositionTracker" in repr_str
        assert "3" in repr_str


class TestGetPositionsDict:
    """Tests for get_positions_dict() method (Story 5.1)."""

    @pytest.fixture
    def tracker_with_positions(self):
        """Create tracker with positions for dict testing."""
        tracker = PositionTracker()

        order1 = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            price=1850.00,
        )
        order1.state = OrderState.FILLED
        order1.fill_price = 1850.25
        order1.filled_at = datetime(2026, 1, 3, 10, 0, 0, tzinfo=timezone.utc)
        tracker.open_position(order1)

        order2 = InternalOrder(
            account_id="ftmo-001",
            symbol="EURUSD",
            action=OrderSide.SELL,
            volume=0.5,
            price=1.0850,
        )
        order2.state = OrderState.FILLED
        order2.fill_price = 1.0852
        order2.filled_at = datetime(2026, 1, 3, 11, 0, 0, tzinfo=timezone.utc)
        tracker.open_position(order2)

        order3 = InternalOrder(
            account_id="ftmo-002",
            symbol="XAUUSD",
            action=OrderSide.SELL,
            volume=0.2,
            price=1851.00,
        )
        order3.state = OrderState.FILLED
        order3.fill_price = 1851.50
        order3.filled_at = datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)
        tracker.open_position(order3)

        return tracker

    def test_get_positions_dict_returns_list(self, tracker_with_positions):
        """get_positions_dict should return a list of dicts."""
        result = tracker_with_positions.get_positions_dict()
        assert isinstance(result, list)
        assert len(result) == 3
        assert all(isinstance(item, dict) for item in result)

    def test_get_positions_dict_filtered_by_account(self, tracker_with_positions):
        """get_positions_dict should filter by account_id."""
        result = tracker_with_positions.get_positions_dict(account_id="ftmo-001")
        assert len(result) == 2

        result = tracker_with_positions.get_positions_dict(account_id="ftmo-002")
        assert len(result) == 1

    def test_get_positions_dict_empty_tracker(self):
        """get_positions_dict should return empty list for empty tracker."""
        tracker = PositionTracker()
        result = tracker.get_positions_dict()
        assert result == []

    def test_get_positions_dict_nonexistent_account(self, tracker_with_positions):
        """get_positions_dict should return empty list for unknown account."""
        result = tracker_with_positions.get_positions_dict(account_id="unknown")
        assert result == []

    def test_get_positions_dict_contains_required_fields(self, tracker_with_positions):
        """Each position dict should have all required snapshot fields."""
        result = tracker_with_positions.get_positions_dict(account_id="ftmo-001")

        for pos_dict in result:
            assert "symbol" in pos_dict
            assert "side" in pos_dict
            assert "volume" in pos_dict
            assert "entry_price" in pos_dict
            assert "entry_time" in pos_dict
            assert "order_id" in pos_dict

    def test_get_positions_dict_values_are_strings(self, tracker_with_positions):
        """Volume and entry_price should be serialized as strings."""
        result = tracker_with_positions.get_positions_dict(account_id="ftmo-001")

        for pos_dict in result:
            assert isinstance(pos_dict["volume"], str)
            assert isinstance(pos_dict["entry_price"], str)
            assert isinstance(pos_dict["entry_time"], str)

    def test_get_positions_dict_volume_from_quantity(self, tracker_with_positions):
        """Volume field should be string of Position.quantity."""
        result = tracker_with_positions.get_positions_dict(account_id="ftmo-001")

        # Find XAUUSD position (volume 0.1)
        xau_pos = next(p for p in result if p["symbol"] == "XAUUSD")
        assert xau_pos["volume"] == "0.1"

        # Find EURUSD position (volume 0.5)
        eur_pos = next(p for p in result if p["symbol"] == "EURUSD")
        assert eur_pos["volume"] == "0.5"

    def test_get_positions_dict_side_is_enum_value(self, tracker_with_positions):
        """Side should be the enum value string (BUY/SELL)."""
        result = tracker_with_positions.get_positions_dict()

        sides = {p["side"] for p in result}
        assert sides == {"BUY", "SELL"}

    def test_get_positions_dict_entry_time_iso_format(self, tracker_with_positions):
        """Entry time should be in ISO format."""
        result = tracker_with_positions.get_positions_dict(account_id="ftmo-001")

        xau_pos = next(p for p in result if p["symbol"] == "XAUUSD")
        assert xau_pos["entry_time"] == "2026-01-03T10:00:00+00:00"

    def test_get_positions_dict_preserves_order_id(self, tracker_with_positions):
        """Order ID should be preserved as non-empty string."""
        result = tracker_with_positions.get_positions_dict()

        for pos_dict in result:
            assert isinstance(pos_dict["order_id"], str)
            assert len(pos_dict["order_id"]) > 0
