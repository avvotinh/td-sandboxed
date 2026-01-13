"""Integration tests for DailyPnLRecalculator with Redis.

These tests verify the P&L recalculation integrates correctly with Redis
state persistence and risk state management.

Requires a running Redis instance. Set TEST_REDIS_URL environment variable.

Run with:
    uv run pytest tests/integration/test_daily_pnl_recalculation_redis.py -v -m integration
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.pnl_tracker import PnLMetrics, PnLTracker
from src.accounts.pnl_registry import PnLTrackerRegistry
from src.accounts.risk_manager import AccountRiskManager
from src.accounts.risk_registry import RiskStateRegistry
from src.accounts.risk_state import RiskState
from src.state.daily_pnl_recalculator import (
    DailyPnLRecalculator,
    RecalculatedPnL,
    RecalculationResult,
)
from src.state.redis_state import RedisStateManager


@pytest.fixture
def redis_url():
    """Get Redis URL from environment or use default test URL."""
    return os.getenv("TEST_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def redis_manager(redis_url):
    """Create real Redis connection for integration tests."""
    manager = RedisStateManager(redis_url)
    await manager.connect()
    yield manager
    # Cleanup test keys
    try:
        async for key in manager.client.scan_iter("risk:test-*:*"):
            await manager.client.delete(key)
    except Exception:
        pass
    await manager.close()


@pytest.fixture
async def risk_registry(redis_manager):
    """Create RiskStateRegistry with real Redis."""
    registry = RiskStateRegistry(redis_manager)
    yield registry


@pytest.fixture
def mock_pnl_tracker():
    """Create mock PnL tracker with unrealized P&L."""
    tracker = MagicMock(spec=PnLTracker)
    tracker.get_pnl_metrics.return_value = PnLMetrics(
        current_equity=Decimal("99500"),
        balance=Decimal("100000"),
        unrealized_pnl=Decimal("-300"),
        daily_pnl=Decimal("-500"),
        daily_pnl_percent=Decimal("-0.5"),
        total_drawdown_percent=Decimal("0.5"),
        open_positions_count=2,
    )
    return tracker


@pytest.fixture
def mock_pnl_registry(mock_pnl_tracker):
    """Create mock PnL registry returning the tracker."""
    registry = MagicMock(spec=PnLTrackerRegistry)
    registry.get.return_value = mock_pnl_tracker
    return registry


@pytest.fixture
def mock_db_session_factory():
    """Create mock database session factory for tests.

    Returns a session that returns trade query results.
    """
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_row = MagicMock()
    mock_row.total_pnl = Decimal("-200")
    mock_row.trade_count = 3
    mock_result.one.return_value = mock_row
    mock_session.execute.return_value = mock_result

    mock_factory = MagicMock()

    class MockContextManager:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_factory.return_value = MockContextManager()
    return mock_factory


@pytest.fixture
async def recalculator(
    mock_db_session_factory,
    redis_manager,
    risk_registry,
    mock_pnl_registry,
):
    """Create DailyPnLRecalculator with real Redis and mocked DB."""
    return DailyPnLRecalculator(
        db_session_factory=mock_db_session_factory,
        redis_manager=redis_manager,
        risk_registry=risk_registry,
        pnl_registry=mock_pnl_registry,
    )


@pytest.mark.integration
class TestRiskStatePersistence:
    """Tests for risk state persistence in Redis after recalculation."""

    @pytest.mark.asyncio
    async def test_recalculation_persists_to_redis(
        self,
        recalculator: DailyPnLRecalculator,
        redis_manager: RedisStateManager,
        risk_registry: RiskStateRegistry,
    ):
        """Recalculated P&L should persist to Redis risk state (AC5)."""
        account_id = "test-account-001"

        # Initialize risk state for the account
        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        await manager.reset_daily(Decimal("100000"))

        # Recalculate
        result = await recalculator.recalculate_daily_pnl(
            account_id=account_id,
            snapshot_daily_pnl=Decimal("-450"),
        )

        assert result.success is True

        # Apply the recalculation
        await recalculator.apply_recalculation(account_id, result)

        # Verify Redis has updated values
        stored_state = await redis_manager.get_risk_state(account_id)
        assert stored_state is not None
        # Total P&L = realized (-200) + unrealized (-300) = -500
        assert stored_state.daily_pnl == Decimal("-500")

    @pytest.mark.asyncio
    async def test_daily_pnl_percent_calculated_correctly(
        self,
        recalculator: DailyPnLRecalculator,
        redis_manager: RedisStateManager,
        risk_registry: RiskStateRegistry,
    ):
        """Daily P&L percent should be calculated from starting balance."""
        account_id = "test-account-002"

        # Initialize with 100000 starting balance
        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        await manager.reset_daily(Decimal("100000"))

        # Recalculate
        result = await recalculator.recalculate_daily_pnl(
            account_id=account_id,
            snapshot_daily_pnl=Decimal("0"),
        )

        await recalculator.apply_recalculation(account_id, result)

        # Verify percent calculation: -500 / 100000 * 100 = -0.5%
        stored_state = await redis_manager.get_risk_state(account_id)
        assert stored_state is not None
        assert stored_state.daily_pnl_percent == Decimal("-0.5")

    @pytest.mark.asyncio
    async def test_multiple_accounts_isolated(
        self,
        recalculator: DailyPnLRecalculator,
        redis_manager: RedisStateManager,
        risk_registry: RiskStateRegistry,
    ):
        """Each account's P&L recalculation should be isolated."""
        account_a = "test-account-a"
        account_b = "test-account-b"

        # Initialize both accounts
        for acc_id in [account_a, account_b]:
            await risk_registry.update_account_equity(acc_id, Decimal("100000"))
            manager = await risk_registry.get_or_create(acc_id)
            await manager.reset_daily(Decimal("100000"))

        # Recalculate only account A
        result_a = await recalculator.recalculate_daily_pnl(
            account_id=account_a,
            snapshot_daily_pnl=Decimal("0"),
        )
        await recalculator.apply_recalculation(account_a, result_a)

        # Account A should have updated state
        state_a = await redis_manager.get_risk_state(account_a)
        assert state_a is not None
        assert state_a.daily_pnl == Decimal("-500")

        # Account B should have original state (daily_pnl = 0)
        state_b = await redis_manager.get_risk_state(account_b)
        assert state_b is not None
        assert state_b.daily_pnl == Decimal("0")


@pytest.mark.integration
class TestRecoveryFlowIntegration:
    """Tests for recovery flow integration with P&L recalculation."""

    @pytest.mark.asyncio
    async def test_failed_recalculation_preserves_existing_state(
        self,
        redis_manager: RedisStateManager,
        risk_registry: RiskStateRegistry,
        mock_pnl_registry: MagicMock,
    ):
        """Failed recalculation should not modify existing Redis state."""
        from sqlalchemy.exc import SQLAlchemyError

        account_id = "test-account-fail"

        # Initialize risk state
        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        manager.state.daily_pnl = Decimal("-100")  # Pre-existing value
        await redis_manager.save_risk_state(account_id, manager.state)

        # Create recalculator that fails on DB query
        async def mock_execute(*args, **kwargs):
            raise SQLAlchemyError("Connection failed")

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        mock_factory = MagicMock()

        class MockContextManager:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_factory.return_value = MockContextManager()

        recalculator = DailyPnLRecalculator(
            db_session_factory=mock_factory,
            redis_manager=redis_manager,
            risk_registry=risk_registry,
            pnl_registry=mock_pnl_registry,
        )

        # Attempt recalculation (should fail)
        result = await recalculator.recalculate_daily_pnl(
            account_id=account_id,
            snapshot_daily_pnl=Decimal("-100"),
        )

        assert result.success is False

        # Apply (should be no-op for failed result)
        await recalculator.apply_recalculation(account_id, result)

        # Verify original state preserved
        stored_state = await redis_manager.get_risk_state(account_id)
        assert stored_state is not None
        assert stored_state.daily_pnl == Decimal("-100")  # Unchanged

    @pytest.mark.asyncio
    async def test_adjustment_is_logged_on_difference(
        self,
        recalculator: DailyPnLRecalculator,
        risk_registry: RiskStateRegistry,
        caplog,
    ):
        """Adjustment should be logged when recalculated differs from snapshot (AC2)."""
        import logging

        account_id = "test-account-log"

        # Initialize risk state
        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        await manager.reset_daily(Decimal("100000"))

        with caplog.at_level(logging.INFO):
            result = await recalculator.recalculate_daily_pnl(
                account_id=account_id,
                snapshot_daily_pnl=Decimal("-450"),  # Different from -500
            )

        assert result.success is True
        assert result.adjustment == Decimal("-50")  # -500 - (-450)
        assert "adjusted from snapshot" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_no_log_when_values_match(
        self,
        recalculator: DailyPnLRecalculator,
        risk_registry: RiskStateRegistry,
        caplog,
    ):
        """No adjustment log when recalculated matches snapshot."""
        import logging

        account_id = "test-account-match"

        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        await manager.reset_daily(Decimal("100000"))

        with caplog.at_level(logging.INFO):
            result = await recalculator.recalculate_daily_pnl(
                account_id=account_id,
                snapshot_daily_pnl=Decimal("-500"),  # Matches recalculated
            )

        assert result.success is True
        assert result.adjustment == Decimal("0")
        # Should not have adjustment log
        assert "adjusted from snapshot" not in caplog.text.lower()


@pytest.mark.integration
class TestDataclassIntegration:
    """Tests for dataclass result handling."""

    @pytest.mark.asyncio
    async def test_recalculated_pnl_contains_all_fields(
        self,
        recalculator: DailyPnLRecalculator,
        risk_registry: RiskStateRegistry,
    ):
        """RecalculatedPnL should contain all required fields."""
        account_id = "test-account-fields"

        await risk_registry.update_account_equity(account_id, Decimal("100000"))
        manager = await risk_registry.get_or_create(account_id)
        await manager.reset_daily(Decimal("100000"))

        result = await recalculator.recalculate_daily_pnl(
            account_id=account_id,
            snapshot_daily_pnl=Decimal("0"),
        )

        assert result.success is True
        assert result.recalculated is not None

        recalc = result.recalculated
        assert recalc.account_id == account_id
        assert recalc.realized_pnl == Decimal("-200")
        assert recalc.unrealized_pnl == Decimal("-300")
        assert recalc.total_daily_pnl == Decimal("-500")
        assert recalc.trade_count == 3
        assert recalc.calculation_time is not None
        assert recalc.day_boundary is not None
        assert recalc.day_boundary.hour == 0
        assert recalc.day_boundary.minute == 0
