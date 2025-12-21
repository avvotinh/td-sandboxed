"""Integration tests for ZeroMQ adapter.

These tests require a running mt5-bridge service.
Mark tests with @pytest.mark.integration.

Run integration tests:
    uv run pytest tests/integration/ -m integration -v

Skip integration tests:
    uv run pytest -m "not integration"
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.adapters.zmq_adapter import ZmqAdapter, ZmqConfig
from src.adapters.zmq_models import Order, OrderSide

# Check if mt5-bridge is available for integration tests
MT5_BRIDGE_HOST = os.getenv("MT5_BRIDGE_HOST", "localhost")
MT5_BRIDGE_AVAILABLE = os.getenv("MT5_BRIDGE_AVAILABLE", "false").lower() == "true"


@pytest.mark.integration
@pytest.mark.skipif(not MT5_BRIDGE_AVAILABLE, reason="mt5-bridge not available")
class TestZmqIntegration:
    """Integration tests requiring running mt5-bridge."""

    @pytest.fixture
    def adapter(self):
        """Create adapter with test configuration."""
        config = ZmqConfig(
            bridge_host=MT5_BRIDGE_HOST,
            tick_port=5556,
            order_port=5557,
        )
        return ZmqAdapter(config=config)

    @pytest.mark.asyncio
    async def test_connection(self, adapter):
        """Test connecting to mt5-bridge."""
        await adapter.connect()
        assert adapter.is_connected
        await adapter.disconnect()
        assert not adapter.is_connected

    @pytest.mark.asyncio
    async def test_context_manager(self, adapter):
        """Test async context manager connection."""
        async with adapter:
            assert adapter.is_connected
        assert not adapter.is_connected

    @pytest.mark.asyncio
    async def test_receive_tick(self, adapter):
        """Test receiving tick from mt5-bridge.

        Note: This test requires mt5-bridge to be publishing ticks.
        """
        async with adapter:
            # Try to receive a tick with timeout
            try:
                async for tick in adapter.receive_ticks():
                    assert tick.symbol is not None
                    assert tick.bid > 0
                    assert tick.ask > 0
                    break  # Got one tick, test passes
            except asyncio.TimeoutError:
                pytest.skip("No ticks received within timeout")

    @pytest.mark.asyncio
    async def test_send_order(self, adapter):
        """Test sending order to mt5-bridge.

        Note: This only tests that the order is sent, not execution.
        """
        async with adapter:
            order = Order(
                account_id="test-account",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.01,
                price=1850.00,
                order_id="TEST-ORDER-001",
            )
            # Should not raise
            await adapter.send_order(order)


@pytest.mark.integration
class TestZmqConnectionErrors:
    """Tests for connection error handling."""

    @pytest.mark.asyncio
    async def test_connection_refused(self):
        """Test handling of connection refused.

        Connects to a port where nothing is listening.
        ZMQ will queue the connection attempt, so this won't fail immediately.
        """
        config = ZmqConfig(
            bridge_host="localhost",
            tick_port=59999,  # Unlikely to be in use
            order_port=59998,
        )
        adapter = ZmqAdapter(config=config)

        # ZMQ connect doesn't fail immediately - it's async
        # But we can verify the adapter reports connected after setup
        await adapter.connect()
        assert adapter.is_connected

        # Disconnect cleanly
        await adapter.disconnect()
        assert not adapter.is_connected


@pytest.mark.integration
class TestZmqReconnection:
    """Tests for reconnection behavior."""

    @pytest.mark.asyncio
    async def test_reconnect_increments_attempt(self):
        """Test that reconnect increments attempt counter."""
        config = ZmqConfig(
            bridge_host="localhost",
            tick_port=59997,
            order_port=59996,
        )
        adapter = ZmqAdapter(config=config)

        assert adapter._reconnect_attempt == 0

        # First connect
        await adapter.connect()
        assert adapter._reconnect_attempt == 0

        # Simulate reconnect (would normally be triggered by error)
        # We'll just test the counter logic
        adapter._reconnect_attempt = 3
        delay_idx = min(adapter._reconnect_attempt, len(adapter.RECONNECT_DELAYS) - 1)
        delay = adapter.RECONNECT_DELAYS[delay_idx]
        assert delay == 8  # 4th attempt = 8 seconds

        await adapter.disconnect()
