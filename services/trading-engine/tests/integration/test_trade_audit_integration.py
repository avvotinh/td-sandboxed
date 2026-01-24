"""Service-level integration tests for Trade Execution Audit Logging.

Tests cover:
- OrderExecutionService + TradeDBWriter integration (method calls, parameters)
- Trade entry → position close → complete record verification
- Fire-and-forget pattern verification

NOTE: These tests use mocked TradeDBWriter (AsyncMock) to verify service-level
integration. True database integration tests require a PostgreSQL/TimescaleDB
test container and should be added in a dedicated test suite with:
- Real async engine against test database
- Verification of actual INSERT/UPDATE statements
- AC #3 verification (SELECT queries returning complete records)
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus
from src.orders.db_models import TradeRecord
from src.orders.execution_service import OrderExecutionService
from src.orders.position_tracker import PositionTracker
from src.orders.signal import Signal, SignalType
from src.orders.trade import Trade
from src.orders.trade_db_writer import TradeDBWriter


class TestTradeAuditIntegration:
    """Service-level integration tests for trade audit logging flow.

    Tests verify OrderExecutionService correctly calls TradeDBWriter methods
    with expected parameters. Uses mocked DB writer (not a real database).
    """

    @pytest.fixture
    def mock_zmq_adapter(self):
        """Create a mock ZMQ adapter."""
        adapter = AsyncMock()
        return adapter

    @pytest.fixture
    def position_tracker(self):
        """Create a position tracker."""
        return PositionTracker()

    @pytest.fixture
    def mock_trade_db_writer(self):
        """Create a mock TradeDBWriter."""
        writer = AsyncMock(spec=TradeDBWriter)
        writer.write_trade_entry = AsyncMock()
        writer.update_trade_exit = AsyncMock()
        return writer

    @pytest.fixture
    def execution_service(self, mock_zmq_adapter, position_tracker, mock_trade_db_writer):
        """Create OrderExecutionService with mock db writer."""
        return OrderExecutionService(
            zmq_adapter=mock_zmq_adapter,
            position_tracker=position_tracker,
            trade_db_writer=mock_trade_db_writer,
        )

    @pytest.mark.asyncio
    async def test_entry_trade_writes_to_db(
        self, execution_service, mock_zmq_adapter, mock_trade_db_writer
    ):
        """Test that entry trades are written to database via TradeDBWriter."""
        # Setup mock ZMQ response for successful fill
        fill_result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
            slippage=0.02,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=fill_result)

        # Create signal
        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
            metadata={"reason": "MA crossover (20/50)", "fast_ma": 1850.10},
        )

        # Execute signal
        order = await execution_service.execute_signal(
            signal=signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1850.25,
        )

        # Wait for async task to complete
        await asyncio.sleep(0.05)

        # Verify db writer was called with correct parameters
        mock_trade_db_writer.write_trade_entry.assert_called_once()
        call_args = mock_trade_db_writer.write_trade_entry.call_args

        # Verify strategy_name from Signal
        assert call_args.kwargs["strategy_name"] == "ma_crossover"

        # Verify signal_reason extracted from metadata
        assert call_args.kwargs["signal_reason"] == "MA crossover (20/50)"

        # Verify signal_metadata passed
        assert call_args.kwargs["signal_metadata"]["fast_ma"] == 1850.10

    @pytest.mark.asyncio
    async def test_close_trade_updates_db(
        self, execution_service, mock_zmq_adapter, mock_trade_db_writer
    ):
        """Test that position close updates trade record in database."""
        # First, execute an entry order
        entry_result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
            slippage=0.02,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=entry_result)

        entry_signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
            metadata={"reason": "Entry signal"},
        )

        await execution_service.execute_signal(
            signal=entry_signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1850.25,
        )

        # Wait for entry write
        await asyncio.sleep(0.05)

        # Now execute a close order
        close_result = OrderResult(
            order_id="test-order-002",
            status=OrderStatus.FILLED,
            fill_price=1858.50,
            slippage=0.01,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=close_result)

        close_signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
            metadata={"reason": "Exit signal"},
        )

        await execution_service.execute_signal(
            signal=close_signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1858.50,
        )

        # Wait for close update
        await asyncio.sleep(0.05)

        # Verify update_trade_exit was called
        mock_trade_db_writer.update_trade_exit.assert_called_once()
        call_args = mock_trade_db_writer.update_trade_exit.call_args

        # Verify exit details
        assert call_args.kwargs["exit_price"] == 1858.50
        assert call_args.kwargs["pnl_dollars"] is not None
        assert call_args.kwargs["pnl_percent"] is not None

    @pytest.mark.asyncio
    async def test_full_trade_lifecycle(
        self, execution_service, mock_zmq_adapter, mock_trade_db_writer
    ):
        """Test complete trade lifecycle: entry → hold → exit."""
        # Entry
        entry_result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
            slippage=0.02,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=entry_result)

        entry_signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
            metadata={"reason": "MA crossover triggered", "fast_ma": 1850.10},
        )

        entry_order = await execution_service.execute_signal(
            signal=entry_signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1850.25,
        )
        await asyncio.sleep(0.05)

        # Verify entry trade created
        assert len(execution_service.get_open_trades()) == 1
        entry_trade = execution_service.get_open_trades()[0]
        assert entry_trade.is_open

        # Close
        close_result = OrderResult(
            order_id="test-order-002",
            status=OrderStatus.FILLED,
            fill_price=1858.50,
            slippage=0.01,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=close_result)

        close_signal = Signal(
            signal_type=SignalType.CLOSE,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
            metadata={"reason": "Take profit triggered"},
        )

        await execution_service.execute_signal(
            signal=close_signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1858.50,
        )
        await asyncio.sleep(0.05)

        # Verify trade is now closed
        assert len(execution_service.get_open_trades()) == 0
        assert len(execution_service.get_closed_trades()) == 1

        # Verify the same trade was updated (not a new one created)
        closed_trade = execution_service.get_closed_trades()[0]
        assert closed_trade.trade_id == entry_trade.trade_id
        assert closed_trade.is_closed
        assert closed_trade.pnl_dollars is not None
        assert closed_trade.pnl_percent is not None

    @pytest.mark.asyncio
    async def test_db_write_is_fire_and_forget(
        self, execution_service, mock_zmq_adapter, mock_trade_db_writer
    ):
        """Test that DB write doesn't block order execution."""
        import time

        # Make the db writer slow
        async def slow_write(*args, **kwargs):
            await asyncio.sleep(0.1)  # 100ms delay

        mock_trade_db_writer.write_trade_entry = slow_write

        fill_result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
            slippage=0.02,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=fill_result)

        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
        )

        start = time.perf_counter()

        await execution_service.execute_signal(
            signal=signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1850.25,
        )

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should not wait for the 100ms db write
        assert elapsed_ms < 50, f"Order execution took {elapsed_ms:.2f}ms, expected < 50ms"

    @pytest.mark.asyncio
    async def test_no_db_write_without_writer(
        self, mock_zmq_adapter, position_tracker
    ):
        """Test that order execution works without db writer configured."""
        # Create service without db writer
        service = OrderExecutionService(
            zmq_adapter=mock_zmq_adapter,
            position_tracker=position_tracker,
            trade_db_writer=None,  # No writer
        )

        fill_result = OrderResult(
            order_id="test-order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
            slippage=0.02,
        )
        mock_zmq_adapter.send_order_and_wait = AsyncMock(return_value=fill_result)

        signal = Signal(
            signal_type=SignalType.BUY,
            symbol="XAUUSD",
            strategy_name="ma_crossover",
        )

        # Should not raise
        order = await service.execute_signal(
            signal=signal,
            account_id="ftmo-gold-001",
            volume=0.1,
            price=1850.25,
        )

        assert order.state.value == "filled"  # Check state instead of is_filled
        assert len(service.get_open_trades()) == 1


class TestTradeRecordFromTradeIntegration:
    """Integration tests for TradeRecord.from_trade() with real Trade objects."""

    def test_from_trade_with_order_execution_trade(self):
        """Test converting a Trade created by OrderExecutionService."""
        # Simulate a trade created during order execution
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
            slippage=0.02,
        )

        record = TradeRecord.from_trade(
            trade=trade,
            strategy_name="ma_crossover",
            signal_reason="MA crossover (20/50)",
            signal_metadata={"fast_ma": 1850.10, "slow_ma": 1849.80},
        )

        # Verify all fields
        assert record.account_id == trade.account_id
        assert record.symbol == trade.symbol
        assert record.side == "BUY"
        assert record.quantity == Decimal("0.1")
        assert record.entry_price == Decimal("1850.25")
        assert record.slippage_pips == Decimal("0.02")
        assert record.strategy_name == "ma_crossover"
        assert record.signal_reason == "MA crossover (20/50)"
        assert record.signal_metadata == {"fast_ma": 1850.10, "slow_ma": 1849.80}
        assert record.status == "open"

    def test_closed_trade_conversion(self):
        """Test converting a closed Trade."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
        )

        # Close the trade
        trade.close(exit_price=1858.50)

        record = TradeRecord.from_trade(
            trade=trade,
            strategy_name="ma_crossover",
        )

        assert record.status == "closed"
        assert record.exit_price == Decimal("1858.5")
        assert record.exit_time is not None
        assert record.pnl_dollars is not None
        assert record.pnl_percent is not None

    def test_decimal_precision_maintained(self):
        """Test that DECIMAL precision is maintained through conversion."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.12345678,  # High precision
            entry_price=1850.12345,  # High precision
            entry_time=datetime.now(timezone.utc),
            slippage=0.00001,
        )

        record = TradeRecord.from_trade(
            trade=trade,
            strategy_name="test",
        )

        # Values should be Decimal, preserving precision
        assert isinstance(record.quantity, Decimal)
        assert isinstance(record.entry_price, Decimal)
        assert isinstance(record.slippage_pips, Decimal)


class TestPnLCalculation:
    """Tests for PnL calculation in trade updates."""

    def test_buy_position_profit(self):
        """Test PnL calculation for profitable BUY position."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(exit_price=1860.25)

        assert pnl_dollars > 0  # Profit
        assert pnl_percent > 0

    def test_buy_position_loss(self):
        """Test PnL calculation for losing BUY position."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(exit_price=1840.25)

        assert pnl_dollars < 0  # Loss
        assert pnl_percent < 0

    def test_sell_position_profit(self):
        """Test PnL calculation for profitable SELL position."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(exit_price=1840.25)

        assert pnl_dollars > 0  # Profit (price went down for short)
        assert pnl_percent > 0

    def test_sell_position_loss(self):
        """Test PnL calculation for losing SELL position."""
        trade = Trade(
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(exit_price=1860.25)

        assert pnl_dollars < 0  # Loss (price went up for short)
        assert pnl_percent < 0
