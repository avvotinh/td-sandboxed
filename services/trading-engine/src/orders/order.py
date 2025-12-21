"""Internal order model with state tracking.

This module defines the InternalOrder model which tracks the complete lifecycle
of an order from creation through execution.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.orders.signal import SignalType

from src.adapters.zmq_models import OrderSide


class OrderState(str, Enum):
    """Order execution state.

    States:
        PENDING: Created, not yet sent to mt5-bridge
        SUBMITTED: Sent to mt5-bridge, awaiting result
        FILLED: Fully executed
        PARTIALLY_FILLED: Partial execution (not fully supported in MVP)
        REJECTED: Rejected by broker
        CANCELLED: Cancelled before fill
        ERROR: System error during execution
    """

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ERROR = "error"

    def is_terminal(self) -> bool:
        """Check if this is a terminal state.

        Terminal states are final - no further transitions allowed.
        """
        return self in (
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.ERROR,
        )


# Valid state transitions for order lifecycle
_VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PENDING: {
        OrderState.SUBMITTED,
        OrderState.CANCELLED,
        OrderState.ERROR,
    },
    OrderState.SUBMITTED: {
        OrderState.FILLED,
        OrderState.PARTIALLY_FILLED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.ERROR,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.ERROR,
    },
    # Terminal states have no valid transitions
    OrderState.FILLED: set(),
    OrderState.REJECTED: set(),
    OrderState.CANCELLED: set(),
    OrderState.ERROR: set(),
}


@dataclass
class InternalOrder:
    """Internal order representation with state tracking.

    Tracks the complete lifecycle of an order from creation through execution.
    Each order has a unique UUID for idempotency checking.

    Attributes:
        order_id: Unique order identifier (UUID)
        account_id: Account to execute on
        symbol: Trading symbol (e.g., "XAUUSD")
        action: Order side (BUY/SELL)
        volume: Lot size
        price: Requested execution price
        sl: Stop loss price (optional)
        tp: Take profit price (optional)
        signal_type: Original signal type (BUY/SELL/CLOSE)
        state: Current order state
        created_at: Order creation time
        submitted_at: Time order was sent to bridge
        filled_at: Time order was filled
        fill_price: Actual fill price
        slippage: Price slippage from requested
        rejection_reason: Reason for rejection (if rejected)
        filled_quantity: Quantity filled (for partial fills)
    """

    # Required fields
    account_id: str = ""
    symbol: str = ""
    action: OrderSide = OrderSide.BUY
    volume: float = 0.0
    price: float = 0.0

    # Optional fields
    sl: Optional[float] = None
    tp: Optional[float] = None

    # Auto-generated UUID for idempotency
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Signal context - CRITICAL for CLOSE handling
    signal_type: Optional[SignalType] = None

    # State tracking
    state: OrderState = OrderState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    # Execution details
    fill_price: Optional[float] = None
    slippage: Optional[float] = None
    rejection_reason: Optional[str] = None
    filled_quantity: float = 0.0  # For partial fills

    @property
    def is_close_order(self) -> bool:
        """Check if this order is closing a position."""
        # Import here to avoid circular import
        from src.orders.signal import SignalType

        return self.signal_type == SignalType.CLOSE

    @property
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state."""
        return self.state.is_terminal()

    @property
    def is_filled(self) -> bool:
        """Check if order was filled."""
        return self.state == OrderState.FILLED

    @property
    def is_rejected(self) -> bool:
        """Check if order was rejected."""
        return self.state == OrderState.REJECTED

    def can_transition_to(self, new_state: OrderState) -> bool:
        """Check if state transition is valid.

        Args:
            new_state: Target state

        Returns:
            True if transition is valid
        """
        return new_state in _VALID_TRANSITIONS.get(self.state, set())

    def transition_to(self, new_state: OrderState) -> None:
        """Transition to new state with validation.

        Args:
            new_state: Target state

        Raises:
            ValueError: If transition is invalid
        """
        if not self.can_transition_to(new_state):
            raise ValueError(
                f"Invalid state transition: {self.state.value} -> {new_state.value}"
            )
        self.state = new_state

    def __repr__(self) -> str:
        """String representation of order."""
        return (
            f"InternalOrder(id={self.order_id[:8]}..., "
            f"account={self.account_id}, "
            f"symbol={self.symbol}, "
            f"action={self.action.value}, "
            f"volume={self.volume}, "
            f"state={self.state.value})"
        )
