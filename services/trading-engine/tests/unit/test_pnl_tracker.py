"""Unit tests for PnLTracker and related classes.

Tests:
- Unrealized P&L calculation for LONG positions
- Unrealized P&L calculation for SHORT positions
- Equity updates on tick
- Daily realized P&L accumulation
- Daily P&L = realized + unrealized
- Tick with no matching positions (fast no-op)
- Decimal precision (no floating point errors)
- Account isolation (update one tracker doesn't affect another)
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.pnl_tracker import (
    PnLMetrics,
    PnLTracker,
    Position,
    get_multiplier,
)
from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus


@pytest.fixture
def mock_risk_registry():
    """Create mock RiskStateRegistry."""
    registry = MagicMock()
    registry.update_account_equity = AsyncMock()
    registry.record_account_trade = AsyncMock()
    registry.get_risk_state = MagicMock(return_value=None)
    return registry


@pytest.fixture
def mock_redis():
    """Create mock RedisStateManager."""
    redis = MagicMock()
    redis.save_account_balance = AsyncMock()
    return redis


@pytest.fixture
def pnl_tracker(mock_risk_registry):
    """Create PnLTracker with mock dependencies."""
    return PnLTracker(
        account_id="test-account",
        initial_balance=Decimal("100000"),
        risk_registry=mock_risk_registry,
    )


class TestGetMultiplier:
    """Tests for get_multiplier function."""

    def test_forex_pair_returns_one(self):
        """Forex pairs should return multiplier of 1.0."""
        assert get_multiplier("EURUSD") == Decimal("1.0")
        assert get_multiplier("XAUUSD") == Decimal("1.0")
        assert get_multiplier("GBPJPY") == Decimal("1.0")


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        """Position should be created with correct fields."""
        position = Position(
            position_id="order-123",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("0.10"),
            entry_price=Decimal("1850.00"),
        )

        assert position.position_id == "order-123"
        assert position.symbol == "XAUUSD"
        assert position.side == OrderSide.BUY
        assert position.volume == Decimal("0.10")
        assert position.entry_price == Decimal("1850.00")
        assert position.current_price == Decimal("0")
        assert position.unrealized_pnl == Decimal("0")
        assert isinstance(position.open_time, datetime)


class TestPnLTracker:
    """Tests for PnLTracker class."""

    def test_initialization(self, mock_risk_registry):
        """PnLTracker should initialize with correct state."""
        tracker = PnLTracker(
            account_id="test-account",
            initial_balance=Decimal("100000"),
            risk_registry=mock_risk_registry,
        )

        assert tracker.account_id == "test-account"
        assert tracker.balance == Decimal("100000")
        assert tracker.equity == Decimal("100000")
        assert tracker.get_open_positions_count() == 0
        assert tracker.get_total_exposure() == Decimal("0")

    def test_calculate_unrealized_pnl_long_profit(self, pnl_tracker):
        """LONG position profit: current > entry."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )

        # Price goes up - profit for long
        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1860.00"))

        # (1860 - 1850) * 1.0 * 1.0 = 10.00
        assert pnl == Decimal("10.00")

    def test_calculate_unrealized_pnl_long_loss(self, pnl_tracker):
        """LONG position loss: current < entry."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )

        # Price goes down - loss for long
        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1840.00"))

        # (1840 - 1850) * 1.0 * 1.0 = -10.00
        assert pnl == Decimal("-10.00")

    def test_calculate_unrealized_pnl_short_profit(self, pnl_tracker):
        """SHORT position profit: current < entry."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )

        # Price goes down - profit for short
        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1840.00"))

        # (1850 - 1840) * 1.0 * 1.0 = 10.00
        assert pnl == Decimal("10.00")

    def test_calculate_unrealized_pnl_short_loss(self, pnl_tracker):
        """SHORT position loss: current > entry."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )

        # Price goes up - loss for short
        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1860.00"))

        # (1850 - 1860) * 1.0 * 1.0 = -10.00
        assert pnl == Decimal("-10.00")

    def test_calculate_unrealized_pnl_with_volume(self, pnl_tracker):
        """P&L should scale with volume."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("0.5"),  # Half a lot
            entry_price=Decimal("1850.00"),
        )

        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1860.00"))

        # (1860 - 1850) * 0.5 * 1.0 = 5.00
        assert pnl == Decimal("5.00")

    @pytest.mark.asyncio
    async def test_on_tick_no_positions(self, pnl_tracker, mock_risk_registry):
        """Tick with no matching positions should be a no-op."""
        await pnl_tracker.on_tick("XAUUSD", Decimal("1850.00"), Decimal("1850.50"))

        # Should NOT call update_equity since no positions
        mock_risk_registry.update_account_equity.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_tick_updates_pnl(self, pnl_tracker, mock_risk_registry):
        """Tick should update unrealized P&L for matching positions."""
        # Add a position manually
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        pnl_tracker._positions["order-1"] = position

        # Tick with price up (profit for long)
        await pnl_tracker.on_tick("XAUUSD", Decimal("1860.00"), Decimal("1860.50"))

        # Long uses bid for mark-to-market (conservative)
        # But story says: LONG positions use ASK, SHORT use BID
        # Actually story says: LONG: exit at bid, SHORT: exit at ask
        # So long uses bid = 1860.00
        assert position.unrealized_pnl == Decimal("10.00")
        assert pnl_tracker.equity == Decimal("100010.00")

        # Should update risk registry
        mock_risk_registry.update_account_equity.assert_called_with(
            "test-account", Decimal("100010.00")
        )

    @pytest.mark.asyncio
    async def test_on_tick_uses_bid_for_long(self, pnl_tracker, mock_risk_registry):
        """LONG positions should use bid price (worst exit) for mark-to-market."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        pnl_tracker._positions["order-1"] = position

        # Bid = 1860.00, Ask = 1860.50
        await pnl_tracker.on_tick("XAUUSD", Decimal("1860.00"), Decimal("1860.50"))

        # Long uses bid (lower) = 1860.00
        assert position.current_price == Decimal("1860.00")
        assert position.unrealized_pnl == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_on_tick_uses_ask_for_short(self, pnl_tracker, mock_risk_registry):
        """SHORT positions should use ask price (worst exit) for mark-to-market."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.SELL,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        pnl_tracker._positions["order-1"] = position

        # Bid = 1840.00, Ask = 1840.50
        await pnl_tracker.on_tick("XAUUSD", Decimal("1840.00"), Decimal("1840.50"))

        # Short uses ask (higher) = 1840.50
        assert position.current_price == Decimal("1840.50")
        # (1850 - 1840.50) * 1.0 = 9.50
        assert position.unrealized_pnl == Decimal("9.50")

    @pytest.mark.asyncio
    async def test_on_trade_executed_creates_position(
        self, pnl_tracker, mock_risk_registry
    ):
        """Trade execution should create new position."""
        order = Order(
            account_id="test-account",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.5,
            price=1850.00,
            order_id="order-123",
        )
        result = OrderResult(
            order_id="order-123",
            status=OrderStatus.FILLED,
            fill_price=1850.25,
        )

        await pnl_tracker.on_trade_executed(result, order)

        assert pnl_tracker.get_open_positions_count() == 1
        position = pnl_tracker._positions["order-123"]
        assert position.symbol == "XAUUSD"
        assert position.side == OrderSide.BUY
        assert position.volume == Decimal("0.5")
        assert position.entry_price == Decimal("1850.25")

    @pytest.mark.asyncio
    async def test_on_trade_executed_not_filled_skips(
        self, pnl_tracker, mock_risk_registry
    ):
        """Non-filled order should not create position."""
        order = Order(
            account_id="test-account",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=0.5,
            price=1850.00,
            order_id="order-123",
        )
        result = OrderResult(
            order_id="order-123",
            status=OrderStatus.REJECTED,
            error="Insufficient margin",
        )

        await pnl_tracker.on_trade_executed(result, order)

        assert pnl_tracker.get_open_positions_count() == 0

    @pytest.mark.asyncio
    async def test_on_position_closed_removes_and_updates(
        self, pnl_tracker, mock_risk_registry
    ):
        """Position close should remove position and update P&L."""
        # Add position first
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
            unrealized_pnl=Decimal("10.00"),
        )
        pnl_tracker._positions["order-1"] = position

        realized_pnl = Decimal("15.00")
        await pnl_tracker.on_position_closed(
            "order-1", Decimal("1865.00"), realized_pnl
        )

        # Position removed
        assert pnl_tracker.get_open_positions_count() == 0
        assert "order-1" not in pnl_tracker._positions

        # Daily P&L updated
        assert pnl_tracker._daily_realized_pnl == Decimal("15.00")

        # Balance updated
        assert pnl_tracker.balance == Decimal("100015.00")

        # Risk registry notified
        mock_risk_registry.record_account_trade.assert_called_with(
            "test-account", realized_pnl
        )

    @pytest.mark.asyncio
    async def test_on_position_closed_unknown_position(
        self, pnl_tracker, mock_risk_registry
    ):
        """Closing unknown position should be handled gracefully."""
        await pnl_tracker.on_position_closed(
            "unknown-order", Decimal("1865.00"), Decimal("15.00")
        )

        # Should not error, just log warning
        assert pnl_tracker.balance == Decimal("100000")

    def test_get_pnl_metrics(self, pnl_tracker):
        """get_pnl_metrics should return correct snapshot."""
        # Add a position with unrealized P&L
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
            unrealized_pnl=Decimal("10.00"),
        )
        pnl_tracker._positions["order-1"] = position
        pnl_tracker._daily_realized_pnl = Decimal("5.00")
        pnl_tracker._current_equity = Decimal("100010.00")

        metrics = pnl_tracker.get_pnl_metrics()

        assert isinstance(metrics, PnLMetrics)
        assert metrics.current_equity == Decimal("100010.00")
        assert metrics.balance == Decimal("100000")
        assert metrics.unrealized_pnl == Decimal("10.00")
        assert metrics.daily_pnl == Decimal("15.00")  # 5.00 realized + 10.00 unrealized
        assert metrics.open_positions_count == 1

    def test_get_pnl_metrics_daily_pnl_percent(self, pnl_tracker, mock_risk_registry):
        """Daily P&L percent should be calculated from starting balance."""
        # Set up risk state with daily starting balance
        mock_state = MagicMock()
        mock_state.daily_starting_balance = Decimal("100000")
        mock_state.total_drawdown_percent = Decimal("0")
        mock_risk_registry.get_risk_state.return_value = mock_state

        pnl_tracker._daily_realized_pnl = Decimal("1000")  # 1% profit

        metrics = pnl_tracker.get_pnl_metrics()

        # 1000 / 100000 * 100 = 1%
        assert metrics.daily_pnl_percent == Decimal("1")

    def test_has_position_for_symbol(self, pnl_tracker):
        """has_position_for_symbol should return correct result."""
        assert not pnl_tracker.has_position_for_symbol("XAUUSD")

        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        pnl_tracker._positions["order-1"] = position

        assert pnl_tracker.has_position_for_symbol("XAUUSD")
        assert not pnl_tracker.has_position_for_symbol("EURUSD")

    def test_get_total_exposure(self, pnl_tracker):
        """get_total_exposure should sum position values."""
        position1 = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        position2 = Position(
            position_id="order-2",
            symbol="EURUSD",
            side=OrderSide.SELL,
            volume=Decimal("0.5"),
            entry_price=Decimal("1.1000"),
        )
        pnl_tracker._positions["order-1"] = position1
        pnl_tracker._positions["order-2"] = position2

        exposure = pnl_tracker.get_total_exposure()

        # 1.0 * 1850.00 + 0.5 * 1.1000 = 1850.55
        assert exposure == Decimal("1850.55")


class TestDecimalPrecision:
    """Tests for Decimal precision requirements."""

    def test_no_floating_point_errors(self, pnl_tracker):
        """Calculations should not suffer from floating point errors."""
        # Classic floating point error case: 0.1 + 0.2 != 0.3
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("0.1"),
            entry_price=Decimal("0.1"),
        )

        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("0.3"))

        # (0.3 - 0.1) * 0.1 = 0.02 exactly
        assert pnl == Decimal("0.02")
        # String repr may have trailing zeros, but value is exact
        assert pnl == Decimal("0.020")

    def test_large_number_precision(self, pnl_tracker):
        """Large numbers should maintain precision."""
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("100.0"),
            entry_price=Decimal("1234567.89"),
        )

        pnl = pnl_tracker.calculate_unrealized_pnl(position, Decimal("1234567.99"))

        # (1234567.99 - 1234567.89) * 100.0 = 10.00
        assert pnl == Decimal("10.00")


class TestAccountIsolation:
    """Tests for account isolation between trackers."""

    @pytest.mark.asyncio
    async def test_trackers_are_isolated(self, mock_risk_registry):
        """Updates to one tracker should not affect another."""
        tracker_a = PnLTracker(
            account_id="account-a",
            initial_balance=Decimal("100000"),
            risk_registry=mock_risk_registry,
        )
        tracker_b = PnLTracker(
            account_id="account-b",
            initial_balance=Decimal("50000"),
            risk_registry=mock_risk_registry,
        )

        # Add position to tracker A
        position = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        tracker_a._positions["order-1"] = position

        # Update tracker A
        await tracker_a.on_tick("XAUUSD", Decimal("1860.00"), Decimal("1860.50"))

        # Tracker B should be unaffected
        assert tracker_b.balance == Decimal("50000")
        assert tracker_b.equity == Decimal("50000")
        assert tracker_b.get_open_positions_count() == 0

        # Tracker A should be updated
        assert tracker_a.equity == Decimal("100010.00")

    @pytest.mark.asyncio
    async def test_close_in_one_tracker_doesnt_affect_other(self, mock_risk_registry):
        """Position close in one tracker should not affect another."""
        tracker_a = PnLTracker(
            account_id="account-a",
            initial_balance=Decimal("100000"),
            risk_registry=mock_risk_registry,
        )
        tracker_b = PnLTracker(
            account_id="account-b",
            initial_balance=Decimal("50000"),
            risk_registry=mock_risk_registry,
        )

        # Add positions to both
        tracker_a._positions["order-1"] = Position(
            position_id="order-1",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        tracker_b._positions["order-2"] = Position(
            position_id="order-2",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("0.5"),
            entry_price=Decimal("1850.00"),
        )

        # Close position in tracker A
        await tracker_a.on_position_closed(
            "order-1", Decimal("1860.00"), Decimal("10.00")
        )

        # Tracker A closed
        assert tracker_a.get_open_positions_count() == 0

        # Tracker B unchanged
        assert tracker_b.get_open_positions_count() == 1
        assert "order-2" in tracker_b._positions
