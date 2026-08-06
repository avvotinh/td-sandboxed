"""Redis data models for market data subscription.

This module defines Pydantic models for Redis pub/sub messages:
- Bar: OHLCV bar data from tv-api via Redis

Bar messages are published to channels: bars:{symbol}:{timeframe}
Example: bars:XAUUSD:1m
"""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class Bar(BaseModel):
    """OHLCV bar data from Redis pub/sub.

    Represents a single candlestick/bar with open, high, low, close prices
    and volume. Published by tv-api to Redis channels.

    Attributes:
        symbol: Trading symbol (e.g., "XAUUSD")
        timeframe: Bar timeframe (e.g., "1m", "5m", "1h")
        time: Bar timestamp (close time)
        open: Opening price
        high: Highest price in period
        low: Lowest price in period
        close: Closing price
        volume: Trading volume

    Example:
        bar = Bar(
            symbol="XAUUSD",
            timeframe="1m",
            time=datetime.now(timezone.utc),
            open=1850.00,
            high=1851.50,
            low=1849.80,
            close=1850.45,
            volume=1234.5
        )
        print(bar.channel_name)  # "bars:XAUUSD:1m"
    """

    symbol: str = Field(..., min_length=1, description="Trading symbol")
    timeframe: str = Field(..., min_length=1, description="Bar timeframe")
    time: datetime = Field(..., description="Bar timestamp")
    open: float = Field(..., gt=0, description="Opening price")
    high: float = Field(..., gt=0, description="Highest price")
    low: float = Field(..., gt=0, description="Lowest price")
    close: float = Field(..., gt=0, description="Closing price")
    volume: float = Field(..., ge=0, description="Trading volume")

    @model_validator(mode="after")
    def validate_high_low(self) -> "Bar":
        """Validate high >= low."""
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self

    @field_validator("symbol", "timeframe")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip whitespace from string fields."""
        return v.strip()

    @classmethod
    def from_json(cls, data: str | bytes) -> "Bar":
        """Parse Bar from JSON string or bytes.

        Args:
            data: JSON string or bytes from Redis message

        Returns:
            Parsed Bar instance

        Raises:
            ValueError: If JSON is invalid or missing required fields
            json.JSONDecodeError: If JSON parsing fails

        Example:
            json_data = '{"symbol":"XAUUSD","timeframe":"1m",...}'
            bar = Bar.from_json(json_data)
        """
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        parsed = json.loads(data)
        return cls(**parsed)

    @property
    def channel_name(self) -> str:
        """Get Redis channel name for this bar.

        Returns:
            Channel name in format "bars:{symbol}:{timeframe}"

        Example:
            bar.channel_name  # "bars:XAUUSD:1m"
        """
        return f"bars:{self.symbol}:{self.timeframe}"

    def to_json(self) -> str:
        """Serialize bar to JSON string.

        Returns:
            JSON string representation
        """
        return self.model_dump_json()
