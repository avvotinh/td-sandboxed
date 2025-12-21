"""Position tracker for managing open positions.

This module provides position tracking per account per symbol.
For MVP, positions are stored in memory with optional Redis persistence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.adapters.zmq_models import OrderSide
from src.orders.order import InternalOrder

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Open position for an account/symbol.

    Represents an open trading position with entry details.

    Attributes:
        account_id: Account the position belongs to
        symbol: Trading symbol
        side: Position direction (BUY = long, SELL = short)
        quantity: Position size
        entry_price: Average entry price
        entry_time: Entry timestamp
        order_id: Order ID that opened the position
    """

    account_id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_time: datetime
    order_id: str

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.side == OrderSide.BUY

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.side == OrderSide.SELL

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL at current price.

        Args:
            current_price: Current market price

        Returns:
            Unrealized PnL in dollars
        """
        price_diff = current_price - self.entry_price
        if self.is_short:
            price_diff = -price_diff
        return price_diff * self.quantity

    def __repr__(self) -> str:
        """String representation of position."""
        return (
            f"Position({self.side.value} {self.symbol} "
            f"qty={self.quantity} @ {self.entry_price}, "
            f"account={self.account_id})"
        )


class PositionTracker:
    """Track open positions per account per symbol.

    Provides position management for the trading engine.
    For MVP, only one position per account per symbol is supported.

    Usage:
        tracker = PositionTracker()

        # Open position from filled order
        position = tracker.open_position(filled_order)

        # Check position
        if tracker.has_position("account-1", "XAUUSD"):
            pos = tracker.get_position("account-1", "XAUUSD")

        # Close position
        closed = tracker.close_position("account-1", "XAUUSD")
    """

    def __init__(self) -> None:
        """Initialize the position tracker."""
        # Key: (account_id, symbol) -> Position
        self._positions: dict[tuple[str, str], Position] = {}

    def open_position(self, order: InternalOrder) -> Position:
        """Open a new position from a filled order.

        Args:
            order: The filled order to create position from

        Returns:
            The newly created Position

        Raises:
            ValueError: If position already exists for account/symbol
        """
        key = (order.account_id, order.symbol)

        if key in self._positions:
            raise ValueError(
                f"Position already exists for {order.account_id}/{order.symbol}. "
                "Close existing position before opening new one."
            )

        position = Position(
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.action,
            quantity=order.volume,
            entry_price=order.fill_price or order.price,
            entry_time=order.filled_at or datetime.now(timezone.utc),
            order_id=order.order_id,
        )

        self._positions[key] = position

        logger.info(
            "Position OPENED: %s %s %s qty=%.2f @ %.4f",
            order.account_id,
            order.action.value,
            order.symbol,
            order.volume,
            position.entry_price,
        )

        return position

    def close_position(
        self, account_id: str, symbol: str
    ) -> Optional[Position]:
        """Close and remove a position.

        Args:
            account_id: Account identifier
            symbol: Trading symbol

        Returns:
            The closed Position, or None if not found
        """
        key = (account_id, symbol)
        position = self._positions.pop(key, None)

        if position:
            logger.info(
                "Position CLOSED: %s %s %s qty=%.2f",
                account_id,
                position.side.value,
                symbol,
                position.quantity,
            )

        return position

    def get_position(
        self, account_id: str, symbol: str
    ) -> Optional[Position]:
        """Get current position for account/symbol.

        Args:
            account_id: Account identifier
            symbol: Trading symbol

        Returns:
            Position if exists, None otherwise
        """
        return self._positions.get((account_id, symbol))

    def has_position(self, account_id: str, symbol: str) -> bool:
        """Check if position exists.

        Args:
            account_id: Account identifier
            symbol: Trading symbol

        Returns:
            True if position exists
        """
        return (account_id, symbol) in self._positions

    def get_all_positions(self, account_id: Optional[str] = None) -> list[Position]:
        """Get all positions, optionally filtered by account.

        Args:
            account_id: Optional account filter

        Returns:
            List of positions
        """
        if account_id is None:
            return list(self._positions.values())
        return [
            pos
            for pos in self._positions.values()
            if pos.account_id == account_id
        ]

    def get_position_count(self, account_id: Optional[str] = None) -> int:
        """Get number of open positions.

        Args:
            account_id: Optional account filter

        Returns:
            Number of positions
        """
        if account_id is None:
            return len(self._positions)
        return sum(
            1
            for pos in self._positions.values()
            if pos.account_id == account_id
        )

    def clear(self) -> int:
        """Clear all positions (for testing/reset).

        Returns:
            Number of positions cleared
        """
        count = len(self._positions)
        self._positions.clear()
        return count

    def __len__(self) -> int:
        """Get total number of open positions."""
        return len(self._positions)

    def __repr__(self) -> str:
        """String representation of tracker."""
        return f"PositionTracker(positions={len(self._positions)})"
