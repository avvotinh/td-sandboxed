"""Redis adapter for market data subscription.

This module provides async pub/sub subscription to bar channels from tv-api:
- Subscribe to bar channels by symbol/timeframe
- Receive and parse OHLCV bar data
- Automatic reconnection with exponential backoff

Channel pattern: bars:{symbol}:{timeframe}
Example: bars:XAUUSD:1m, bars:BTCUSD:5m

Example:
    async with RedisAdapter() as adapter:
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
        async for bar in adapter.listen_bars():
            print(f"Bar: {bar.symbol} close={bar.close}")
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Union

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError

from .redis_config import RedisConfig
from .redis_models import Bar

if TYPE_CHECKING:
    from redis.asyncio.client import PubSub

logger = logging.getLogger(__name__)

# Type alias for bar callback - supports both sync and async callbacks
BarCallback = Union[Callable[[Bar], None], Callable[[Bar], Awaitable[None]]]


class MaxReconnectAttemptsError(Exception):
    """Raised when maximum reconnection attempts exceeded."""

    pass


@dataclass
class _ConnectionState:
    """Connection state tracking (internal use only)."""

    connected: bool = False
    connecting: bool = False
    last_error: str | None = None


class RedisAdapter:
    """Redis adapter for market data subscription.

    Provides pub/sub subscription to bar channels from tv-api:
    - Subscribe to bar channels by symbol/timeframe
    - Receive and parse OHLCV bar data
    - Automatic reconnection with exponential backoff

    Attributes:
        config: Redis configuration
        is_connected: Whether adapter is connected

    Example:
        async with RedisAdapter() as adapter:
            await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
            async for bar in adapter.listen_bars():
                print(f"Bar: {bar.symbol} close={bar.close}")
    """

    def __init__(self, config: RedisConfig | None = None):
        """Initialize Redis adapter.

        Args:
            config: Redis configuration. Uses defaults if not provided.
        """
        self.config = config or RedisConfig()
        self._client: redis.Redis | None = None
        self._pubsub: PubSub | None = None
        self._state = _ConnectionState()
        self._subscriptions: set[str] = set()
        self._reconnect_attempt = 0
        self._on_bar_callback: BarCallback | None = None

    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._state.connected

    async def connect(self) -> None:
        """Connect to Redis server.

        Creates Redis client and pub/sub instance for subscriptions.

        Raises:
            redis.exceptions.ConnectionError: If connection fails

        Note:
            For production with high throughput, consider using ConnectionPool:
            pool = redis.ConnectionPool.from_url(url, max_connections=20)
            self._client = redis.Redis(connection_pool=pool)
        """
        if self._state.connected:
            return

        self._state.connecting = True
        try:
            self._client = redis.from_url(
                self.config.redis_url,
                decode_responses=True,  # Auto-decode bytes to str
            )

            # Test connection
            await self._client.ping()

            # Create pub/sub instance
            self._pubsub = self._client.pubsub(ignore_subscribe_messages=True)

            self._state.connected = True
            self._state.last_error = None
            self._reconnect_attempt = 0

            logger.info("Redis connected to %s", self.config.redis_url)

        except RedisConnectionError as e:
            self._state.last_error = str(e)
            logger.error("Failed to connect to Redis: %s", e)
            raise
        finally:
            self._state.connecting = False

    async def disconnect(self) -> None:
        """Disconnect and cleanup.

        Closes pub/sub and Redis client gracefully.
        """
        self._state.connected = False

        if self._pubsub:
            try:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            except Exception as e:
                logger.warning("Error closing pubsub: %s", e)
            self._pubsub = None

        if self._client:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning("Error closing Redis client: %s", e)
            self._client = None

        logger.info("Redis adapter disconnected")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Uses configured reconnect_delays sequence.
        Re-subscribes to all previous channels after successful reconnect.

        Raises:
            MaxReconnectAttemptsError: If max_reconnect_attempts exceeded (when > 0)
        """
        # Check max attempts limit (0 = unlimited)
        if (
            self.config.max_reconnect_attempts > 0
            and self._reconnect_attempt >= self.config.max_reconnect_attempts
        ):
            raise MaxReconnectAttemptsError(
                f"Maximum reconnection attempts ({self.config.max_reconnect_attempts}) exceeded"
            )

        delay_idx = min(
            self._reconnect_attempt, len(self.config.reconnect_delays) - 1
        )
        delay = self.config.reconnect_delays[delay_idx]

        logger.warning(
            "Redis reconnecting in %d seconds (attempt %d/%s)",
            delay,
            self._reconnect_attempt + 1,
            self.config.max_reconnect_attempts or "unlimited",
        )

        await asyncio.sleep(delay)
        self._reconnect_attempt += 1

        await self.disconnect()
        await self.connect()

        # Re-subscribe to all previous channels
        if self._subscriptions and self._pubsub:
            await self._pubsub.subscribe(*self._subscriptions)
            logger.info(
                "Re-subscribed to %d channels after reconnect",
                len(self._subscriptions),
            )

    async def subscribe(
        self,
        symbols: list[str],
        timeframe: str = "1m",
    ) -> None:
        """Subscribe to bar channels for given symbols.

        Creates channel subscriptions in format: bars:{symbol}:{timeframe}

        Args:
            symbols: List of symbols (e.g., ["XAUUSD", "BTCUSD"])
            timeframe: Bar timeframe (default "1m")

        Raises:
            RuntimeError: If not connected

        Example:
            await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
            # Subscribes to bars:XAUUSD:1m, bars:BTCUSD:1m
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        channels = [f"bars:{symbol}:{timeframe}" for symbol in symbols]

        await self._pubsub.subscribe(*channels)
        self._subscriptions.update(channels)

        logger.info(
            "Subscribed to %d bar channels: %s",
            len(channels),
            ", ".join(channels),
        )

    async def unsubscribe(
        self,
        symbols: list[str],
        timeframe: str = "1m",
    ) -> None:
        """Unsubscribe from bar channels.

        Args:
            symbols: List of symbols to unsubscribe
            timeframe: Bar timeframe

        Raises:
            RuntimeError: If not connected
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        channels = [f"bars:{symbol}:{timeframe}" for symbol in symbols]

        await self._pubsub.unsubscribe(*channels)
        self._subscriptions.difference_update(channels)

        logger.info("Unsubscribed from %d channels", len(channels))

    async def listen_bars(self) -> AsyncIterator[Bar]:
        """Async generator yielding Bar objects from subscribed channels.

        Handles connection errors by attempting reconnection with backoff.
        Malformed messages are logged and skipped (not raised).

        Yields:
            Bar: Parsed OHLCV bar data

        Raises:
            RuntimeError: If not connected
            MaxReconnectAttemptsError: If max reconnection attempts exceeded

        Example:
            async for bar in adapter.listen_bars():
                print(f"{bar.symbol}: close={bar.close}")
        """
        if not self._pubsub:
            raise RuntimeError("Not connected - call connect() first")

        # Calculate timeout: 0 ms = None (block forever), otherwise convert to seconds
        # Use minimum of 1.0 second to allow cancellation checks
        timeout = (
            max(self.config.recv_timeout_ms / 1000.0, 1.0)
            if self.config.recv_timeout_ms > 0
            else 1.0
        )

        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=timeout,
                )

                if message is None:
                    continue

                if message["type"] != "message":
                    continue

                try:
                    bar = Bar.from_json(message["data"])

                    # Optional callback for routing (supports sync and async)
                    if self._on_bar_callback:
                        if inspect.iscoroutinefunction(self._on_bar_callback):
                            await self._on_bar_callback(bar)
                        else:
                            self._on_bar_callback(bar)

                    yield bar

                except (json.JSONDecodeError, ValueError) as e:
                    # Truncate long messages for logging
                    data_preview = str(message["data"])[:100]
                    logger.warning(
                        "Failed to parse bar: %s - %s",
                        e,
                        data_preview,
                    )

            except RedisConnectionError as e:
                logger.error("Redis connection error: %s", e)
                # Reconnect can raise MaxReconnectAttemptsError - let it propagate
                await self.reconnect()

    def set_bar_callback(
        self,
        callback: BarCallback | None,
    ) -> None:
        """Set callback for bar routing (used by signal router).

        This is an integration point for Story 2.9 signal filtering.
        The callback is invoked for each received bar before yielding.
        Supports both sync and async callbacks.

        Args:
            callback: Function to call for each received bar, or None to clear.
                      Can be sync (Callable[[Bar], None]) or async (Callable[[Bar], Awaitable[None]])
        """
        self._on_bar_callback = callback

    def get_subscription_count(self) -> int:
        """Get count of active channel subscriptions.

        Returns:
            Number of subscribed channels
        """
        return len(self._subscriptions)

    def get_subscriptions(self) -> set[str]:
        """Get copy of active channel subscriptions.

        Returns:
            Set of subscribed channel names
        """
        return self._subscriptions.copy()

    async def __aenter__(self) -> "RedisAdapter":
        """Async context manager entry - connect."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnect."""
        await self.disconnect()
