"""Integration tests for P&L tracking system.

Tests the full integration of:
- PnLTracker with RiskStateRegistry
- PnLTrackerRegistry for multi-account management
- ZmqAdapter tick routing
- AccountMetricsService integration
- Performance requirements
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.pnl_registry import PnLTrackerRegistry
from src.accounts.pnl_tracker import PnLTracker, Position
from src.accounts.risk_registry import RiskStateRegistry
from src.accounts.risk_state import RiskState
from src.adapters.zmq_models import Order, OrderResult, OrderSide, OrderStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_redis():
    """Create mock RedisStateManager for testing."""
    redis = MagicMock()
    redis.get_risk_state = AsyncMock(return_value=None)
    redis.save_risk_state = AsyncMock()
    redis.record_risk_violation = AsyncMock()
    redis.get_account_balance = AsyncMock(return_value=None)
    redis.save_account_balance = AsyncMock()
    return redis


@pytest.fixture
def risk_registry(mock_redis):
    """Create RiskStateRegistry for testing."""
    return RiskStateRegistry(mock_redis)


@pytest.fixture
def pnl_registry(risk_registry, mock_redis):
    """Create PnLTrackerRegistry for testing."""
    return PnLTrackerRegistry(risk_registry, mock_redis)


class TestFullFlow:
    """Integration tests for complete P&L tracking flow."""

    async def test_open_position_tick_update_pnl_changes(
        self, pnl_registry, risk_registry
    ):
        """Test: open position -> tick update -> P&L changes (AC: 1-3)."""
        # Create tracker for account
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Simulate order execution
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )

        # Execute trade
        await tracker.on_trade_executed(result, order)

        # Verify position created
        assert tracker.get_open_positions_count() == 1
        assert tracker.equity == Decimal("100000")  # No unrealized yet

        # Simulate tick update - price goes up
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # Verify P&L updated (LONG uses bid = 1860.00)
        # P&L = (1860.00 - 1850.00) * 1.0 = 10.00
        position = tracker._positions["order-001"]
        assert position.unrealized_pnl == Decimal("10.00")
        assert tracker.equity == Decimal("100010.00")

    async def test_open_tick_close_realized_pnl_correct(
        self, pnl_registry, risk_registry
    ):
        """Test: open -> tick -> close -> realized P&L correct (AC: 2-3)."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Open position
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker.on_trade_executed(result, order)

        # Update with tick
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # Close position with realized P&L
        realized_pnl = Decimal("10.00")
        await tracker.on_position_closed(
            "order-001", Decimal("1860.00"), realized_pnl
        )

        # Verify realized P&L recorded
        assert tracker._daily_realized_pnl == Decimal("10.00")
        assert tracker.balance == Decimal("100010.00")
        assert tracker.get_open_positions_count() == 0

        # Equity should now equal balance (no open positions)
        assert tracker.equity == Decimal("100010.00")

    async def test_multiple_positions_same_symbol(
        self, pnl_registry, risk_registry
    ):
        """Test multiple positions on same symbol (AC: 1)."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Open two positions
        for i in range(2):
            order = Order(
                account_id="ftmo-001",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.5,
                price=1850.00,
                order_id=f"order-{i}",
            )
            result = OrderResult(
                order_id=f"order-{i}",
                status=OrderStatus.FILLED,
                fill_price=1850.00,
            )
            await tracker.on_trade_executed(result, order)

        assert tracker.get_open_positions_count() == 2

        # Tick update affects both positions
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # Each position: (1860 - 1850) * 0.5 = 5.00
        # Total unrealized = 10.00
        metrics = tracker.get_pnl_metrics()
        assert metrics.unrealized_pnl == Decimal("10.00")
        assert metrics.current_equity == Decimal("100010.00")


class TestConcurrentAccountUpdates:
    """Tests for concurrent updates to multiple accounts (AC: 6)."""

    async def test_concurrent_tick_updates_multiple_accounts(
        self, pnl_registry, risk_registry
    ):
        """Test concurrent tick updates for multiple accounts."""
        # Create trackers for multiple accounts
        trackers = {}
        for i in range(3):
            account_id = f"account-{i}"
            tracker = await pnl_registry.get_or_create(
                account_id, Decimal("100000")
            )
            trackers[account_id] = tracker

            # Add position to each
            order = Order(
                account_id=account_id,
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=1.0,
                price=1850.00,
                order_id=f"order-{i}",
            )
            result = OrderResult(
                order_id=f"order-{i}",
                status=OrderStatus.FILLED,
                fill_price=1850.00,
            )
            await tracker.on_trade_executed(result, order)

        # Broadcast tick to all accounts
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # All accounts should be updated
        for account_id, tracker in trackers.items():
            assert tracker.equity == Decimal("100010.00")

    async def test_update_one_account_doesnt_affect_other(
        self, pnl_registry, risk_registry
    ):
        """Test that updating one account's P&L doesn't affect another (AC: 6)."""
        # Create two trackers
        tracker_a = await pnl_registry.get_or_create(
            "account-a", Decimal("100000")
        )
        tracker_b = await pnl_registry.get_or_create(
            "account-b", Decimal("50000")
        )

        # Add position only to account A
        order = Order(
            account_id="account-a",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-a",
        )
        result = OrderResult(
            order_id="order-a",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker_a.on_trade_executed(result, order)

        # Tick update
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # Account A updated
        assert tracker_a.equity == Decimal("100010.00")

        # Account B unchanged
        assert tracker_b.balance == Decimal("50000")
        assert tracker_b.equity == Decimal("50000")
        assert tracker_b.get_open_positions_count() == 0


class TestRiskStateIntegration:
    """Tests for integration with RiskStateRegistry (AC: 4)."""

    async def test_equity_updates_propagate_to_risk_registry(
        self, pnl_registry, risk_registry
    ):
        """Test that equity updates propagate to RiskStateRegistry."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Initialize risk state
        await risk_registry.get_or_create("ftmo-001")

        # Add position
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker.on_trade_executed(result, order)

        # Tick update triggers equity update to risk registry
        await pnl_registry.on_tick_all(
            "XAUUSD", Decimal("1860.00"), Decimal("1860.50")
        )

        # Verify risk state updated
        risk_state = risk_registry.get_risk_state("ftmo-001")
        assert risk_state is not None
        assert risk_state.current_equity == Decimal("100010.00")

    async def test_realized_pnl_recorded_via_risk_registry(
        self, pnl_registry, risk_registry
    ):
        """Test that realized P&L is recorded via risk registry."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Initialize risk state with starting balance
        manager = await risk_registry.get_or_create("ftmo-001")
        manager.state.daily_starting_balance = Decimal("100000")
        manager.state.current_equity = Decimal("100000")

        # Add position
        position = Position(
            position_id="order-001",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=Decimal("1.0"),
            entry_price=Decimal("1850.00"),
        )
        tracker._positions["order-001"] = position

        # Close with profit
        await tracker.on_position_closed(
            "order-001", Decimal("1860.00"), Decimal("10.00")
        )

        # Verify daily P&L updated in risk state
        risk_state = risk_registry.get_risk_state("ftmo-001")
        assert risk_state.daily_pnl == Decimal("10.00")


class TestPerformance:
    """Performance tests for tick processing (AC: 5)."""

    async def test_tick_processing_under_10ms(self, pnl_registry, risk_registry):
        """Test that tick processing stays under 10ms per tick."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Add 10 positions
        for i in range(10):
            order = Order(
                account_id="ftmo-001",
                action=OrderSide.BUY,
                symbol="XAUUSD",
                volume=0.1,
                price=1850.00,
                order_id=f"order-{i}",
            )
            result = OrderResult(
                order_id=f"order-{i}",
                status=OrderStatus.FILLED,
                fill_price=1850.00,
            )
            await tracker.on_trade_executed(result, order)

        # Measure tick processing time
        start = time.perf_counter()
        await tracker.on_tick("XAUUSD", Decimal("1860.00"), Decimal("1860.50"))
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should be well under 10ms
        assert elapsed_ms < 10, f"Tick processing took {elapsed_ms:.1f}ms"

    async def test_1000_ticks_under_10_seconds(self, pnl_registry, risk_registry):
        """Test: 1000 ticks processed in < 10 seconds (AC: 5)."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Add a position
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker.on_trade_executed(result, order)

        # Process 1000 ticks
        start = time.perf_counter()
        for i in range(1000):
            bid = Decimal("1850.00") + Decimal(str(i % 100)) / 100
            ask = bid + Decimal("0.50")
            await tracker.on_tick("XAUUSD", bid, ask)
        total_time = time.perf_counter() - start

        # Should complete in under 10 seconds
        assert total_time < 10, f"1000 ticks took {total_time:.2f}s"

        # Average per tick should be under 10ms
        avg_ms = (total_time / 1000) * 1000
        assert avg_ms < 10, f"Average tick time: {avg_ms:.2f}ms"

    async def test_no_position_tick_is_fast_noop(
        self, pnl_registry, risk_registry
    ):
        """Test that tick with no matching positions is a fast no-op."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # No positions added

        # Measure tick processing time
        start = time.perf_counter()
        await tracker.on_tick("XAUUSD", Decimal("1860.00"), Decimal("1860.50"))
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should be extremely fast (< 1ms)
        assert elapsed_ms < 1, f"Empty tick took {elapsed_ms:.3f}ms"


class TestPnLTrackerRegistry:
    """Tests for PnLTrackerRegistry functionality."""

    async def test_get_or_create_creates_tracker(
        self, pnl_registry, risk_registry
    ):
        """get_or_create should create new tracker."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        assert tracker is not None
        assert tracker.account_id == "ftmo-001"
        assert tracker.balance == Decimal("100000")

    async def test_get_or_create_returns_existing(
        self, pnl_registry, risk_registry
    ):
        """get_or_create should return existing tracker."""
        tracker1 = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )
        tracker2 = await pnl_registry.get_or_create("ftmo-001")

        assert tracker1 is tracker2

    async def test_get_returns_none_for_unknown(
        self, pnl_registry, risk_registry
    ):
        """get should return None for unknown account."""
        tracker = pnl_registry.get("unknown-account")
        assert tracker is None

    async def test_get_open_positions_count(
        self, pnl_registry, risk_registry
    ):
        """get_open_positions_count should return correct count."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Initially 0
        assert pnl_registry.get_open_positions_count("ftmo-001") == 0

        # Add position
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker.on_trade_executed(result, order)

        assert pnl_registry.get_open_positions_count("ftmo-001") == 1

    async def test_get_total_exposure(self, pnl_registry, risk_registry):
        """get_total_exposure should return correct exposure."""
        tracker = await pnl_registry.get_or_create(
            "ftmo-001", Decimal("100000")
        )

        # Initially 0
        assert pnl_registry.get_total_exposure("ftmo-001") == Decimal("0")

        # Add position
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )
        result = OrderResult(
            order_id="order-001",
            status=OrderStatus.FILLED,
            fill_price=1850.00,
        )
        await tracker.on_trade_executed(result, order)

        # Exposure = 1.0 * 1850.00 = 1850.00
        assert pnl_registry.get_total_exposure("ftmo-001") == Decimal("1850.00")


class TestValidatedAdapterIntegration:
    """Tests for ValidatedZmqAdapter integration with P&L tracking."""

    async def test_send_order_and_wait_creates_position(
        self, pnl_registry, risk_registry
    ):
        """Test that send_order_and_wait() correctly notifies PnL tracker."""
        from unittest.mock import AsyncMock, MagicMock

        from src.execution.order_validator import OrderValidator
        from src.execution.validated_adapter import ValidatedZmqAdapter

        # Create mock ZmqAdapter that returns a filled result
        mock_zmq = MagicMock()
        mock_zmq.send_order_and_wait = AsyncMock(
            return_value=OrderResult(
                order_id="order-001",
                status=OrderStatus.FILLED,
                fill_price=1850.00,
            )
        )

        # Create mock validator that allows all orders
        mock_validator = MagicMock(spec=OrderValidator)
        mock_validation_result = MagicMock()
        mock_validation_result.is_blocked = False
        mock_validation_result.has_warnings = False
        mock_validation_result.evaluation_time_ms = 1.0
        mock_validator.validate_order = AsyncMock(return_value=mock_validation_result)

        # Create ValidatedZmqAdapter with PnL registry
        validated_adapter = ValidatedZmqAdapter(
            zmq_adapter=mock_zmq,
            order_validator=mock_validator,
            risk_registry=risk_registry,
            pnl_registry=pnl_registry,
        )

        # Create order
        order = Order(
            account_id="ftmo-001",
            action=OrderSide.BUY,
            symbol="XAUUSD",
            volume=1.0,
            price=1850.00,
            order_id="order-001",
        )

        # Initialize tracker for account
        await pnl_registry.get_or_create("ftmo-001", Decimal("100000"))

        # Send order through ValidatedZmqAdapter
        result = await validated_adapter.send_order_and_wait(order)

        # Verify order was filled
        assert result.status == OrderStatus.FILLED

        # Verify position was created in PnL tracker
        tracker = pnl_registry.get("ftmo-001")
        assert tracker is not None
        assert tracker.get_open_positions_count() == 1

        # Verify position details
        position = tracker._positions.get("order-001")
        assert position is not None
        assert position.symbol == "XAUUSD"
        assert position.side == OrderSide.BUY
        assert position.volume == Decimal("1.0")
        assert position.entry_price == Decimal("1850.0")
