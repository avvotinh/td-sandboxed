"""ZeroMQ data models for mt5-bridge communication.

This module defines the data models for:
- Tick: Market tick data from mt5-bridge
- Order: Order command to mt5-bridge
- OrderResult: Order execution result from mt5-bridge
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OrderSide(str, Enum):
    """Order direction."""

    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    """Order execution status."""

    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass
class Tick:
    """Market tick data from mt5-bridge.

    Attributes:
        account_id: Account identifier for routing (non-empty)
        symbol: Trading symbol (e.g., "XAUUSD") (non-empty)
        bid: Bid price (must be positive)
        ask: Ask price (must be positive, >= bid)
        timestamp: ISO format timestamp (non-empty)
    """

    account_id: str
    symbol: str
    bid: float
    ask: float
    timestamp: str  # ISO format: "2025-12-22T10:00:00.123Z"

    def __post_init__(self) -> None:
        """Validate tick data after initialization."""
        if not self.account_id:
            raise ValueError("account_id must not be empty")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        if self.bid <= 0:
            raise ValueError("bid must be positive")
        if self.ask <= 0:
            raise ValueError("ask must be positive")
        if self.ask < self.bid:
            raise ValueError("ask must be >= bid")
        if not self.timestamp:
            raise ValueError("timestamp must not be empty")

    @property
    def spread(self) -> float:
        """Calculate spread in price units."""
        return self.ask - self.bid

    @property
    def mid(self) -> float:
        """Calculate mid price."""
        return (self.bid + self.ask) / 2

    @property
    def timestamp_dt(self) -> datetime:
        """Parse timestamp to datetime object."""
        return datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))


class Order(BaseModel):
    """Order command to mt5-bridge.

    Attributes:
        type: Message type (always "order")
        account_id: Account to execute on
        action: Buy or Sell
        symbol: Trading symbol
        volume: Lot size (must be positive)
        price: Requested price (must be positive)
        sl: Stop loss price (optional)
        tp: Take profit price (optional)
        order_id: Unique order identifier
    """

    type: str = Field(default="order", frozen=True)
    account_id: str = Field(..., min_length=1)
    action: OrderSide
    symbol: str = Field(..., min_length=1)
    volume: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    sl: Optional[float] = Field(default=None, gt=0)
    tp: Optional[float] = Field(default=None, gt=0)
    order_id: str = Field(..., min_length=1)

    @field_validator("sl", "tp", mode="before")
    @classmethod
    def validate_optional_prices(cls, v: float | None) -> float | None:
        """Validate optional price fields are positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("Price must be positive")
        return v


@dataclass
class OrderResult:
    """Order execution result from mt5-bridge.

    Attributes:
        order_id: Order identifier for correlation
        status: Execution status
        fill_price: Actual fill price (if filled)
        slippage: Price slippage from requested
        timestamp: Execution timestamp
        error: Error message (if rejected/error)
    """

    order_id: str
    status: OrderStatus
    fill_price: Optional[float] = None
    slippage: Optional[float] = None
    timestamp: str = ""
    error: Optional[str] = None

    @property
    def is_filled(self) -> bool:
        """Check if order was filled."""
        return self.status == OrderStatus.FILLED

    @property
    def is_rejected(self) -> bool:
        """Check if order was rejected or errored."""
        return self.status in (OrderStatus.REJECTED, OrderStatus.ERROR)
