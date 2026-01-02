"""ZeroMQ data models for mt5-bridge communication.

This module defines the data models for:
- Tick: Market tick data from mt5-bridge
- Order: Order command to mt5-bridge
- OrderResult: Order execution result from mt5-bridge
- MT5Position: Position data from MT5 for reconciliation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
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


@dataclass
class MT5Position:
    """Position data from MT5 via mt5-bridge.

    Used for position reconciliation during crash recovery.
    MT5 positions are ALWAYS the source of truth.

    Attributes:
        ticket: MT5 position ticket number
        symbol: Trading symbol (e.g., "XAUUSD")
        side: Position direction ("BUY" or "SELL")
        volume: Position size in lots
        entry_price: Price at which position was opened
        entry_time: ISO8601 timestamp of position entry
        current_price: Current market price
        profit: Current unrealized profit
        swap: Accumulated swap charges
        commission: Commission paid
    """

    ticket: int
    symbol: str
    side: str  # "BUY" or "SELL"
    volume: Decimal
    entry_price: Decimal
    entry_time: str  # ISO8601
    current_price: Decimal
    profit: Decimal
    swap: Decimal
    commission: Decimal

    @classmethod
    def from_dict(cls, data: dict) -> MT5Position:
        """Create MT5Position from dictionary.

        Handles type conversion from JSON payload.

        Args:
            data: Dictionary with position data from mt5-bridge

        Returns:
            MT5Position instance
        """
        return cls(
            ticket=int(data["ticket"]),
            symbol=str(data["symbol"]),
            side=str(data["side"]),
            volume=Decimal(str(data["volume"])),
            entry_price=Decimal(str(data["entry_price"])),
            entry_time=str(data["entry_time"]),
            current_price=Decimal(str(data["current_price"])),
            profit=Decimal(str(data["profit"])),
            swap=Decimal(str(data["swap"])),
            commission=Decimal(str(data["commission"])),
        )
