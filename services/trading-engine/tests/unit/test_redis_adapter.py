"""Unit tests for Redis adapter.

Tests cover:
- RedisAdapter connection management
- Subscription management
- Bar listening with mocked Redis
- Reconnection logic with exponential backoff
- Context manager support
- Bar callback handling
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.redis_adapter import RedisAdapter, _ConnectionState
from src.adapters.redis_config import RedisConfig
from src.adapters.redis_models import Bar


class TestConnectionState:
    """Tests for _ConnectionState dataclass (internal)."""

    def test_default_state(self):
        """Test default connection state."""
        state = _ConnectionState()
        assert state.connected is False
        assert state.connecting is False
        assert state.last_error is None

    def test_state_with_error(self):
        """Test state with error."""
        state = _ConnectionState(connected=False, last_error="Connection refused")
        assert state.last_error == "Connection refused"


class TestRedisAdapterInit:
    """Tests for RedisAdapter initialization."""

    def test_adapter_not_connected_by_default(self):
        """Test adapter is not connected by default."""
        adapter = RedisAdapter()
        assert adapter.is_connected is False

    def test_adapter_default_config(self):
        """Test adapter uses default config."""
        adapter = RedisAdapter()
        assert adapter.config.redis_url == "redis://localhost:6379"

    def test_adapter_custom_config(self):
        """Test adapter with custom config."""
        config = RedisConfig(redis_url="redis://custom-host:6380")
        adapter = RedisAdapter(config=config)
        assert adapter.config.redis_url == "redis://custom-host:6380"

    def test_adapter_empty_subscriptions(self):
        """Test adapter has no subscriptions by default."""
        adapter = RedisAdapter()
        assert adapter.get_subscription_count() == 0
        assert adapter.get_subscriptions() == set()


class TestRedisAdapterSubscription:
    """Tests for RedisAdapter subscription management."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client and pubsub."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client
            yield mock, mock_client, mock_pubsub

    @pytest.mark.asyncio
    async def test_subscribe_creates_channels(self, mock_redis):
        """Test subscribe creates correct channel names."""
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")

        mock_pubsub.subscribe.assert_called_once()
        call_args = mock_pubsub.subscribe.call_args[0]
        assert "bars:XAUUSD:1m" in call_args
        assert "bars:BTCUSD:1m" in call_args

    @pytest.mark.asyncio
    async def test_subscribe_updates_subscription_count(self, mock_redis):
        """Test subscribe updates subscription count."""
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()

        assert adapter.get_subscription_count() == 0
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
        assert adapter.get_subscription_count() == 2

    @pytest.mark.asyncio
    async def test_subscribe_different_timeframes(self, mock_redis):
        """Test subscribe with different timeframes."""
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="5m")

        call_args = mock_pubsub.subscribe.call_args[0]
        assert "bars:XAUUSD:5m" in call_args

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_channels(self, mock_redis):
        """Test unsubscribe removes channels."""
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD", "BTCUSD"], timeframe="1m")
        await adapter.unsubscribe(["XAUUSD"], timeframe="1m")

        assert adapter.get_subscription_count() == 1
        subscriptions = adapter.get_subscriptions()
        assert "bars:XAUUSD:1m" not in subscriptions
        assert "bars:BTCUSD:1m" in subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_not_connected_raises(self):
        """Test subscribe raises when not connected."""
        adapter = RedisAdapter()

        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.subscribe(["XAUUSD"])

    @pytest.mark.asyncio
    async def test_unsubscribe_not_connected_raises(self):
        """Test unsubscribe raises when not connected."""
        adapter = RedisAdapter()

        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.unsubscribe(["XAUUSD"])

    @pytest.mark.asyncio
    async def test_get_subscriptions_returns_copy(self, mock_redis):
        """Test get_subscriptions returns copy of set."""
        _, mock_client, mock_pubsub = mock_redis

        adapter = RedisAdapter()
        await adapter.connect()
        await adapter.subscribe(["XAUUSD"], timeframe="1m")

        subs1 = adapter.get_subscriptions()
        subs2 = adapter.get_subscriptions()

        # Should be equal but not the same object
        assert subs1 == subs2
        assert subs1 is not adapter._subscriptions


class TestRedisAdapterReconnection:
    """Tests for RedisAdapter reconnection logic."""

    def test_reconnect_delays_from_config(self):
        """Test reconnect delays come from config."""
        config = RedisConfig(reconnect_delays=[0, 1, 2])
        adapter = RedisAdapter(config=config)
        assert adapter.config.reconnect_delays == [0, 1, 2]

    def test_reconnect_delay_calculation_first(self):
        """Test first reconnect delay."""
        adapter = RedisAdapter()
        adapter._reconnect_attempt = 0
        delays = adapter.config.reconnect_delays
        delay_idx = min(adapter._reconnect_attempt, len(delays) - 1)
        delay = delays[delay_idx]
        assert delay == 1

    def test_reconnect_delay_calculation_fourth(self):
        """Test fourth reconnect delay is 8 seconds."""
        adapter = RedisAdapter()
        adapter._reconnect_attempt = 3
        delays = adapter.config.reconnect_delays
        delay_idx = min(adapter._reconnect_attempt, len(delays) - 1)
        delay = delays[delay_idx]
        assert delay == 8

    def test_reconnect_delay_calculation_max(self):
        """Test max reconnect delay is 30 seconds."""
        adapter = RedisAdapter()
        adapter._reconnect_attempt = 100
        delays = adapter.config.reconnect_delays
        delay_idx = min(adapter._reconnect_attempt, len(delays) - 1)
        delay = delays[delay_idx]
        assert delay == 30

    @pytest.mark.asyncio
    async def test_reconnect_resubscribes(self):
        """Test reconnect re-subscribes to all channels."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            config = RedisConfig(reconnect_delays=[0])  # No delay for test
            adapter = RedisAdapter(config=config)
            await adapter.connect()
            await adapter.subscribe(["XAUUSD"], timeframe="1m")

            # Simulate reconnect
            await adapter.reconnect()

            # Should have subscribed twice (initial + reconnect)
            assert mock_pubsub.subscribe.call_count == 2


class TestRedisAdapterListenBars:
    """Tests for RedisAdapter listen_bars method."""

    @pytest.mark.asyncio
    async def test_listen_bars_not_connected_raises(self):
        """Test listen_bars raises when not connected."""
        adapter = RedisAdapter()

        with pytest.raises(RuntimeError, match="Not connected"):
            async for _ in adapter.listen_bars():
                pass

    @pytest.mark.asyncio
    async def test_listen_bars_yields_bar(self):
        """Test listen_bars yields parsed Bar objects."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()
            await adapter.subscribe(["XAUUSD"], timeframe="1m")

            # Mock receiving a bar message
            bar_json = json.dumps({
                "symbol": "XAUUSD",
                "timeframe": "1m",
                "time": "2025-12-03T14:32:00Z",
                "open": 1850.00,
                "high": 1851.50,
                "low": 1849.80,
                "close": 1850.45,
                "volume": 1234.5,
            })

            mock_pubsub.get_message = AsyncMock(
                return_value={"type": "message", "data": bar_json}
            )

            # Get first bar
            bar = None
            async for b in adapter.listen_bars():
                bar = b
                break

            assert bar is not None
            assert bar.symbol == "XAUUSD"
            assert bar.close == 1850.45

    @pytest.mark.asyncio
    async def test_listen_bars_skips_non_message_types(self):
        """Test listen_bars skips subscribe/unsubscribe messages."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            call_count = 0

            async def mock_get_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Subscribe confirmation - should be skipped
                    return {"type": "subscribe", "data": 1}
                # Return valid bar
                return {
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }

            mock_pubsub.get_message = mock_get_message

            bar = None
            async for b in adapter.listen_bars():
                bar = b
                break

            assert call_count == 2  # First was skipped, second yielded
            assert bar.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_listen_bars_handles_invalid_json(self):
        """Test listen_bars handles invalid JSON gracefully."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            call_count = 0

            async def mock_get_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Invalid JSON - should be logged and skipped
                    return {"type": "message", "data": "not valid json"}
                # Return valid bar
                return {
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }

            mock_pubsub.get_message = mock_get_message

            bar = None
            async for b in adapter.listen_bars():
                bar = b
                break

            assert call_count == 2  # First was skipped, second yielded
            assert bar.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_listen_bars_handles_validation_error(self):
        """Test listen_bars handles bar validation errors."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            call_count = 0

            async def mock_get_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # Invalid bar (high < low) - should be logged and skipped
                    return {
                        "type": "message",
                        "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1849.00,"low":1850.00,"close":1850.00,"volume":100}',
                    }
                # Return valid bar
                return {
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }

            mock_pubsub.get_message = mock_get_message

            bar = None
            async for b in adapter.listen_bars():
                bar = b
                break

            assert call_count == 2  # First was skipped, second yielded
            assert bar.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_listen_bars_continues_on_none_message(self):
        """Test listen_bars continues when get_message returns None."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            call_count = 0

            async def mock_get_message(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    return None  # Timeout - continue
                return {
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }

            mock_pubsub.get_message = mock_get_message

            bar = None
            async for b in adapter.listen_bars():
                bar = b
                break

            assert call_count == 3  # Two None returns, then bar
            assert bar.symbol == "XAUUSD"


class TestRedisAdapterBarCallback:
    """Tests for RedisAdapter bar callback functionality."""

    @pytest.mark.asyncio
    async def test_bar_callback_invoked(self):
        """Test bar callback is invoked for each bar."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            # Set up callback
            callback_bars = []

            def on_bar(bar: Bar):
                callback_bars.append(bar)

            adapter.set_bar_callback(on_bar)

            # Mock bar message
            mock_pubsub.get_message = AsyncMock(
                return_value={
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }
            )

            # Get one bar
            async for _ in adapter.listen_bars():
                break

            assert len(callback_bars) == 1
            assert callback_bars[0].symbol == "XAUUSD"

    def test_set_bar_callback_none(self):
        """Test clearing bar callback."""
        adapter = RedisAdapter()
        adapter.set_bar_callback(lambda b: None)
        assert adapter._on_bar_callback is not None

        adapter.set_bar_callback(None)
        assert adapter._on_bar_callback is None


class TestRedisAdapterContextManager:
    """Tests for RedisAdapter async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_and_disconnects(self):
        """Test async context manager connects and disconnects."""
        with patch.object(
            RedisAdapter, "connect", new_callable=AsyncMock
        ) as mock_connect:
            with patch.object(
                RedisAdapter, "disconnect", new_callable=AsyncMock
            ) as mock_disconnect:
                async with RedisAdapter() as adapter:
                    assert adapter is not None

                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_returns_adapter(self):
        """Test context manager returns adapter instance."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            async with RedisAdapter() as adapter:
                assert isinstance(adapter, RedisAdapter)
                assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_context_manager_disconnects_on_exception(self):
        """Test context manager disconnects even on exception."""
        with patch.object(
            RedisAdapter, "connect", new_callable=AsyncMock
        ) as mock_connect:
            with patch.object(
                RedisAdapter, "disconnect", new_callable=AsyncMock
            ) as mock_disconnect:
                with pytest.raises(RuntimeError):
                    async with RedisAdapter():
                        raise RuntimeError("Test exception")

                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()


class TestRedisAdapterConnection:
    """Tests for RedisAdapter connection management."""

    @pytest.mark.asyncio
    async def test_connect_sets_connected_state(self):
        """Test connect sets is_connected to True."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            assert adapter.is_connected is False

            await adapter.connect()
            assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_resets_reconnect_attempt(self):
        """Test connect resets reconnect attempt counter."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            adapter._reconnect_attempt = 5

            await adapter.connect()
            assert adapter._reconnect_attempt == 0

    @pytest.mark.asyncio
    async def test_connect_already_connected_is_noop(self):
        """Test connect when already connected is no-op."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()
            await adapter.connect()  # Second call should be no-op

            # from_url should only be called once
            mock.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_clears_connected_state(self):
        """Test disconnect clears is_connected."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            # pubsub() is a synchronous method in redis.asyncio
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()
            assert adapter.is_connected is True

            await adapter.disconnect()
            assert adapter.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self):
        """Test disconnect when not connected is safe."""
        adapter = RedisAdapter()
        # Should not raise
        await adapter.disconnect()
        assert adapter.is_connected is False


class TestRedisAdapterMaxReconnectAttempts:
    """Tests for RedisAdapter max reconnect attempts."""

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts_raises_error(self):
        """Test max_reconnect_attempts raises MaxReconnectAttemptsError."""
        from src.adapters.redis_adapter import MaxReconnectAttemptsError

        config = RedisConfig(reconnect_delays=[0], max_reconnect_attempts=2)
        adapter = RedisAdapter(config=config)
        adapter._reconnect_attempt = 2  # Already at limit

        with pytest.raises(MaxReconnectAttemptsError, match="Maximum reconnection attempts"):
            await adapter.reconnect()

    @pytest.mark.asyncio
    async def test_max_reconnect_attempts_zero_is_unlimited(self):
        """Test max_reconnect_attempts=0 means unlimited."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            config = RedisConfig(reconnect_delays=[0], max_reconnect_attempts=0)
            adapter = RedisAdapter(config=config)
            adapter._reconnect_attempt = 100  # High number

            # Should not raise even with 100 attempts (0 = unlimited)
            # Note: successful connect() resets _reconnect_attempt to 0
            await adapter.reconnect()
            # After successful reconnect, counter is reset to 0
            assert adapter._reconnect_attempt == 0
            assert adapter.is_connected is True


class TestRedisAdapterAsyncCallback:
    """Tests for RedisAdapter async callback support."""

    @pytest.mark.asyncio
    async def test_async_callback_invoked(self):
        """Test async callback is properly awaited."""
        with patch("src.adapters.redis_adapter.redis") as mock:
            mock_client = AsyncMock()
            mock_pubsub = AsyncMock()
            mock_client.pubsub = MagicMock(return_value=mock_pubsub)
            mock.from_url.return_value = mock_client

            adapter = RedisAdapter()
            await adapter.connect()

            # Set up async callback
            callback_bars = []

            async def on_bar(bar: Bar):
                await asyncio.sleep(0)  # Simulate async operation
                callback_bars.append(bar)

            adapter.set_bar_callback(on_bar)

            # Mock bar message
            mock_pubsub.get_message = AsyncMock(
                return_value={
                    "type": "message",
                    "data": '{"symbol":"XAUUSD","timeframe":"1m","time":"2025-12-03T14:32:00Z","open":1850.00,"high":1851.50,"low":1849.80,"close":1850.45,"volume":100}',
                }
            )

            # Get one bar
            async for _ in adapter.listen_bars():
                break

            assert len(callback_bars) == 1
            assert callback_bars[0].symbol == "XAUUSD"


class TestRedisAdapterTimeoutConfig:
    """Tests for RedisAdapter timeout configuration."""

    def test_recv_timeout_ms_default(self):
        """Test default recv_timeout_ms is 0."""
        config = RedisConfig()
        assert config.recv_timeout_ms == 0

    def test_recv_timeout_ms_custom(self):
        """Test custom recv_timeout_ms is respected."""
        config = RedisConfig(recv_timeout_ms=5000)
        assert config.recv_timeout_ms == 5000


class TestRedisAdapterImports:
    """Tests for RedisAdapter can be imported from adapters module."""

    def test_import_from_adapters(self):
        """Test RedisAdapter can be imported from adapters."""
        from src.adapters import Bar, MaxReconnectAttemptsError, RedisAdapter, RedisConfig

        assert RedisAdapter is not None
        assert RedisConfig is not None
        assert Bar is not None
        assert MaxReconnectAttemptsError is not None
