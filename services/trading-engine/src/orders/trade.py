"""Trade record model.

This module defines the Trade model which represents a completed trade
for audit trail purposes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.adapters.zmq_models import OrderSide


@dataclass
class Trade:
    """Trade record for audit trail.

    Represents a completed trade with entry and optional exit information.
    Trades are created when orders are filled.

    Attributes:
        trade_id: Unique trade identifier (UUID)
        order_id: Order ID that opened/closed this trade
        account_id: Account the trade belongs to
        symbol: Trading symbol (e.g., "XAUUSD")
        side: Trade direction (BUY/SELL)
        quantity: Trade size (lot size)
        entry_price: Entry price
        entry_time: Entry timestamp
        exit_price: Exit price (if closed)
        exit_time: Exit timestamp (if closed)
        pnl_dollars: Profit/loss in dollars (if closed)
        pnl_percent: Profit/loss as percentage (if closed)
        slippage: Total slippage on entry and exit
    """

    # Required fields
    order_id: str
    account_id: str
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_time: datetime

    # Auto-generated UUID
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Exit fields (populated when trade is closed)
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl_dollars: Optional[float] = None
    pnl_percent: Optional[float] = None

    # Slippage tracking
    slippage: Optional[float] = None

    @property
    def is_closed(self) -> bool:
        """Check if trade has been closed."""
        return self.exit_price is not None

    @property
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return not self.is_closed

    @property
    def is_profitable(self) -> bool:
        """Check if trade is profitable (must be closed)."""
        if self.pnl_dollars is None:
            return False
        return self.pnl_dollars > 0

    @property
    def is_loss(self) -> bool:
        """Check if trade is a loss (must be closed)."""
        if self.pnl_dollars is None:
            return False
        return self.pnl_dollars < 0

    @property
    def duration(self) -> Optional[float]:
        """Get trade duration in seconds (if closed)."""
        if self.exit_time is None:
            return None
        delta = self.exit_time - self.entry_time
        return delta.total_seconds()

    def calculate_pnl(self, exit_price: float) -> tuple[float, float]:
        """Calculate PnL for a given exit price.

        Args:
            exit_price: The exit price

        Returns:
            Tuple of (pnl_dollars, pnl_percent)
        """
        price_diff = exit_price - self.entry_price
        if self.side == OrderSide.SELL:
            price_diff = -price_diff  # Short position

        pnl_dollars = price_diff * self.quantity
        pnl_percent = (price_diff / self.entry_price) * 100 if self.entry_price else 0

        return pnl_dollars, pnl_percent

    def close(
        self,
        exit_price: float,
        exit_time: Optional[datetime] = None,
        slippage: Optional[float] = None,
    ) -> None:
        """Close the trade with exit details.

        Args:
            exit_price: The exit price
            exit_time: Exit timestamp (defaults to now)
            slippage: Exit slippage to add to existing
        """
        self.exit_price = exit_price
        self.exit_time = exit_time or datetime.now(timezone.utc)
        self.pnl_dollars, self.pnl_percent = self.calculate_pnl(exit_price)

        # Add exit slippage to total
        if slippage is not None:
            if self.slippage is not None:
                self.slippage += slippage
            else:
                self.slippage = slippage

    def __repr__(self) -> str:
        """String representation of trade."""
        status = "CLOSED" if self.is_closed else "OPEN"
        pnl_str = f", PnL=${self.pnl_dollars:.2f}" if self.is_closed else ""
        return (
            f"Trade(id={self.trade_id[:8]}..., "
            f"{self.side.value} {self.symbol} "
            f"qty={self.quantity} @ {self.entry_price}, "
            f"status={status}{pnl_str})"
        )
