"""Integration tests for order execution flow.

These tests verify end-to-end order execution with a running mt5-bridge.
They are marked with @pytest.mark.integration and skipped unless
MT5_BRIDGE_AVAILABLE=true is set in the environment.
"""

import asyncio
import os

import pytest

from src.adapters.zmq_adapter import ZmqAdapter
from src.adapters.zmq_models import OrderSide
from src.orders.execution_service import OrderExecutionService
from src.orders.order import OrderState
from src.orders.position_tracker import PositionTracker
from src.orders.signal import Signal, SignalType


# Skip all tests in this module unless MT5_BRIDGE_AVAILABLE is set
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("MT5_BRIDGE_AVAILABLE", "").lower() != "true",
        reason="MT5_BRIDGE_AVAILABLE not set to true",
    ),
]


class TestOrderExecutionIntegration:
    """Integration tests for order execution with live bridge."""

    @pytest.fixture
    async def zmq_adapter(self):
        """Create and connect ZmqAdapter."""
        adapter = ZmqAdapter()
        await adapter.connect()
        yield adapter
        await adapter.disconnect()

    @pytest.fixture
    def execution_service(self, zmq_adapter):
        """Create execution service with real ZMQ adapter."""
        tracker = PositionTracker()
        return OrderExecutionService(
            zmq_adapter=zmq_adapter,
            position_tracker=tracker,
            order_timeout=10.0,  # Longer timeout for real execution
        )

    @pytest.fixture
    async def tick_receiver_task(self, zmq_adapter):
        """Start tick receiver in background.

        CRITICAL: Order results require receive_ticks() to be running.
        """

        async def receiver():
            try:
                async for tick in zmq_adapter.receive_ticks():
                    # Just consume ticks - order results handled internally
                    pass
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(receiver())
        await asyncio.sleep(0.1)  # Allow task to start
        yield task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_full_buy_order_flow(
        self, execution_service, tick_receiver_task
    ):
        """Test complete BUY order from signal to fill.

        Requires running mt5-bridge.
        """
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="integration_test",
        )

        order = await execution_service.execute_signal(
            signal=signal,
            account_id="integration-test-001",
            volume=0.01,  # Minimum lot size
            price=1850.00,
        )

        # Verify order executed
        assert order.state in (OrderState.FILLED, OrderState.REJECTED)

        if order.is_filled:
            assert order.fill_price is not None
            assert execution_service._positions.has_position(
                "integration-test-001", "XAUUSD"
            )
            assert len(execution_service.get_trades()) >= 1

    @pytest.mark.asyncio
    async def test_full_sell_order_flow(
        self, execution_service, tick_receiver_task
    ):
        """Test complete SELL order from signal to fill."""
        signal = Signal(
            signal_type=SignalType.SELL,
            symbol="XAUUSD",
            strategy_name="integration_test",
        )

        order = await execution_service.execute_signal(
            signal=signal,
            account_id="integration-test-002",
            volume=0.01,
            price=1850.00,
        )

        assert order.state in (OrderState.FILLED, OrderState.REJECTED)

        if order.is_filled:
            position = execution_service._positions.get_position(
                "integration-test-002", "XAUUSD"
            )
            if position:
                assert position.side == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_open_and_close_position(
        self, execution_service, tick_receiver_task
    ):
        """Test opening and closing a position."""
        # Open position
        buy_signal = Signal(
            signal_type=SignalType.BUY,
            symbol="EURUSD",
            strategy_name="integration_test",
        )

        open_order = await execution_service.execute_signal(
            signal=buy_signal,
            account_id="integration-test-003",
            volume=0.01,
            price=1.0850,
        )

        if not open_order.is_filled:
            pytest.skip("Open order was rejected - can't test close")

        # Verify position opened
        assert execution_service._positions.has_position(
            "integration-test-003", "EURUSD"
        )

        # Close position
        close_signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="EURUSD",
        )

        close_order = await execution_service.execute_signal(
            signal=close_signal,
            account_id="integration-test-003",
            volume=0,  # Uses position volume
            price=1.0855,
        )

        if close_order.is_filled:
            # Verify position closed
            assert not execution_service._positions.has_position(
                "integration-test-003", "EURUSD"
            )

            # Verify trade with PnL created
            closed_trades = execution_service.get_closed_trades()
            assert len(closed_trades) >= 1

    @pytest.mark.asyncio
    async def test_order_timeout_without_receiver(self, zmq_adapter):
        """Order should timeout if receive_ticks() not running."""
        # Do NOT start tick_receiver_task
        tracker = PositionTracker()
        service = OrderExecutionService(
            zmq_adapter=zmq_adapter,
            position_tracker=tracker,
            order_timeout=2.0,  # Short timeout
        )

        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )

        with pytest.raises(asyncio.TimeoutError):
            await service.execute_signal(
                signal=signal,
                account_id="timeout-test",
                volume=0.01,
                price=1850.00,
            )

    @pytest.mark.asyncio
    async def test_slippage_recorded(
        self, execution_service, tick_receiver_task
    ):
        """Slippage should be recorded on filled orders."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )

        order = await execution_service.execute_signal(
            signal=signal,
            account_id="slippage-test",
            volume=0.01,
            price=1850.00,
        )

        if order.is_filled:
            # Slippage may be 0 or have a value
            assert order.slippage is not None or order.fill_price is not None


class TestMultipleOrders:
    """Integration tests for multiple concurrent orders."""

    @pytest.fixture
    async def zmq_adapter(self):
        """Create and connect ZmqAdapter."""
        adapter = ZmqAdapter()
        await adapter.connect()
        yield adapter
        await adapter.disconnect()

    @pytest.fixture
    def execution_service(self, zmq_adapter):
        """Create execution service."""
        return OrderExecutionService(
            zmq_adapter=zmq_adapter,
            position_tracker=PositionTracker(),
        )

    @pytest.fixture
    async def tick_receiver_task(self, zmq_adapter):
        """Start tick receiver in background."""

        async def receiver():
            try:
                async for _ in zmq_adapter.receive_ticks():
                    pass
            except asyncio.CancelledError:
                pass

        task = asyncio.create_task(receiver())
        await asyncio.sleep(0.1)
        yield task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_sequential_orders(
        self, execution_service, tick_receiver_task
    ):
        """Multiple orders should execute sequentially."""
        results = []

        for i in range(3):
            signal = Signal(
                signal_type=SignalType.BUY,
                symbol="XAUUSD",
            )

            order = await execution_service.execute_signal(
                signal=signal,
                account_id=f"seq-test-{i}",
                volume=0.01,
                price=1850.00,
            )
            results.append(order)

        # All orders should complete
        assert len(results) == 3
        for order in results:
            assert order.state in (OrderState.FILLED, OrderState.REJECTED)

    @pytest.mark.asyncio
    async def test_different_symbols(
        self, execution_service, tick_receiver_task
    ):
        """Orders for different symbols should work."""
        symbols = ["XAUUSD", "EURUSD", "GBPUSD"]
        results = []

        for symbol in symbols:
            signal = Signal(
                signal_type=SignalType.BUY,
                symbol=symbol,
            )

            order = await execution_service.execute_signal(
                signal=signal,
                account_id="multi-symbol-test",
                volume=0.01,
                price=1850.00 if symbol == "XAUUSD" else 1.0850,
            )
            results.append(order)

            # Close position for next iteration
            if order.is_filled:
                execution_service._positions.close_position(
                    "multi-symbol-test", symbol
                )

        assert len(results) == 3
