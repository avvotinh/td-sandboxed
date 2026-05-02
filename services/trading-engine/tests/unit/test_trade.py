"""Unit tests for Trade model."""

import pytest
from datetime import datetime, timedelta, timezone

from src.adapters.zmq_models import OrderSide
from src.orders.trade import Trade


class TestTradeCreation:
    """Tests for Trade model creation."""

    def test_create_open_trade(self):
        """Should create an open trade."""
        trade = Trade(
            order_id="order-123",
            account_id="ftmo-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        assert trade.order_id == "order-123"
        assert trade.account_id == "ftmo-001"
        assert trade.symbol == "XAUUSD"
        assert trade.side == OrderSide.BUY
        assert trade.quantity == 0.1
        assert trade.entry_price == 1850.00
        assert trade.is_open is True
        assert trade.is_closed is False

    def test_trade_id_auto_generated(self):
        """Trade ID should be auto-generated UUID."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        # UUID format: 8-4-4-4-12 hex chars
        assert len(trade.trade_id) == 36
        assert trade.trade_id.count("-") == 4

    def test_unique_trade_ids(self):
        """Each trade should have unique ID."""
        trades = [
            Trade(
                order_id=f"order-{i}",
                account_id="test",
                symbol="XAUUSD",
                side=OrderSide.BUY,
                quantity=0.1,
                entry_price=1850.00,
                entry_time=datetime.now(timezone.utc),
            )
            for i in range(3)
        ]

        trade_ids = [t.trade_id for t in trades]
        assert len(trade_ids) == len(set(trade_ids))

    def test_open_trade_defaults(self):
        """Open trade should have None for exit fields."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        assert trade.exit_price is None
        assert trade.exit_time is None
        assert trade.pnl_dollars is None
        assert trade.pnl_percent is None


class TestTradeClose:
    """Tests for closing trades."""

    def test_close_profitable_long(self):
        """Closing a profitable long trade should calculate positive PnL."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        trade.close(exit_price=1860.00)

        assert trade.is_closed is True
        assert trade.exit_price == 1860.00
        assert trade.pnl_dollars == pytest.approx(1.0)  # (1860-1850) * 0.1
        assert trade.is_profitable is True
        assert trade.is_loss is False

    def test_close_losing_long(self):
        """Closing a losing long trade should calculate negative PnL."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        trade.close(exit_price=1840.00)

        assert trade.is_closed is True
        assert trade.pnl_dollars == pytest.approx(-1.0)  # (1840-1850) * 0.1
        assert trade.is_loss is True
        assert trade.is_profitable is False

    def test_close_profitable_short(self):
        """Closing a profitable short trade should calculate positive PnL."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        trade.close(exit_price=1840.00)  # Price went down = profit for short

        assert trade.is_closed is True
        assert trade.pnl_dollars == pytest.approx(1.0)  # Short profit
        assert trade.is_profitable is True

    def test_close_losing_short(self):
        """Closing a losing short trade should calculate negative PnL."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        trade.close(exit_price=1860.00)  # Price went up = loss for short

        assert trade.is_closed is True
        assert trade.pnl_dollars == pytest.approx(-1.0)  # Short loss
        assert trade.is_loss is True

    def test_close_sets_exit_time(self):
        """Closing should set exit time to now if not provided."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        before = datetime.now(timezone.utc)
        trade.close(exit_price=1860.00)
        after = datetime.now(timezone.utc)

        assert before <= trade.exit_time <= after

    def test_close_with_custom_exit_time(self):
        """Closing should accept custom exit time."""
        entry = datetime(2025, 12, 22, 10, 0, 0)
        exit_time = datetime(2025, 12, 22, 11, 30, 0)

        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=entry,
        )

        trade.close(exit_price=1860.00, exit_time=exit_time)

        assert trade.exit_time == exit_time

    def test_close_with_slippage(self):
        """Closing should track slippage."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
            slippage=0.02,  # Entry slippage
        )

        trade.close(exit_price=1860.00, slippage=0.03)

        # Total slippage = entry + exit
        assert trade.slippage == pytest.approx(0.05)


class TestTradePnlCalculation:
    """Tests for PnL calculation method."""

    def test_calculate_pnl_long_profit(self):
        """Calculate PnL for long profitable trade."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=1.0,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(1870.00)

        assert pnl_dollars == pytest.approx(20.0)  # (1870-1850) * 1.0
        assert pnl_percent == pytest.approx(20.0 / 1850.0 * 100)

    def test_calculate_pnl_short_profit(self):
        """Calculate PnL for short profitable trade."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            quantity=1.0,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        pnl_dollars, pnl_percent = trade.calculate_pnl(1830.00)

        assert pnl_dollars == pytest.approx(20.0)  # Short: entry - exit
        assert pnl_percent == pytest.approx(20.0 / 1850.0 * 100)


class TestTradeDuration:
    """Tests for trade duration calculation."""

    def test_duration_open_trade(self):
        """Open trade should have None duration."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        assert trade.duration is None

    def test_duration_closed_trade(self):
        """Closed trade should have correct duration."""
        entry = datetime(2025, 12, 22, 10, 0, 0)
        exit_time = datetime(2025, 12, 22, 11, 30, 0)

        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=entry,
        )

        trade.close(exit_price=1860.00, exit_time=exit_time)

        assert trade.duration == pytest.approx(90 * 60)  # 90 minutes in seconds


class TestTradeRepr:
    """Tests for Trade string representation."""

    def test_repr_open_trade(self):
        """repr should show OPEN status for open trades."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )

        repr_str = repr(trade)
        assert "Trade" in repr_str
        assert "BUY" in repr_str
        assert "XAUUSD" in repr_str
        assert "OPEN" in repr_str
        assert "PnL" not in repr_str

    def test_repr_closed_trade(self):
        """repr should show CLOSED status with PnL."""
        trade = Trade(
            order_id="order-123",
            account_id="test",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=0.1,
            entry_price=1850.00,
            entry_time=datetime.now(timezone.utc),
        )
        trade.close(exit_price=1860.00)

        repr_str = repr(trade)
        assert "CLOSED" in repr_str
        assert "PnL=$" in repr_str
