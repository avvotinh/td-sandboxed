"""Unit tests for order module (InternalOrder and OrderState)."""

import pytest

from src.adapters.zmq_models import OrderSide
from src.orders.order import InternalOrder, OrderState
from src.orders.signal import SignalType


class TestOrderState:
    """Tests for OrderState enum."""

    def test_pending_is_initial_state(self):
        """PENDING should be the initial state for new orders."""
        order = InternalOrder(account_id="test", symbol="XAUUSD")
        assert order.state == OrderState.PENDING

    def test_terminal_states(self):
        """Terminal states should be correctly identified."""
        assert OrderState.FILLED.is_terminal() is True
        assert OrderState.REJECTED.is_terminal() is True
        assert OrderState.CANCELLED.is_terminal() is True
        assert OrderState.ERROR.is_terminal() is True
        assert OrderState.PENDING.is_terminal() is False
        assert OrderState.SUBMITTED.is_terminal() is False
        assert OrderState.PARTIALLY_FILLED.is_terminal() is False

    def test_state_values(self):
        """State enum values should be lowercase strings."""
        assert OrderState.PENDING.value == "pending"
        assert OrderState.SUBMITTED.value == "submitted"
        assert OrderState.FILLED.value == "filled"
        assert OrderState.REJECTED.value == "rejected"


class TestOrderStateTransitions:
    """Tests for order state transitions."""

    def test_valid_transition_pending_to_submitted(self):
        """PENDING -> SUBMITTED is valid."""
        order = InternalOrder()
        assert order.can_transition_to(OrderState.SUBMITTED) is True
        order.transition_to(OrderState.SUBMITTED)
        assert order.state == OrderState.SUBMITTED

    def test_valid_transition_pending_to_cancelled(self):
        """PENDING -> CANCELLED is valid."""
        order = InternalOrder()
        assert order.can_transition_to(OrderState.CANCELLED) is True
        order.transition_to(OrderState.CANCELLED)
        assert order.state == OrderState.CANCELLED

    def test_valid_transition_pending_to_error(self):
        """PENDING -> ERROR is valid."""
        order = InternalOrder()
        assert order.can_transition_to(OrderState.ERROR) is True
        order.transition_to(OrderState.ERROR)
        assert order.state == OrderState.ERROR

    def test_valid_transition_submitted_to_filled(self):
        """SUBMITTED -> FILLED is valid."""
        order = InternalOrder()
        order.state = OrderState.SUBMITTED
        assert order.can_transition_to(OrderState.FILLED) is True
        order.transition_to(OrderState.FILLED)
        assert order.state == OrderState.FILLED

    def test_valid_transition_submitted_to_rejected(self):
        """SUBMITTED -> REJECTED is valid."""
        order = InternalOrder()
        order.state = OrderState.SUBMITTED
        assert order.can_transition_to(OrderState.REJECTED) is True
        order.transition_to(OrderState.REJECTED)
        assert order.state == OrderState.REJECTED

    def test_valid_transition_submitted_to_partially_filled(self):
        """SUBMITTED -> PARTIALLY_FILLED is valid."""
        order = InternalOrder()
        order.state = OrderState.SUBMITTED
        assert order.can_transition_to(OrderState.PARTIALLY_FILLED) is True
        order.transition_to(OrderState.PARTIALLY_FILLED)
        assert order.state == OrderState.PARTIALLY_FILLED

    def test_valid_transition_partially_filled_to_filled(self):
        """PARTIALLY_FILLED -> FILLED is valid."""
        order = InternalOrder()
        order.state = OrderState.PARTIALLY_FILLED
        assert order.can_transition_to(OrderState.FILLED) is True
        order.transition_to(OrderState.FILLED)
        assert order.state == OrderState.FILLED

    def test_invalid_transition_filled_to_pending(self):
        """FILLED -> PENDING is invalid (terminal state)."""
        order = InternalOrder()
        order.state = OrderState.FILLED
        assert order.can_transition_to(OrderState.PENDING) is False

        with pytest.raises(ValueError, match="Invalid state transition"):
            order.transition_to(OrderState.PENDING)

    def test_invalid_transition_rejected_to_submitted(self):
        """REJECTED -> SUBMITTED is invalid (terminal state)."""
        order = InternalOrder()
        order.state = OrderState.REJECTED
        assert order.can_transition_to(OrderState.SUBMITTED) is False

        with pytest.raises(ValueError, match="Invalid state transition"):
            order.transition_to(OrderState.SUBMITTED)

    def test_invalid_transition_pending_to_filled(self):
        """PENDING -> FILLED is invalid (must go through SUBMITTED)."""
        order = InternalOrder()
        assert order.can_transition_to(OrderState.FILLED) is False

        with pytest.raises(ValueError, match="Invalid state transition"):
            order.transition_to(OrderState.FILLED)

    def test_terminal_states_have_no_transitions(self):
        """Terminal states should have no valid outgoing transitions."""
        for terminal_state in [
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.ERROR,
        ]:
            order = InternalOrder()
            order.state = terminal_state
            for target_state in OrderState:
                if target_state != terminal_state:
                    assert order.can_transition_to(target_state) is False


class TestInternalOrder:
    """Tests for InternalOrder model."""

    def test_order_id_is_uuid(self):
        """Order ID should be a valid UUID format."""
        order = InternalOrder()
        # UUID format: 8-4-4-4-12 hex chars
        assert len(order.order_id) == 36
        assert order.order_id.count("-") == 4

    def test_unique_order_ids(self):
        """Each order should have a unique ID."""
        order1 = InternalOrder()
        order2 = InternalOrder()
        order3 = InternalOrder()
        assert order1.order_id != order2.order_id
        assert order2.order_id != order3.order_id
        assert order1.order_id != order3.order_id

    def test_default_values(self):
        """Default values should be set correctly."""
        order = InternalOrder()
        assert order.account_id == ""
        assert order.symbol == ""
        assert order.action == OrderSide.BUY
        assert order.volume == 0.0
        assert order.price == 0.0
        assert order.sl is None
        assert order.tp is None
        assert order.state == OrderState.PENDING
        assert order.fill_price is None
        assert order.slippage is None
        assert order.rejection_reason is None
        assert order.filled_quantity == 0.0

    def test_custom_values(self):
        """Custom values should be set correctly."""
        order = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.SELL,
            volume=0.5,
            price=1850.45,
            sl=1855.00,
            tp=1840.00,
        )
        assert order.account_id == "ftmo-001"
        assert order.symbol == "XAUUSD"
        assert order.action == OrderSide.SELL
        assert order.volume == 0.5
        assert order.price == 1850.45
        assert order.sl == 1855.00
        assert order.tp == 1840.00

    def test_created_at_is_set(self):
        """created_at should be automatically set."""
        order = InternalOrder()
        assert order.created_at is not None

    def test_is_terminal_property(self):
        """is_terminal property should delegate to state."""
        order = InternalOrder()
        assert order.is_terminal is False

        order.state = OrderState.FILLED
        assert order.is_terminal is True

    def test_is_filled_property(self):
        """is_filled property should check FILLED state."""
        order = InternalOrder()
        assert order.is_filled is False

        order.state = OrderState.FILLED
        assert order.is_filled is True

        order.state = OrderState.PARTIALLY_FILLED
        assert order.is_filled is False

    def test_is_rejected_property(self):
        """is_rejected property should check REJECTED state."""
        order = InternalOrder()
        assert order.is_rejected is False

        order.state = OrderState.REJECTED
        assert order.is_rejected is True


class TestCloseOrderHandling:
    """Tests for CLOSE signal handling in orders."""

    def test_is_close_order_with_close_signal(self):
        """is_close_order should be True for CLOSE signal type."""
        order = InternalOrder(signal_type=SignalType.CLOSE)
        assert order.is_close_order is True

    def test_is_close_order_with_buy_signal(self):
        """is_close_order should be False for BUY signal type."""
        order = InternalOrder(signal_type=SignalType.BUY)
        assert order.is_close_order is False

    def test_is_close_order_with_sell_signal(self):
        """is_close_order should be False for SELL signal type."""
        order = InternalOrder(signal_type=SignalType.SELL)
        assert order.is_close_order is False

    def test_is_close_order_with_no_signal(self):
        """is_close_order should be False when signal_type is None."""
        order = InternalOrder()
        assert order.signal_type is None
        assert order.is_close_order is False


class TestOrderRepr:
    """Tests for InternalOrder string representation."""

    def test_repr_basic(self):
        """repr should include key order information."""
        order = InternalOrder(
            account_id="test-account",
            symbol="EURUSD",
            action=OrderSide.BUY,
            volume=1.0,
        )
        repr_str = repr(order)
        assert "InternalOrder" in repr_str
        assert "test-account" in repr_str
        assert "EURUSD" in repr_str
        assert "BUY" in repr_str
        assert "1.0" in repr_str
        assert "pending" in repr_str

    def test_repr_order_id_truncated(self):
        """Order ID in repr should be truncated."""
        order = InternalOrder()
        repr_str = repr(order)
        # Should show first 8 chars + "..."
        assert "..." in repr_str
        assert order.order_id[:8] in repr_str
