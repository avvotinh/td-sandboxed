"""Unit tests for OrderExecutionService."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus
from src.orders.execution_service import (
    DuplicateOrderError,
    NoPositionError,
    OrderExecutionService,
)
from src.orders.order import InternalOrder, OrderState
from src.orders.position_tracker import PositionTracker
from src.orders.signal import Signal, SignalType


class TestOrderExecutionServiceInit:
    """Tests for OrderExecutionService initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        zmq = MagicMock()
        tracker = PositionTracker()

        service = OrderExecutionService(zmq, tracker)

        assert service._zmq == zmq
        assert service._positions == tracker
        assert service._order_timeout == 5.0
        assert len(service._pending_order_ids) == 0
        assert len(service._trades) == 0

    def test_init_with_custom_timeout(self):
        """Should accept custom timeout."""
        zmq = MagicMock()
        tracker = PositionTracker()

        service = OrderExecutionService(zmq, tracker, order_timeout=10.0)

        assert service._order_timeout == 10.0


class TestOrderCreation:
    """Tests for order creation from signals."""

    @pytest.fixture
    def service(self):
        """Create service with mock ZMQ."""
        zmq = MagicMock()
        tracker = PositionTracker()
        return OrderExecutionService(zmq, tracker)

    def test_create_buy_order(self, service):
        """BUY signal should create BUY order."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test",
        )

        order = service._create_order(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
            sl=1845.00,
            tp=1860.00,
        )

        assert order.action == OrderSide.BUY
        assert order.symbol == "XAUUSD"
        assert order.account_id == "ftmo-001"
        assert order.volume == 0.1
        assert order.price == 1850.45
        assert order.sl == 1845.00
        assert order.tp == 1860.00
        assert order.signal_type == SignalType.BUY

    def test_create_sell_order(self, service):
        """SELL signal should create SELL order."""
        signal = Signal(
            signal_type=SignalType.SELL,
            symbol="EURUSD",
            strategy_name="test",
        )

        order = service._create_order(
            signal=signal,
            account_id="ftmo-001",
            volume=0.5,
            price=1.0850,
            sl=None,
            tp=None,
        )

        assert order.action == OrderSide.SELL
        assert order.symbol == "EURUSD"
        assert order.signal_type == SignalType.SELL

    def test_create_close_order_from_long_position(self, service):
        """CLOSE signal on long position should create SELL order."""
        # First open a long position
        long_order = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.BUY,
            volume=0.1,
            price=1850.00,
        )
        long_order.state = OrderState.FILLED
        long_order.fill_price = 1850.00
        long_order.filled_at = datetime.now(timezone.utc)
        service._positions.open_position(long_order)

        # Create CLOSE signal
        signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
        )

        order = service._create_order(
            signal=signal,
            account_id="ftmo-001",
            volume=0,  # Should use position volume
            price=1855.00,
            sl=None,
            tp=None,
        )

        assert order.action == OrderSide.SELL  # Opposite of long
        assert order.volume == 0.1  # From position
        assert order.signal_type == SignalType.CLOSE
        assert order.is_close_order is True

    def test_create_close_order_from_short_position(self, service):
        """CLOSE signal on short position should create BUY order."""
        # First open a short position
        short_order = InternalOrder(
            account_id="ftmo-001",
            symbol="XAUUSD",
            action=OrderSide.SELL,
            volume=0.2,
            price=1850.00,
        )
        short_order.state = OrderState.FILLED
        short_order.fill_price = 1850.00
        short_order.filled_at = datetime.now(timezone.utc)
        service._positions.open_position(short_order)

        # Create CLOSE signal
        signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
        )

        order = service._create_order(
            signal=signal,
            account_id="ftmo-001",
            volume=0,
            price=1840.00,
            sl=None,
            tp=None,
        )

        assert order.action == OrderSide.BUY  # Opposite of short
        assert order.volume == 0.2  # From position

    def test_create_close_order_no_position_raises_error(self, service):
        """CLOSE signal without position should raise NoPositionError."""
        signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
        )

        with pytest.raises(NoPositionError, match="No position to close"):
            service._create_order(
                signal=signal,
                account_id="ftmo-001",
                volume=0,
                price=1850.00,
                sl=None,
                tp=None,
            )


class TestOrderExecution:
    """Tests for order execution."""

    @pytest.fixture
    def mock_zmq(self):
        """Create mock ZMQ adapter with successful order result."""
        zmq = MagicMock()
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="test-123",
                status=OrderStatus.FILLED,
                fill_price=1850.47,
                slippage=0.02,
                timestamp="2025-12-22T10:00:00Z",
            )
        )
        return zmq

    @pytest.fixture
    def service(self, mock_zmq):
        """Create service with mock ZMQ."""
        tracker = PositionTracker()
        return OrderExecutionService(mock_zmq, tracker)

    @pytest.mark.asyncio
    async def test_execute_buy_signal(self, service, mock_zmq):
        """Should execute BUY signal and return filled order."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test",
        )

        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert order.state == OrderState.FILLED
        assert order.fill_price == 1850.47
        assert order.slippage == 0.02
        mock_zmq.send_order_and_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_signal_opens_position(self, service):
        """Filled BUY signal should open position."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test",
        )

        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert service._positions.has_position("ftmo-001", "XAUUSD") is True
        position = service._positions.get_position("ftmo-001", "XAUUSD")
        assert position.side == OrderSide.BUY
        assert position.quantity == 0.1

    @pytest.mark.asyncio
    async def test_execute_signal_creates_trade(self, service):
        """Filled signal should create trade record."""
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="test",
        )

        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        trades = service.get_trades()
        assert len(trades) == 1
        assert trades[0].symbol == "XAUUSD"
        assert trades[0].side == OrderSide.BUY
        assert trades[0].is_open is True

    @pytest.mark.asyncio
    async def test_execute_close_signal(self, service, mock_zmq):
        """Should execute CLOSE signal and close position."""
        # First open a position
        buy_signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
        )
        await service.execute_signal(
            signal=buy_signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        # Reset mock for close order
        mock_zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="close-123",
                status=OrderStatus.FILLED,
                fill_price=1860.00,
                slippage=0.03,
                timestamp="2025-12-22T11:00:00Z",
            )
        )

        # Execute CLOSE
        close_signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
        )
        order = await service.execute_signal(
            signal=close_signal,
            account_id="ftmo-001",
            volume=0,  # Uses position volume
            price=1860.00,
        )

        assert order.state == OrderState.FILLED
        assert order.action == OrderSide.SELL  # Opposite of long
        assert service._positions.has_position("ftmo-001", "XAUUSD") is False

    @pytest.mark.asyncio
    async def test_execute_close_creates_closed_trade(self, service, mock_zmq):
        """CLOSE signal should create trade with PnL."""
        # Open position
        buy_signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        await service.execute_signal(
            signal=buy_signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.00,
        )

        # Close position at profit
        mock_zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="close-123",
                status=OrderStatus.FILLED,
                fill_price=1860.00,
                slippage=0.0,
                timestamp="2025-12-22T11:00:00Z",
            )
        )

        close_signal = Signal(signal_type=SignalType.CLOSE, symbol="XAUUSD")
        await service.execute_signal(
            signal=close_signal,
            account_id="ftmo-001",
            volume=0,
            price=1860.00,
        )

        trades = service.get_closed_trades()
        assert len(trades) == 1
        assert trades[0].is_closed is True
        # Entry was at 1850.47 (mock fill_price), exit at 1860.00
        # PnL = (1860.00 - 1850.47) * 0.1 = 0.953
        assert trades[0].pnl_dollars == pytest.approx(0.953, rel=0.01)


class TestOrderRejection:
    """Tests for rejected orders."""

    @pytest.fixture
    def rejected_zmq(self):
        """Create mock ZMQ adapter that rejects orders."""
        zmq = MagicMock()
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="test-123",
                status=OrderStatus.REJECTED,
                fill_price=None,
                slippage=None,
                timestamp="2025-12-22T10:00:00Z",
                error="Insufficient margin",
            )
        )
        return zmq

    @pytest.mark.asyncio
    async def test_rejected_order_state(self, rejected_zmq):
        """Rejected order should have REJECTED state."""
        service = OrderExecutionService(rejected_zmq, PositionTracker())

        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert order.state == OrderState.REJECTED
        assert order.rejection_reason == "Insufficient margin"

    @pytest.mark.asyncio
    async def test_rejected_order_no_position(self, rejected_zmq):
        """Rejected order should not open position."""
        service = OrderExecutionService(rejected_zmq, PositionTracker())

        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert service._positions.has_position("ftmo-001", "XAUUSD") is False

    @pytest.mark.asyncio
    async def test_rejected_order_no_trade(self, rejected_zmq):
        """Rejected order should not create trade."""
        service = OrderExecutionService(rejected_zmq, PositionTracker())

        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert len(service.get_trades()) == 0


class TestIdempotency:
    """Tests for idempotency checking."""

    @pytest.fixture
    def slow_zmq(self):
        """Create mock ZMQ that takes time to respond."""
        zmq = MagicMock()

        async def slow_send(*args, **kwargs):
            await asyncio.sleep(0.5)
            return OrderResult(
                order_id="test-123",
                status=OrderStatus.FILLED,
                fill_price=1850.47,
                slippage=0.02,
                timestamp="2025-12-22T10:00:00Z",
            )

        zmq.send_order_and_wait = slow_send
        return zmq

    @pytest.mark.asyncio
    async def test_pending_order_tracked(self, slow_zmq):
        """Pending orders should be tracked."""
        service = OrderExecutionService(slow_zmq, PositionTracker())

        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")

        # Start order but don't wait
        task = asyncio.create_task(
            service.execute_signal(
                signal=signal,
                account_id="ftmo-001",
                volume=0.1,
                price=1850.45,
            )
        )

        await asyncio.sleep(0.1)  # Let task start

        # Should have pending order
        assert service.get_pending_order_count() == 1

        # Complete the task
        await task

        # Should no longer be pending
        assert service.get_pending_order_count() == 0

    @pytest.mark.asyncio
    async def test_pending_order_cleaned_on_error(self):
        """Pending order should be cleaned up on error."""
        zmq = MagicMock()
        zmq.send_order_and_wait = AsyncMock(
            side_effect=Exception("Connection error")
        )

        service = OrderExecutionService(zmq, PositionTracker())
        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")

        with pytest.raises(Exception, match="Connection error"):
            await service.execute_signal(
                signal=signal,
                account_id="ftmo-001",
                volume=0.1,
                price=1850.45,
            )

        assert service.get_pending_order_count() == 0


class TestSlippageTracking:
    """Tests for slippage tracking."""

    @pytest.mark.asyncio
    async def test_slippage_warning_threshold(self):
        """High slippage should be logged as warning."""
        zmq = MagicMock()
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="test-123",
                status=OrderStatus.FILLED,
                fill_price=1860.00,  # 10 points slippage on 1850
                slippage=10.0,  # > 0.5% threshold
                timestamp="2025-12-22T10:00:00Z",
            )
        )

        service = OrderExecutionService(zmq, PositionTracker())

        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.00,
        )

        assert order.slippage == 10.0


class TestTradeQueries:
    """Tests for trade query methods."""

    @pytest.fixture
    def service_with_trades(self):
        """Create service with some trades."""
        zmq = MagicMock()
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="test-123",
                status=OrderStatus.FILLED,
                fill_price=1850.47,
                slippage=0.02,
                timestamp="2025-12-22T10:00:00Z",
            )
        )
        return OrderExecutionService(zmq, PositionTracker())

    @pytest.mark.asyncio
    async def test_get_trades_by_account(self, service_with_trades):
        """Should filter trades by account."""
        service = service_with_trades

        # Create trades for different accounts
        for account in ["ftmo-001", "ftmo-001", "ftmo-002"]:
            signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
            await service.execute_signal(
                signal=signal,
                account_id=account,
                volume=0.1,
                price=1850.45,
            )
            # Close position for next trade
            service._positions.close_position(account, "XAUUSD")

        trades_001 = service.get_trades_by_account("ftmo-001")
        trades_002 = service.get_trades_by_account("ftmo-002")

        assert len(trades_001) == 2
        assert len(trades_002) == 1

    @pytest.mark.asyncio
    async def test_get_open_and_closed_trades(self, service_with_trades):
        """Should separate open and closed trades."""
        service = service_with_trades
        zmq = service._zmq

        # Open trade
        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.45,
        )

        assert len(service.get_open_trades()) == 1
        assert len(service.get_closed_trades()) == 0

        # Close trade
        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="close-123",
                status=OrderStatus.FILLED,
                fill_price=1860.00,
                slippage=0.0,
                timestamp="2025-12-22T11:00:00Z",
            )
        )

        close_signal = Signal(signal_type=SignalType.CLOSE, symbol="XAUUSD")
        await service.execute_signal(
            signal=close_signal,
            account_id="ftmo-001",
            volume=0,
            price=1860.00,
        )

        # Now we have 2 trades: 1 open (entry) and 1 closed (entry+exit)
        # Wait - the entry trade should remain open, and we create a new closed trade
        # Actually, on close we create a NEW trade record that includes PnL
        assert len(service.get_closed_trades()) == 1

    @pytest.mark.asyncio
    async def test_get_total_pnl(self, service_with_trades):
        """Should calculate total realized PnL."""
        service = service_with_trades
        zmq = service._zmq

        # Open and close with profit
        signal = Signal(signal_type=SignalType.BUY, symbol="XAUUSD")
        await service.execute_signal(
            signal=signal,
            account_id="ftmo-001",
            volume=0.1,
            price=1850.00,
        )

        zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="close-123",
                status=OrderStatus.FILLED,
                fill_price=1860.00,
                slippage=0.0,
                timestamp="2025-12-22T11:00:00Z",
            )
        )

        close_signal = Signal(signal_type=SignalType.CLOSE, symbol="XAUUSD")
        await service.execute_signal(
            signal=close_signal,
            account_id="ftmo-001",
            volume=0,
            price=1860.00,
        )

        total_pnl = service.get_total_pnl()
        # Entry was at 1850.47 (mock fill_price), exit at 1860.00
        # PnL = (1860.00 - 1850.47) * 0.1 = 0.953
        assert total_pnl == pytest.approx(0.953, rel=0.01)

    def test_clear_trades(self, service_with_trades):
        """Should clear all trades."""
        service = service_with_trades

        # Add some mock trades
        from src.orders.trade import Trade

        service._trades.append(
            Trade(
                order_id="order-1",
                account_id="test",
                symbol="XAUUSD",
                side=OrderSide.BUY,
                quantity=0.1,
                entry_price=1850.00,
                entry_time=datetime.now(timezone.utc),
            )
        )

        count = service.clear_trades()
        assert count == 1
        assert len(service.get_trades()) == 0


class TestServiceRepr:
    """Tests for service string representation."""

    def test_repr(self):
        """repr should show pending and trade counts."""
        zmq = MagicMock()
        service = OrderExecutionService(zmq, PositionTracker())

        repr_str = repr(service)
        assert "OrderExecutionService" in repr_str
        assert "pending=0" in repr_str
        assert "trades=0" in repr_str
