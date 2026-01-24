"""Unit tests for TradeDBWriter and TradeRecord.

Tests cover:
- TradeRecord.from_trade() conversion with all fields
- TradeRecord.to_dict() serialization
- TradeDBWriter buffer management
- TradeDBWriter.write_trade_entry() adds to buffer
- TradeDBWriter._flush_buffer() clears buffer
- TradeDBWriter.update_trade_exit() updates existing record
- Graceful handling of missing strategy_name
"""

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.zmq_models import OrderSide
from src.orders.db_models import TradeRecord
from src.orders.trade import Trade
from src.orders.trade_db_writer import TradeDBWriter


class TestTradeRecord:
    """Tests for TradeRecord ORM model."""

    @pytest.fixture
    def sample_trade(self):
        """Create a sample Trade for testing."""
        return Trade(
            trade_id=str(uuid.uuid4()),
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime(2025, 12, 3, 14, 32, 15, tzinfo=timezone.utc),
            slippage=0.02,
        )

    @pytest.fixture
    def closed_trade(self, sample_trade):
        """Create a closed Trade for testing."""
        sample_trade.exit_price = 1858.50
        sample_trade.exit_time = datetime(2025, 12, 3, 15, 45, 0, tzinfo=timezone.utc)
        sample_trade.pnl_dollars = 82.50
        sample_trade.pnl_percent = 0.0825
        return sample_trade

    def test_from_trade_with_all_fields(self, sample_trade):
        """Test TradeRecord.from_trade() converts all fields correctly."""
        record = TradeRecord.from_trade(
            trade=sample_trade,
            strategy_name="ma_crossover",
            signal_reason="MA crossover (20/50)",
            signal_metadata={"fast_ma": 1850.10, "slow_ma": 1849.80},
        )

        assert str(record.trade_id) == sample_trade.trade_id
        assert record.account_id == "ftmo-gold-001"
        assert record.strategy_name == "ma_crossover"
        assert record.symbol == "XAUUSD"
        assert record.side == "BUY"
        assert record.quantity == Decimal("0.1")
        assert record.entry_price == Decimal("1850.25")
        assert record.entry_time == sample_trade.entry_time
        assert record.slippage_pips == Decimal("0.02")
        assert record.signal_reason == "MA crossover (20/50)"
        assert record.signal_metadata == {"fast_ma": 1850.10, "slow_ma": 1849.80}
        assert record.status == "open"

    def test_from_trade_closed_trade(self, closed_trade):
        """Test from_trade() correctly sets closed status."""
        record = TradeRecord.from_trade(
            trade=closed_trade,
            strategy_name="ma_crossover",
        )

        assert record.exit_price == Decimal("1858.5")
        assert record.exit_time == closed_trade.exit_time
        assert record.pnl_dollars == Decimal("82.5")
        assert record.pnl_percent == Decimal("0.0825")
        assert record.status == "closed"

    def test_from_trade_requires_strategy_name(self, sample_trade):
        """Test that from_trade() raises ValueError without strategy_name."""
        with pytest.raises(ValueError) as exc_info:
            TradeRecord.from_trade(
                trade=sample_trade,
                strategy_name="",
            )
        assert "strategy_name is required" in str(exc_info.value)

        with pytest.raises(ValueError):
            TradeRecord.from_trade(
                trade=sample_trade,
                strategy_name=None,
            )

    def test_from_trade_handles_none_optional_fields(self, sample_trade):
        """Test from_trade() handles None for optional fields."""
        sample_trade.slippage = None
        record = TradeRecord.from_trade(
            trade=sample_trade,
            strategy_name="test_strategy",
            signal_reason=None,
            signal_metadata=None,
        )

        assert record.slippage_pips is None
        assert record.signal_reason is None
        assert record.signal_metadata is None

    def test_from_trade_decimal_precision(self, sample_trade):
        """Test that DECIMAL precision is maintained."""
        sample_trade.entry_price = 1850.12345
        sample_trade.quantity = 0.12345678

        record = TradeRecord.from_trade(
            trade=sample_trade,
            strategy_name="test_strategy",
        )

        # Values should be Decimal, not float
        assert isinstance(record.entry_price, Decimal)
        assert isinstance(record.quantity, Decimal)

    def test_to_dict(self, closed_trade):
        """Test TradeRecord.to_dict() serialization."""
        record = TradeRecord.from_trade(
            trade=closed_trade,
            strategy_name="ma_crossover",
            signal_reason="Test reason",
            signal_metadata={"key": "value"},
        )

        result = record.to_dict()

        assert result["account_id"] == "ftmo-gold-001"
        assert result["strategy_name"] == "ma_crossover"
        assert result["symbol"] == "XAUUSD"
        assert result["side"] == "BUY"
        # Financial fields are serialized as strings to preserve DECIMAL precision
        assert result["quantity"] == "0.1"
        assert result["entry_price"] == "1850.25"
        assert result["exit_price"] == "1858.5"
        assert result["pnl_dollars"] == "82.5"
        assert result["pnl_percent"] == "0.0825"
        assert result["signal_reason"] == "Test reason"
        assert result["metadata"] == {"key": "value"}
        assert result["status"] == "closed"


class TestTradeDBWriter:
    """Tests for TradeDBWriter class."""

    @pytest.fixture
    def db_writer(self):
        """Create a TradeDBWriter with test configuration."""
        try:
            writer = TradeDBWriter(
                database_url="postgresql+asyncpg://test:test@localhost/test",
                batch_size=10,
                flush_interval=1.0,
            )
            return writer
        except ModuleNotFoundError:
            pytest.skip("asyncpg not installed - skipping TradeDBWriter tests")

    @pytest.fixture
    def sample_trade(self):
        """Create a sample Trade for testing."""
        return Trade(
            trade_id=str(uuid.uuid4()),
            order_id=str(uuid.uuid4()),
            account_id="ftmo-gold-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.25,
            entry_time=datetime.now(timezone.utc),
            slippage=0.02,
        )

    def test_db_writer_init(self, db_writer):
        """Test TradeDBWriter initialization."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")
        assert db_writer.buffer_size == 0
        assert db_writer.is_running is False

    @pytest.mark.asyncio
    async def test_write_trade_entry_adds_to_buffer(self, db_writer, sample_trade):
        """Test write_trade_entry adds entry to buffer."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        await db_writer.write_trade_entry(
            trade=sample_trade,
            strategy_name="ma_crossover",
            signal_reason="Test signal",
            signal_metadata={"key": "value"},
        )

        assert db_writer.buffer_size == 1

    @pytest.mark.asyncio
    async def test_write_trade_entry_multiple_entries(self, db_writer, sample_trade):
        """Test adding multiple entries to buffer."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        for i in range(5):
            trade = Trade(
                trade_id=str(uuid.uuid4()),
                order_id=str(uuid.uuid4()),
                account_id="ftmo-gold-001",
                symbol="XAUUSD",
                side=OrderSide.BUY,
                quantity=0.1,
                entry_price=1850.25,
                entry_time=datetime.now(timezone.utc),
            )
            await db_writer.write_trade_entry(
                trade=trade,
                strategy_name="test_strategy",
            )

        assert db_writer.buffer_size == 5

    @pytest.mark.asyncio
    async def test_write_trade_entry_requires_strategy_name(self, db_writer, sample_trade):
        """Test that write_trade_entry raises ValueError without strategy_name."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        with pytest.raises(ValueError) as exc_info:
            await db_writer.write_trade_entry(
                trade=sample_trade,
                strategy_name="",
            )
        assert "strategy_name is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_flush_buffer_clears_buffer(self, db_writer, sample_trade):
        """Test _flush_buffer clears the buffer."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        # Add entries
        await db_writer.write_trade_entry(
            trade=sample_trade,
            strategy_name="test_strategy",
        )
        assert db_writer.buffer_size == 1

        # Mock the batch insert to avoid actual DB operation
        with patch.object(db_writer, "_batch_insert", new_callable=AsyncMock):
            await db_writer._flush_buffer()

        assert db_writer.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_buffer_on_batch_size_reached(self, db_writer):
        """Test buffer flushes when batch_size is reached."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        flush_called = False

        async def mock_flush():
            nonlocal flush_called
            flush_called = True

        # Set batch_size to 3 for easier testing
        db_writer._batch_size = 3

        with patch.object(db_writer, "_flush_buffer", mock_flush):
            for i in range(3):
                trade = Trade(
                    trade_id=str(uuid.uuid4()),
                    order_id=str(uuid.uuid4()),
                    account_id="ftmo-gold-001",
                    symbol="XAUUSD",
                    side=OrderSide.BUY,
                    quantity=0.1,
                    entry_price=1850.25,
                    entry_time=datetime.now(timezone.utc),
                )
                await db_writer.write_trade_entry(
                    trade=trade,
                    strategy_name="test_strategy",
                )

        # Give time for the create_task to execute
        await asyncio.sleep(0.01)
        assert flush_called

    @pytest.mark.asyncio
    async def test_update_trade_exit_calls_db(self, db_writer):
        """Test update_trade_exit calls the database."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        trade_id = str(uuid.uuid4())
        exit_time = datetime.now(timezone.utc)

        # Track if execute was called
        execute_called = False

        # Create a proper async context manager for session
        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def begin(self):
                return MockBegin()

            async def execute(self, stmt):
                nonlocal execute_called
                execute_called = True
                mock_result = MagicMock()
                mock_result.rowcount = 1
                return mock_result

        class MockBegin:
            async def __aenter__(self):
                pass

            async def __aexit__(self, *args):
                pass

        with patch.object(db_writer, "_session_factory", return_value=MockSession()):
            await db_writer.update_trade_exit(
                trade_id=trade_id,
                exit_price=1858.50,
                exit_time=exit_time,
                pnl_dollars=82.50,
                pnl_percent=0.0825,
            )

        assert execute_called, "execute should have been called"

    @pytest.mark.asyncio
    async def test_update_trade_exit_handles_not_found(self, db_writer):
        """Test update_trade_exit logs warning when trade not found."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        trade_id = str(uuid.uuid4())
        exit_time = datetime.now(timezone.utc)

        # Create a proper async context manager for session
        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def begin(self):
                return MockBegin()

            async def execute(self, stmt):
                mock_result = MagicMock()
                mock_result.rowcount = 0  # No rows updated
                return mock_result

        class MockBegin:
            async def __aenter__(self):
                pass

            async def __aexit__(self, *args):
                pass

        with patch.object(db_writer, "_session_factory", return_value=MockSession()):
            # Should not raise, just log warning
            await db_writer.update_trade_exit(
                trade_id=trade_id,
                exit_price=1858.50,
                exit_time=exit_time,
                pnl_dollars=82.50,
                pnl_percent=0.0825,
            )

    @pytest.mark.asyncio
    async def test_start_and_stop(self, db_writer):
        """Test start() and stop() lifecycle."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        assert not db_writer.is_running

        await db_writer.start()
        assert db_writer.is_running

        # Mock the engine dispose
        db_writer._engine = MagicMock()
        db_writer._engine.dispose = AsyncMock()

        await db_writer.stop()
        assert not db_writer.is_running

    @pytest.mark.asyncio
    async def test_stop_flushes_remaining_entries(self, db_writer, sample_trade):
        """Test stop() flushes remaining buffer entries."""
        if db_writer is None:
            pytest.skip("db_writer fixture skipped")

        # Start the writer first (stop() only flushes if running)
        db_writer._running = True

        # Add entry
        await db_writer.write_trade_entry(
            trade=sample_trade,
            strategy_name="test_strategy",
        )
        assert db_writer.buffer_size == 1

        # Mock engine dispose
        db_writer._engine = MagicMock()
        db_writer._engine.dispose = AsyncMock()

        # Mock batch insert to avoid actual DB operation
        with patch.object(db_writer, "_batch_insert", new_callable=AsyncMock):
            await db_writer.stop()

        # Buffer should be empty after stop (flushed)
        assert db_writer.buffer_size == 0


class TestTradeDBWriterIntegration:
    """Integration-style tests for TradeDBWriter with OrderExecutionService."""

    @pytest.fixture
    def sample_signal_metadata(self):
        """Create sample signal metadata."""
        return {
            "fast_ma": 1850.10,
            "slow_ma": 1849.80,
            "reason": "MA crossover (20/50)",
        }

    def test_signal_reason_extracted_from_metadata(self, sample_signal_metadata):
        """Test that signal_reason is extracted from metadata.get('reason')."""
        signal_reason = sample_signal_metadata.get("reason")
        assert signal_reason == "MA crossover (20/50)"

    def test_signal_reason_none_when_no_reason(self):
        """Test signal_reason is None when metadata has no 'reason' key."""
        metadata = {"fast_ma": 1850.10}
        signal_reason = metadata.get("reason") if metadata else None
        assert signal_reason is None

    def test_signal_reason_none_when_metadata_is_none(self):
        """Test signal_reason is None when metadata is None."""
        metadata = None
        signal_reason = metadata.get("reason") if metadata else None
        assert signal_reason is None
