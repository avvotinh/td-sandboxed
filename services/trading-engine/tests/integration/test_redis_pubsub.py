"""Integration tests for Redis adapter pub/sub.

Tests cover:
- Real pub/sub round-trip with running Redis
- Bar publishing and receiving
- Subscription management with real Redis

These tests require a running Redis server:
- Set REDIS_AVAILABLE=true to run
- Or run: docker run -p 6379:6379 redis:7-alpine
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

# Skip all tests if Redis is not available
pytestmark = pytest.mark.integration


def redis_available() -> bool:
    """Check if Redis is available for testing."""
    return os.environ.get("REDIS_AVAILABLE", "").lower() == "true"


@pytest.fixture
def skip_without_redis():
    """Skip test if Redis is not available."""
    if not redis_available():
        pytest.skip("REDIS_AVAILABLE not set - skipping Redis integration tests")


class TestRedisAdapterIntegration:
    """Integration tests for RedisAdapter with real Redis."""

    @pytest.mark.asyncio
    async def test_connect_to_redis(self, skip_without_redis):
        """Test connecting to Redis server."""
        from src.adapters.redis_adapter import RedisAdapter

        adapter = RedisAdapter()
        await adapter.connect()

        assert adapter.is_connected is True

        await adapter.disconnect()
        assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_subscribe_to_channels(self, skip_without_redis):
        """Test subscribing to bar channels."""
        from src.adapters.redis_adapter import RedisAdapter

        async with RedisAdapter() as adapter:
            await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")

            assert adapter.get_subscription_count() == 2
            subs = adapter.get_subscriptions()
            assert "bars:XAUUSD:1m" in subs
            assert "bars:BTCUSD:1m" in subs

    @pytest.mark.asyncio
    async def test_unsubscribe_from_channels(self, skip_without_redis):
        """Test unsubscribing from bar channels."""
        from src.adapters.redis_adapter import RedisAdapter

        async with RedisAdapter() as adapter:
            await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
            await adapter.unsubscribe(["XAUUSD"], timeframe="1m")

            assert adapter.get_subscription_count() == 1
            subs = adapter.get_subscriptions()
            assert "bars:XAUUSD:1m" not in subs
            assert "bars:BTCUSD:1m" in subs

    @pytest.mark.asyncio
    async def test_pub_sub_round_trip(self, skip_without_redis):
        """Test full pub/sub round trip with bar data."""
        import redis.asyncio as redis

        from src.adapters.redis_adapter import RedisAdapter
        from src.adapters.redis_models import Bar

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="1m")

        # Publish test bar in background
        async def publisher():
            client = redis.from_url("redis://localhost:6379")
            await asyncio.sleep(0.1)  # Wait for subscription to be ready
            bar_json = Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.50,
                low=1849.80,
                close=1850.45,
                volume=1234.5,
            ).to_json()
            await client.publish("bars:XAUUSD:1m", bar_json)
            await client.aclose()

        publisher_task = asyncio.create_task(publisher())

        # Receive bar with timeout
        received_bar = None
        try:
            async for bar in adapter.listen_bars():
                received_bar = bar
                break
        except asyncio.TimeoutError:
            pytest.fail("Timeout waiting for bar")

        await publisher_task
        await adapter.disconnect()

        assert received_bar is not None
        assert received_bar.symbol == "XAUUSD"
        assert received_bar.timeframe == "1m"
        assert received_bar.close == 1850.45
        assert received_bar.volume == 1234.5

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, skip_without_redis):
        """Test receiving bars from multiple symbols."""
        import redis.asyncio as redis

        from src.adapters.redis_adapter import RedisAdapter
        from src.adapters.redis_models import Bar

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")

        received_symbols = set()

        async def publisher():
            client = redis.from_url("redis://localhost:6379")
            await asyncio.sleep(0.1)

            # Publish bars for both symbols
            for symbol, close_price in [("XAUUSD", 1850.00), ("BTCUSD", 45000.00)]:
                bar_json = Bar(
                    symbol=symbol,
                    timeframe="1m",
                    time=datetime.now(timezone.utc),
                    open=close_price - 10,
                    high=close_price + 10,
                    low=close_price - 20,
                    close=close_price,
                    volume=100,
                ).to_json()
                await client.publish(f"bars:{symbol}:1m", bar_json)

            await client.aclose()

        publisher_task = asyncio.create_task(publisher())

        # Receive bars with timeout
        timeout = asyncio.get_event_loop().time() + 2.0
        async for bar in adapter.listen_bars():
            received_symbols.add(bar.symbol)
            if len(received_symbols) >= 2:
                break
            if asyncio.get_event_loop().time() > timeout:
                break

        await publisher_task
        await adapter.disconnect()

        assert "XAUUSD" in received_symbols
        assert "BTCUSD" in received_symbols

    @pytest.mark.asyncio
    async def test_bar_callback(self, skip_without_redis):
        """Test bar callback is invoked."""
        import redis.asyncio as redis

        from src.adapters.redis_adapter import RedisAdapter
        from src.adapters.redis_models import Bar

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="1m")

        callback_bars = []

        def on_bar(bar: Bar):
            callback_bars.append(bar)

        adapter.set_bar_callback(on_bar)

        async def publisher():
            client = redis.from_url("redis://localhost:6379")
            await asyncio.sleep(0.1)
            bar_json = Bar(
                symbol="XAUUSD",
                timeframe="1m",
                time=datetime.now(timezone.utc),
                open=1850.00,
                high=1851.50,
                low=1849.80,
                close=1850.45,
                volume=100,
            ).to_json()
            await client.publish("bars:XAUUSD:1m", bar_json)
            await client.aclose()

        publisher_task = asyncio.create_task(publisher())

        # Receive bar
        async for bar in adapter.listen_bars():
            break

        await publisher_task
        await adapter.disconnect()

        assert len(callback_bars) == 1
        assert callback_bars[0].symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_context_manager(self, skip_without_redis):
        """Test async context manager with real Redis."""
        from src.adapters.redis_adapter import RedisAdapter

        async with RedisAdapter() as adapter:
            assert adapter.is_connected is True
            await adapter.subscribe(["XAUUSD"], timeframe="1m")
            assert adapter.get_subscription_count() == 1

        # After exiting context, should be disconnected
        assert adapter.is_connected is False
