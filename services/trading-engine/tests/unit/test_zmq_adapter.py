"""Unit tests for ZeroMQ adapter.

Tests cover:
- ZmqConfig validation
- Tick parsing and properties
- Order serialization
- OrderResult parsing
- Reconnection delay sequence
- Mock socket operations
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.zmq_adapter import _ConnectionState, ZmqAdapter, ZmqConfig
from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus, Tick


class TestZmqConfig:
    """Tests for ZmqConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ZmqConfig()
        assert config.bridge_host == "localhost"
        assert config.tick_port == 5556
        assert config.order_port == 5557
        assert config.recv_timeout_ms == 1000
        assert config.send_timeout_ms == 5000

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ZmqConfig(
            bridge_host="mt5-bridge",
            tick_port=6556,
            order_port=6557,
            recv_timeout_ms=2000,
        )
        assert config.bridge_host == "mt5-bridge"
        assert config.tick_port == 6556
        assert config.order_port == 6557
        assert config.recv_timeout_ms == 2000

    def test_config_from_env(self):
        """Test configuration can be created from dict."""
        data = {
            "bridge_host": "remote-host",
            "tick_port": 7556,
        }
        config = ZmqConfig(**data)
        assert config.bridge_host == "remote-host"
        assert config.tick_port == 7556


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


class TestTick:
    """Tests for Tick dataclass."""

    def test_tick_creation(self):
        """Test tick creation."""
        tick = Tick(
            account_id="ftmo-001",
            symbol="XAUUSD",
            bid=1850.25,
            ask=1850.45,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert tick.account_id == "ftmo-001"
        assert tick.symbol == "XAUUSD"
        assert tick.bid == 1850.25
        assert tick.ask == 1850.45

    def test_tick_spread(self):
        """Test tick spread calculation."""
        tick = Tick(
            account_id="test",
            symbol="XAUUSD",
            bid=1850.25,
            ask=1850.45,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert tick.spread == pytest.approx(0.20)

    def test_tick_mid(self):
        """Test tick mid price calculation."""
        tick = Tick(
            account_id="test",
            symbol="XAUUSD",
            bid=1850.00,
            ask=1850.50,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert tick.mid == pytest.approx(1850.25)

    def test_tick_timestamp_dt(self):
        """Test tick timestamp parsing to datetime."""
        tick = Tick(
            account_id="test",
            symbol="XAUUSD",
            bid=1850.00,
            ask=1850.50,
            timestamp="2025-12-22T10:30:00Z",
        )
        dt = tick.timestamp_dt
        assert dt.year == 2025
        assert dt.month == 12
        assert dt.day == 22
        assert dt.hour == 10
        assert dt.minute == 30


class TestOrder:
    """Tests for Order Pydantic model."""

    def test_order_creation(self):
        """Test order creation."""
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.45,
            order_id="ORDER-123",
        )
        assert order.type == "order"
        assert order.account_id == "ftmo-001"
        assert order.action == OrderSide.BUY
        assert order.symbol == "XAUUSD"
        assert order.volume == 0.1
        assert order.price == 1850.45
        assert order.order_id == "ORDER-123"

    def test_order_with_sl_tp(self):
        """Test order with stop loss and take profit."""
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.SELL,
            symbol="XAUUSD",
            volume=0.5,
            price=1850.00,
            sl=1855.00,
            tp=1840.00,
            order_id="ORDER-456",
        )
        assert order.sl == 1855.00
        assert order.tp == 1840.00

    def test_order_serialization(self):
        """Test order serialization to JSON."""
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.45,
            sl=1845.00,
            tp=1860.00,
            order_id="ORDER-123",
        )
        json_str = order.model_dump_json()
        data = json.loads(json_str)

        assert data["type"] == "order"
        assert data["account_id"] == "ftmo-001"
        assert data["action"] == "BUY"
        assert data["order_id"] == "ORDER-123"
        assert data["sl"] == 1845.00
        assert data["tp"] == 1860.00

    def test_order_type_frozen(self):
        """Test that order type cannot be changed."""
        order = Order(
            account_id="test",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.00,
            order_id="TEST",
        )
        # type is frozen, attempting to change should raise
        with pytest.raises(Exception):
            order.type = "something_else"


class TestOrderResult:
    """Tests for OrderResult dataclass."""

    def test_order_result_filled(self):
        """Test filled order result."""
        result = OrderResult(
            order_id="ORDER-123",
            status=OrderStatus.FILLED,
            fill_price=1850.47,
            slippage=0.02,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert result.is_filled is True
        assert result.is_rejected is False

    def test_order_result_rejected(self):
        """Test rejected order result."""
        result = OrderResult(
            order_id="ORDER-456",
            status=OrderStatus.REJECTED,
            error="Insufficient margin",
        )
        assert result.is_filled is False
        assert result.is_rejected is True

    def test_order_result_error(self):
        """Test error order result."""
        result = OrderResult(
            order_id="ORDER-789",
            status=OrderStatus.ERROR,
            error="Connection lost",
        )
        assert result.is_rejected is True


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_order_side_values(self):
        """Test order side values."""
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_side_from_string(self):
        """Test creating order side from string."""
        assert OrderSide("BUY") == OrderSide.BUY
        assert OrderSide("SELL") == OrderSide.SELL


class TestOrderStatus:
    """Tests for OrderStatus enum."""

    def test_order_status_values(self):
        """Test order status values."""
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.REJECTED.value == "rejected"
        assert OrderStatus.ERROR.value == "error"
        assert OrderStatus.PARTIALLY_FILLED.value == "partially_filled"


class TestZmqAdapterReconnection:
    """Tests for ZmqAdapter reconnection logic."""

    def test_reconnect_delays(self):
        """Test reconnect delay sequence."""
        adapter = ZmqAdapter()
        assert adapter.RECONNECT_DELAYS == [1, 2, 4, 8, 16, 30]

    def test_reconnect_delay_calculation_first(self):
        """Test first reconnect delay is 1 second."""
        adapter = ZmqAdapter()
        adapter._reconnect_attempt = 0
        delay_idx = min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        delay = adapter.RECONNECT_DELAYS[delay_idx]
        assert delay == 1

    def test_reconnect_delay_calculation_fourth(self):
        """Test fourth reconnect delay is 8 seconds."""
        adapter = ZmqAdapter()
        adapter._reconnect_attempt = 3
        delay_idx = min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        delay = adapter.RECONNECT_DELAYS[delay_idx]
        assert delay == 8

    def test_reconnect_delay_calculation_max(self):
        """Test max reconnect delay is 30 seconds."""
        adapter = ZmqAdapter()
        adapter._reconnect_attempt = 100
        delay_idx = min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        delay = adapter.RECONNECT_DELAYS[delay_idx]
        assert delay == 30


class TestZmqAdapterConnection:
    """Tests for ZmqAdapter connection management."""

    def test_adapter_not_connected_by_default(self):
        """Test adapter is not connected by default."""
        adapter = ZmqAdapter()
        assert adapter.is_connected is False

    def test_adapter_custom_config(self):
        """Test adapter with custom config."""
        config = ZmqConfig(bridge_host="custom-host", tick_port=9556)
        adapter = ZmqAdapter(config=config)
        assert adapter.config.bridge_host == "custom-host"
        assert adapter.config.tick_port == 9556

    @pytest.mark.asyncio
    async def test_send_order_not_connected_raises(self):
        """Test send_order raises when not connected."""
        adapter = ZmqAdapter()
        order = Order(
            account_id="test",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.00,
            order_id="TEST-001",
        )
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.send_order(order)

    @pytest.mark.asyncio
    async def test_receive_ticks_not_connected_raises(self):
        """Test receive_ticks raises when not connected."""
        adapter = ZmqAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            async for _ in adapter.receive_ticks():
                pass

    def test_pending_order_count(self):
        """Test pending order count."""
        adapter = ZmqAdapter()
        assert adapter.get_pending_order_count() == 0

        # Manually add pending order for test
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        adapter._pending_orders["ORDER-001"] = future
        assert adapter.get_pending_order_count() == 1
        loop.close()


class TestZmqAdapterMocked:
    """Tests for ZmqAdapter with mocked sockets."""

    @pytest.mark.asyncio
    async def test_send_order_with_mock(self):
        """Test sending order with mocked socket."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._pub_socket = AsyncMock()

        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.45,
            order_id="ORDER-123",
        )

        await adapter.send_order(order)

        # Verify send_multipart was called
        adapter._pub_socket.send_multipart.assert_called_once()
        call_args = adapter._pub_socket.send_multipart.call_args[0][0]
        assert call_args[0] == b"order:ftmo-001"
        assert b"ORDER-123" in call_args[1]

    @pytest.mark.asyncio
    async def test_receive_ticks_parses_tick(self):
        """Test receive_ticks parses tick messages correctly."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        # Mock receiving a tick message
        tick_data = {
            "account_id": "ftmo-001",
            "symbol": "XAUUSD",
            "bid": 1850.25,
            "ask": 1850.45,
            "timestamp": "2025-12-22T10:00:00Z",
        }
        adapter._sub_socket.recv_multipart = AsyncMock(
            return_value=[b"tick:XAUUSD", json.dumps(tick_data).encode()]
        )

        # Get first tick
        tick = None
        async for t in adapter.receive_ticks():
            tick = t
            break

        assert tick is not None
        assert tick.account_id == "ftmo-001"
        assert tick.symbol == "XAUUSD"
        assert tick.bid == 1850.25
        assert tick.ask == 1850.45

    @pytest.mark.asyncio
    async def test_receive_ticks_handles_order_result(self):
        """Test receive_ticks handles order result messages."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        # Create pending order future
        loop = asyncio.get_running_loop()
        future: asyncio.Future[OrderResult] = loop.create_future()
        adapter._pending_orders["ORDER-123"] = future

        # Mock receiving order result
        result_data = {
            "order_id": "ORDER-123",
            "status": "filled",
            "fill_price": 1850.47,
            "slippage": 0.02,
            "timestamp": "2025-12-22T10:00:00Z",
        }

        call_count = 0

        async def mock_recv():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [b"order_result:ORDER-123", json.dumps(result_data).encode()]
            # Return a tick to keep the loop going
            return [
                b"tick:XAUUSD",
                b'{"account_id":"test","symbol":"XAUUSD","bid":1850.0,"ask":1850.5,"timestamp":"2025-12-22T10:00:00Z"}',
            ]

        adapter._sub_socket.recv_multipart = mock_recv

        # Start receiving in background
        async def receiver():
            async for _ in adapter.receive_ticks():
                if future.done():
                    break

        task = asyncio.create_task(receiver())

        # Wait for result
        result = await asyncio.wait_for(future, timeout=1.0)
        task.cancel()

        assert result.order_id == "ORDER-123"
        assert result.status == OrderStatus.FILLED
        assert result.fill_price == 1850.47

    @pytest.mark.asyncio
    async def test_send_order_and_wait_timeout(self):
        """Test send_order_and_wait raises on timeout."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._pub_socket = AsyncMock()

        order = Order(
            account_id="test",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.00,
            order_id="TIMEOUT-ORDER",
        )

        # No result will arrive, should timeout
        with pytest.raises(asyncio.TimeoutError):
            await adapter.send_order_and_wait(order, timeout=0.1)

        # Pending order should be cleaned up
        assert "TIMEOUT-ORDER" not in adapter._pending_orders

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        with patch.object(ZmqAdapter, "connect", new_callable=AsyncMock) as mock_connect:
            with patch.object(
                ZmqAdapter, "disconnect", new_callable=AsyncMock
            ) as mock_disconnect:
                async with ZmqAdapter() as adapter:
                    assert adapter is not None

                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()


class TestTickParsing:
    """Tests for tick parsing from JSON."""

    def test_parse_tick_from_json(self):
        """Test parsing tick from JSON payload."""
        json_str = '{"account_id":"ftmo-001","symbol":"XAUUSD","bid":1850.25,"ask":1850.45,"timestamp":"2025-12-22T10:00:00Z"}'
        data = json.loads(json_str)
        tick = Tick(
            account_id=data["account_id"],
            symbol=data["symbol"],
            bid=data["bid"],
            ask=data["ask"],
            timestamp=data["timestamp"],
        )
        assert tick.symbol == "XAUUSD"
        assert tick.bid == 1850.25

    def test_tick_with_extra_fields(self):
        """Test tick parsing ignores extra fields."""
        data = {
            "account_id": "test",
            "symbol": "EURUSD",
            "bid": 1.0850,
            "ask": 1.0852,
            "timestamp": "2025-12-22T10:00:00Z",
            "extra_field": "ignored",
        }
        tick = Tick(
            account_id=data["account_id"],
            symbol=data["symbol"],
            bid=data["bid"],
            ask=data["ask"],
            timestamp=data["timestamp"],
        )
        assert tick.symbol == "EURUSD"


class TestOrderResultParsing:
    """Tests for order result parsing from JSON."""

    def test_parse_filled_result(self):
        """Test parsing filled order result."""
        data = {
            "order_id": "ORDER-123",
            "status": "filled",
            "fill_price": 1850.47,
            "slippage": 0.02,
            "timestamp": "2025-12-22T10:00:00Z",
        }
        result = OrderResult(
            order_id=data["order_id"],
            status=OrderStatus(data["status"]),
            fill_price=data.get("fill_price"),
            slippage=data.get("slippage"),
            timestamp=data.get("timestamp", ""),
        )
        assert result.is_filled
        assert result.fill_price == 1850.47

    def test_parse_rejected_result(self):
        """Test parsing rejected order result."""
        data = {
            "order_id": "ORDER-456",
            "status": "rejected",
            "error": "Insufficient margin",
            "timestamp": "2025-12-22T10:00:00Z",
        }
        result = OrderResult(
            order_id=data["order_id"],
            status=OrderStatus(data["status"]),
            error=data.get("error"),
            timestamp=data.get("timestamp", ""),
        )
        assert result.is_rejected
        assert result.error == "Insufficient margin"


class TestOrderValidation:
    """Tests for Order field validation."""

    def test_order_rejects_empty_account_id(self):
        """Test order rejects empty account_id."""
        with pytest.raises(ValueError, match="at least 1 character"):
            Order(
                account_id="",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=1850.00,
                order_id="TEST",
            )

    def test_order_rejects_empty_symbol(self):
        """Test order rejects empty symbol."""
        with pytest.raises(ValueError, match="at least 1 character"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="",
                volume=0.1,
                price=1850.00,
                order_id="TEST",
            )

    def test_order_rejects_empty_order_id(self):
        """Test order rejects empty order_id."""
        with pytest.raises(ValueError, match="at least 1 character"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=1850.00,
                order_id="",
            )

    def test_order_rejects_zero_volume(self):
        """Test order rejects zero volume."""
        with pytest.raises(ValueError, match="greater than 0"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0,
                price=1850.00,
                order_id="TEST",
            )

    def test_order_rejects_negative_volume(self):
        """Test order rejects negative volume."""
        with pytest.raises(ValueError, match="greater than 0"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=-0.1,
                price=1850.00,
                order_id="TEST",
            )

    def test_order_rejects_zero_price(self):
        """Test order rejects zero price."""
        with pytest.raises(ValueError, match="greater than 0"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=0,
                order_id="TEST",
            )

    def test_order_rejects_negative_price(self):
        """Test order rejects negative price."""
        with pytest.raises(ValueError, match="greater than 0"):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=-1850.00,
                order_id="TEST",
            )

    def test_order_rejects_negative_sl(self):
        """Test order rejects negative stop loss."""
        with pytest.raises(ValueError):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=1850.00,
                sl=-1845.00,
                order_id="TEST",
            )

    def test_order_rejects_negative_tp(self):
        """Test order rejects negative take profit."""
        with pytest.raises(ValueError):
            Order(
                account_id="test",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=1850.00,
                tp=-1860.00,
                order_id="TEST",
            )

    def test_order_allows_none_sl_tp(self):
        """Test order allows None for sl and tp."""
        order = Order(
            account_id="test",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.1,
            price=1850.00,
            order_id="TEST",
        )
        assert order.sl is None
        assert order.tp is None


class TestTickValidation:
    """Tests for Tick field validation."""

    def test_tick_rejects_empty_account_id(self):
        """Test tick rejects empty account_id."""
        with pytest.raises(ValueError, match="account_id must not be empty"):
            Tick(
                account_id="",
                symbol="XAUUSD",
                bid=1850.25,
                ask=1850.45,
                timestamp="2025-12-22T10:00:00Z",
            )

    def test_tick_rejects_empty_symbol(self):
        """Test tick rejects empty symbol."""
        with pytest.raises(ValueError, match="symbol must not be empty"):
            Tick(
                account_id="test",
                symbol="",
                bid=1850.25,
                ask=1850.45,
                timestamp="2025-12-22T10:00:00Z",
            )

    def test_tick_rejects_negative_bid(self):
        """Test tick rejects negative bid."""
        with pytest.raises(ValueError, match="bid must be positive"):
            Tick(
                account_id="test",
                symbol="XAUUSD",
                bid=-1850.25,
                ask=1850.45,
                timestamp="2025-12-22T10:00:00Z",
            )

    def test_tick_rejects_zero_bid(self):
        """Test tick rejects zero bid."""
        with pytest.raises(ValueError, match="bid must be positive"):
            Tick(
                account_id="test",
                symbol="XAUUSD",
                bid=0,
                ask=1850.45,
                timestamp="2025-12-22T10:00:00Z",
            )

    def test_tick_rejects_ask_less_than_bid(self):
        """Test tick rejects ask < bid."""
        with pytest.raises(ValueError, match="ask must be >= bid"):
            Tick(
                account_id="test",
                symbol="XAUUSD",
                bid=1850.50,
                ask=1850.25,
                timestamp="2025-12-22T10:00:00Z",
            )

    def test_tick_rejects_empty_timestamp(self):
        """Test tick rejects empty timestamp."""
        with pytest.raises(ValueError, match="timestamp must not be empty"):
            Tick(
                account_id="test",
                symbol="XAUUSD",
                bid=1850.25,
                ask=1850.45,
                timestamp="",
            )

    def test_tick_allows_equal_bid_ask(self):
        """Test tick allows bid == ask (zero spread)."""
        tick = Tick(
            account_id="test",
            symbol="XAUUSD",
            bid=1850.25,
            ask=1850.25,
            timestamp="2025-12-22T10:00:00Z",
        )
        assert tick.spread == 0


class TestMalformedMessages:
    """Tests for handling malformed ZeroMQ messages."""

    @pytest.mark.asyncio
    async def test_receive_handles_empty_topic(self):
        """Test receive_ticks handles empty topic gracefully."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        messages_received = []

        async def mock_recv():
            if len(messages_received) == 0:
                messages_received.append(1)
                # Empty topic - should be logged and skipped
                return [b"", b'{"account_id":"test","symbol":"X","bid":1.0,"ask":1.1,"timestamp":"2025-12-22T10:00:00Z"}']
            # Return valid tick on second call
            return [b"tick:XAUUSD", b'{"account_id":"test","symbol":"XAUUSD","bid":1850.25,"ask":1850.45,"timestamp":"2025-12-22T10:00:00Z"}']

        adapter._sub_socket.recv_multipart = mock_recv

        tick = None
        async for t in adapter.receive_ticks():
            tick = t
            break

        assert tick is not None
        assert tick.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_receive_handles_extra_multipart_frames(self):
        """Test receive_ticks handles messages with extra frames."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        # Message with 3 frames instead of 2 - should still work (uses first 2)
        adapter._sub_socket.recv_multipart = AsyncMock(
            return_value=[
                b"tick:XAUUSD",
                b'{"account_id":"test","symbol":"XAUUSD","bid":1850.25,"ask":1850.45,"timestamp":"2025-12-22T10:00:00Z"}',
                b"extra_frame_ignored",
            ]
        )

        tick = None
        async for t in adapter.receive_ticks():
            tick = t
            break

        assert tick is not None
        assert tick.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_receive_handles_invalid_json(self):
        """Test receive_ticks handles invalid JSON gracefully."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        call_count = 0

        async def mock_recv():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Invalid JSON - should be logged and skipped
                return [b"tick:XAUUSD", b"not valid json"]
            # Return valid tick on second call
            return [b"tick:XAUUSD", b'{"account_id":"test","symbol":"XAUUSD","bid":1850.25,"ask":1850.45,"timestamp":"2025-12-22T10:00:00Z"}']

        adapter._sub_socket.recv_multipart = mock_recv

        tick = None
        async for t in adapter.receive_ticks():
            tick = t
            break

        assert tick is not None
        assert tick.symbol == "XAUUSD"

    @pytest.mark.asyncio
    async def test_receive_handles_missing_fields(self):
        """Test receive_ticks handles JSON with missing fields."""
        adapter = ZmqAdapter()
        adapter._state.connected = True
        adapter._sub_socket = AsyncMock()

        call_count = 0

        async def mock_recv():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Missing 'ask' field - should be logged and skipped
                return [b"tick:XAUUSD", b'{"account_id":"test","symbol":"XAUUSD","bid":1850.25}']
            # Return valid tick on second call
            return [b"tick:XAUUSD", b'{"account_id":"test","symbol":"XAUUSD","bid":1850.25,"ask":1850.45,"timestamp":"2025-12-22T10:00:00Z"}']

        adapter._sub_socket.recv_multipart = mock_recv

        tick = None
        async for t in adapter.receive_ticks():
            tick = t
            break

        assert tick is not None
        assert tick.symbol == "XAUUSD"
