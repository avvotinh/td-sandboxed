"""Unit tests for DailyPnLRecalculator module.

Tests daily P&L recalculation logic after crash recovery.

Test Categories:
- Day boundary calculation (midnight UTC)
- Realized P&L query (mocked database)
- Unrealized P&L retrieval (mocked PnLTracker)
- Total calculation (realized + unrealized)
- Adjustment logging
- Error handling (database errors, missing trackers)
- State update propagation
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.accounts.pnl_tracker import PnLMetrics
from src.state.daily_pnl_recalculator import (
    DailyPnLRecalculator,
    RecalculatedPnL,
    RecalculationResult,
)


class TestDayBoundaryCalculation:
    """Tests for day boundary (midnight UTC) calculation."""

    @pytest.fixture
    def recalculator(self) -> DailyPnLRecalculator:
        """Create recalculator with mocked dependencies."""
        mock_session_factory = MagicMock()
        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()
        mock_pnl_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    def test_day_boundary_at_midnight(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Without firm_registry, boundary defaults to UTC midnight."""
        test_time = datetime(2026, 1, 13, 14, 30, 45, 123456, tzinfo=timezone.utc)
        boundary = recalculator._get_day_boundary(account_id=None, now=test_time)

        assert boundary.hour == 0
        assert boundary.minute == 0
        assert boundary.second == 0
        assert boundary.microsecond == 0
        assert boundary.year == 2026
        assert boundary.month == 1
        assert boundary.day == 13

    def test_day_boundary_uses_current_time_by_default(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test day boundary uses current time if no time provided."""
        boundary = recalculator._get_day_boundary()
        now = datetime.now(timezone.utc)

        assert boundary.year == now.year
        assert boundary.month == now.month
        assert boundary.day == now.day
        assert boundary.hour == 0
        assert boundary.minute == 0

    def test_day_boundary_uses_firm_session_when_registered(self) -> None:
        """When firm_registry is wired in, boundary follows firm session timezone."""
        from src.config.firm_profile import SessionConfig

        # Mock account + firm registry so account "ftmo-001" → CET session
        account = MagicMock()
        account.firm_id = "ftmo"
        account_manager = MagicMock()
        account_manager.get_account.return_value = account

        cet_session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        firm = MagicMock(session=cet_session)
        firm_registry = MagicMock()
        firm_registry.get.return_value = firm

        recalculator = DailyPnLRecalculator(
            db_session_factory=MagicMock(),
            redis_manager=MagicMock(),
            risk_registry=MagicMock(),
            pnl_registry=MagicMock(),
            firm_registry=firm_registry,
            account_manager=account_manager,
        )

        # 14:00 UTC on 15 Jan = 15:00 CET → previous local midnight = 14 Jan 23:00 UTC
        now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
        boundary = recalculator._get_day_boundary(account_id="ftmo-001", now=now)

        assert boundary == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)


class TestUnrealizedPnLRetrieval:
    """Tests for unrealized P&L retrieval from PnLTracker."""

    @pytest.fixture
    def mock_pnl_registry(self) -> MagicMock:
        """Create mock PnL registry."""
        return MagicMock()

    @pytest.fixture
    def recalculator(
        self,
        mock_pnl_registry: MagicMock,
    ) -> DailyPnLRecalculator:
        """Create recalculator with mocked dependencies."""
        mock_session_factory = MagicMock()
        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    def test_unrealized_pnl_from_tracker(
        self,
        recalculator: DailyPnLRecalculator,
        mock_pnl_registry: MagicMock,
    ) -> None:
        """Test unrealized P&L retrieved from PnLTracker."""
        mock_tracker = MagicMock()
        mock_tracker.get_pnl_metrics.return_value = PnLMetrics(
            current_equity=Decimal("99500"),
            balance=Decimal("100000"),
            unrealized_pnl=Decimal("-500"),
            daily_pnl=Decimal("-300"),
            daily_pnl_percent=Decimal("-0.3"),
            total_drawdown_percent=Decimal("0.5"),
            open_positions_count=2,
        )
        mock_pnl_registry.get.return_value = mock_tracker

        result = recalculator._get_unrealized_pnl("ftmo-001")

        assert result == Decimal("-500")
        mock_pnl_registry.get.assert_called_once_with("ftmo-001")

    def test_unrealized_pnl_missing_tracker_returns_zero(
        self,
        recalculator: DailyPnLRecalculator,
        mock_pnl_registry: MagicMock,
    ) -> None:
        """Test missing tracker returns zero unrealized P&L."""
        mock_pnl_registry.get.return_value = None

        result = recalculator._get_unrealized_pnl("ftmo-001")

        assert result == Decimal("0")

    def test_unrealized_pnl_positive_value(
        self,
        recalculator: DailyPnLRecalculator,
        mock_pnl_registry: MagicMock,
    ) -> None:
        """Test positive unrealized P&L retrieval."""
        mock_tracker = MagicMock()
        mock_tracker.get_pnl_metrics.return_value = PnLMetrics(
            current_equity=Decimal("100500"),
            balance=Decimal("100000"),
            unrealized_pnl=Decimal("500"),
            daily_pnl=Decimal("700"),
            daily_pnl_percent=Decimal("0.7"),
            total_drawdown_percent=Decimal("0"),
            open_positions_count=1,
        )
        mock_pnl_registry.get.return_value = mock_tracker

        result = recalculator._get_unrealized_pnl("ftmo-001")

        assert result == Decimal("500")


class TestRealizedPnLQuery:
    """Tests for realized P&L database query."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock async session."""
        session = AsyncMock()
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session: AsyncMock) -> MagicMock:
        """Create mock session factory that returns async context manager."""
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock()
        return factory

    @pytest.fixture
    def recalculator(
        self,
        mock_session_factory: MagicMock,
    ) -> DailyPnLRecalculator:
        """Create recalculator with mocked dependencies."""
        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()
        mock_pnl_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    async def test_query_realized_pnl_with_trades(
        self,
        recalculator: DailyPnLRecalculator,
        mock_session: AsyncMock,
    ) -> None:
        """Test query returns sum of closed trade P&L."""
        # Mock query result
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_pnl = Decimal("-520")
        mock_row.trade_count = 5
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        day_boundary = datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)
        pnl, count = await recalculator._query_realized_pnl("ftmo-001", day_boundary)

        assert pnl == Decimal("-520")
        assert count == 5

    async def test_query_realized_pnl_no_trades(
        self,
        recalculator: DailyPnLRecalculator,
        mock_session: AsyncMock,
    ) -> None:
        """Test query returns zero when no trades today."""
        # Mock query result with COALESCE returning 0
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_pnl = Decimal("0")
        mock_row.trade_count = 0
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        day_boundary = datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)
        pnl, count = await recalculator._query_realized_pnl("ftmo-001", day_boundary)

        assert pnl == Decimal("0")
        assert count == 0


class TestRecalculateDailyPnL:
    """Tests for main recalculation logic."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock async session."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.total_pnl = Decimal("-200")
        mock_row.trade_count = 3
        mock_result.one.return_value = mock_row
        session.execute.return_value = mock_result
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session: AsyncMock) -> MagicMock:
        """Create mock session factory."""
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        factory.return_value.__aexit__ = AsyncMock()
        return factory

    @pytest.fixture
    def mock_pnl_registry(self) -> MagicMock:
        """Create mock PnL registry with tracker."""
        registry = MagicMock()
        mock_tracker = MagicMock()
        mock_tracker.get_pnl_metrics.return_value = PnLMetrics(
            current_equity=Decimal("99500"),
            balance=Decimal("100000"),
            unrealized_pnl=Decimal("-300"),
            daily_pnl=Decimal("-500"),
            daily_pnl_percent=Decimal("-0.5"),
            total_drawdown_percent=Decimal("0.5"),
            open_positions_count=2,
        )
        registry.get.return_value = mock_tracker
        return registry

    @pytest.fixture
    def recalculator(
        self,
        mock_session_factory: MagicMock,
        mock_pnl_registry: MagicMock,
    ) -> DailyPnLRecalculator:
        """Create recalculator with mocked dependencies."""
        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    async def test_recalculate_returns_success(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test successful recalculation returns RecalculationResult."""
        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-500"),
        )

        assert result.success is True
        assert result.recalculated is not None
        assert result.error_message is None

    async def test_recalculate_total_equals_realized_plus_unrealized(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test total daily P&L = realized + unrealized (AC4)."""
        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("0"),
        )

        assert result.success is True
        assert result.recalculated is not None
        # realized (-200) + unrealized (-300) = -500
        assert result.recalculated.realized_pnl == Decimal("-200")
        assert result.recalculated.unrealized_pnl == Decimal("-300")
        assert result.recalculated.total_daily_pnl == Decimal("-500")

    async def test_recalculate_adjustment_calculated(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test adjustment is difference between recalculated and snapshot (AC2)."""
        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-450"),  # Snapshot had -450
        )

        assert result.success is True
        # Recalculated is -500, snapshot was -450
        # Adjustment = -500 - (-450) = -50
        assert result.adjustment == Decimal("-50")

    async def test_recalculate_no_adjustment_when_values_match(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test no adjustment when recalculated matches snapshot."""
        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-500"),  # Matches recalculated
        )

        assert result.success is True
        assert result.adjustment == Decimal("0")

    async def test_recalculate_logs_adjustment(
        self,
        recalculator: DailyPnLRecalculator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test adjustment is logged when values differ (AC2)."""
        import logging

        with caplog.at_level(logging.INFO):
            result = await recalculator.recalculate_daily_pnl(
                account_id="ftmo-001",
                snapshot_daily_pnl=Decimal("-450"),
            )

        assert result.success is True
        assert "Daily P&L adjusted from snapshot" in caplog.text
        assert "-450" in caplog.text
        assert "-500" in caplog.text

    async def test_recalculate_includes_trade_count(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test recalculated result includes trade count."""
        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("0"),
        )

        assert result.success is True
        assert result.recalculated is not None
        assert result.recalculated.trade_count == 3


class TestDatabaseErrorHandling:
    """Tests for database error fallback behavior (AC6)."""

    @pytest.fixture
    def mock_pnl_registry(self) -> MagicMock:
        """Create mock PnL registry that returns None."""
        registry = MagicMock()
        registry.get.return_value = None
        return registry

    @pytest.fixture
    def recalculator_with_db_error(
        self,
        mock_pnl_registry: MagicMock,
    ) -> DailyPnLRecalculator:
        """Create recalculator that will fail on DB query."""
        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()

        # Create a proper async context manager that raises on execute
        async def mock_execute(*args, **kwargs):
            raise SQLAlchemyError("Connection failed")

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        # Factory returns async context manager
        mock_factory = MagicMock()

        class MockContextManager:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_factory.return_value = MockContextManager()

        return DailyPnLRecalculator(
            db_session_factory=mock_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    async def test_database_error_returns_failure(
        self,
        recalculator_with_db_error: DailyPnLRecalculator,
    ) -> None:
        """Test database error returns failure result (AC6)."""
        result = await recalculator_with_db_error.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-500"),
        )

        assert result.success is False
        assert result.recalculated is None
        assert result.error_message is not None
        assert "Database error" in result.error_message or "Connection" in result.error_message

    async def test_database_error_preserves_snapshot_value(
        self,
        recalculator_with_db_error: DailyPnLRecalculator,
    ) -> None:
        """Test database error preserves snapshot value (AC6)."""
        result = await recalculator_with_db_error.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-500"),
        )

        assert result.success is False
        assert result.snapshot_value == Decimal("-500")
        assert result.adjustment == Decimal("0")

    async def test_database_error_logs_warning(
        self,
        mock_pnl_registry: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test database error is logged as warning (AC6)."""
        import logging

        mock_redis = MagicMock()
        mock_risk_registry = MagicMock()

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
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

        with caplog.at_level(logging.WARNING):
            await recalculator.recalculate_daily_pnl(
                account_id="ftmo-001",
                snapshot_daily_pnl=Decimal("-500"),
            )

        assert "using snapshot value" in caplog.text.lower()


class TestStateUpdatePersistence:
    """Tests for state update and Redis persistence (AC5)."""

    @pytest.fixture
    def mock_redis_manager(self) -> MagicMock:
        """Create mock Redis manager."""
        redis = MagicMock()
        redis.save_risk_state = AsyncMock()
        return redis

    @pytest.fixture
    def mock_risk_registry(self) -> MagicMock:
        """Create mock risk registry with state."""
        from src.accounts.risk_state import RiskState

        registry = MagicMock()
        mock_state = RiskState(
            daily_pnl=Decimal("-450"),
            daily_pnl_percent=Decimal("-0.45"),
            current_equity=Decimal("99550"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("0.45"),
            daily_starting_balance=Decimal("100000"),
        )
        registry.get_risk_state.return_value = mock_state
        return registry

    @pytest.fixture
    def recalculator(
        self,
        mock_redis_manager: MagicMock,
        mock_risk_registry: MagicMock,
    ) -> DailyPnLRecalculator:
        """Create recalculator with mocked dependencies."""
        mock_session_factory = MagicMock()
        mock_pnl_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis_manager,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    async def test_apply_updates_risk_registry(
        self,
        recalculator: DailyPnLRecalculator,
        mock_risk_registry: MagicMock,
    ) -> None:
        """Test apply_recalculation updates RiskStateRegistry (AC5)."""
        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        await recalculator.apply_recalculation("ftmo-001", result)

        # Verify risk state was retrieved
        mock_risk_registry.get_risk_state.assert_called_once_with("ftmo-001")

    async def test_apply_persists_to_redis(
        self,
        recalculator: DailyPnLRecalculator,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test apply_recalculation persists to Redis (AC5)."""
        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        await recalculator.apply_recalculation("ftmo-001", result)

        # Verify Redis save was called
        mock_redis_manager.save_risk_state.assert_called_once()

    async def test_apply_skips_failed_result(
        self,
        recalculator: DailyPnLRecalculator,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test apply_recalculation skips update for failed result."""
        result = RecalculationResult(
            success=False,
            recalculated=None,
            snapshot_value=Decimal("-500"),
            adjustment=Decimal("0"),
            error_message="Database error",
        )

        await recalculator.apply_recalculation("ftmo-001", result)

        # Verify Redis save was NOT called
        mock_redis_manager.save_risk_state.assert_not_called()

    async def test_apply_calculates_pnl_percent(
        self,
        recalculator: DailyPnLRecalculator,
        mock_risk_registry: MagicMock,
    ) -> None:
        """Test apply_recalculation calculates daily_pnl_percent."""
        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        await recalculator.apply_recalculation("ftmo-001", result)

        # Get the risk state that was modified
        risk_state = mock_risk_registry.get_risk_state.return_value

        # Daily P&L percent should be -500 / 100000 * 100 = -0.5%
        assert risk_state.daily_pnl == Decimal("-500")
        assert risk_state.daily_pnl_percent == Decimal("-0.5")


class TestRecalculatedPnLDataclass:
    """Tests for RecalculatedPnL dataclass."""

    def test_recalculated_pnl_creation(self) -> None:
        """Test RecalculatedPnL can be created with all fields."""
        now = datetime.now(timezone.utc)
        day_boundary = datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc)

        result = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=now,
            day_boundary=day_boundary,
        )

        assert result.account_id == "ftmo-001"
        assert result.realized_pnl == Decimal("-200")
        assert result.unrealized_pnl == Decimal("-300")
        assert result.total_daily_pnl == Decimal("-500")
        assert result.trade_count == 3
        assert result.calculation_time == now
        assert result.day_boundary == day_boundary


class TestRecalculationResultDataclass:
    """Tests for RecalculationResult dataclass."""

    def test_successful_result_creation(self) -> None:
        """Test RecalculationResult for successful recalculation."""
        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )

        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        assert result.success is True
        assert result.recalculated is not None
        assert result.snapshot_value == Decimal("-450")
        assert result.adjustment == Decimal("-50")
        assert result.error_message is None

    def test_failed_result_creation(self) -> None:
        """Test RecalculationResult for failed recalculation."""
        result = RecalculationResult(
            success=False,
            recalculated=None,
            snapshot_value=Decimal("-500"),
            adjustment=Decimal("0"),
            error_message="Database connection failed",
        )

        assert result.success is False
        assert result.recalculated is None
        assert result.snapshot_value == Decimal("-500")
        assert result.adjustment == Decimal("0")
        assert result.error_message == "Database connection failed"


class TestMissingRiskStateHandling:
    """Tests for missing risk state during update."""

    @pytest.fixture
    def recalculator(self) -> DailyPnLRecalculator:
        """Create recalculator with risk registry returning None."""
        mock_session_factory = MagicMock()
        mock_redis = MagicMock()
        mock_redis.save_risk_state = AsyncMock()
        mock_risk_registry = MagicMock()
        mock_risk_registry.get_risk_state.return_value = None  # No risk state
        mock_pnl_registry = MagicMock()
        return DailyPnLRecalculator(
            db_session_factory=mock_session_factory,
            redis_manager=mock_redis,
            risk_registry=mock_risk_registry,
            pnl_registry=mock_pnl_registry,
        )

    async def test_missing_risk_state_logs_error(
        self,
        recalculator: DailyPnLRecalculator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test missing risk state logs error during update."""
        import logging

        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        with caplog.at_level(logging.ERROR):
            await recalculator.apply_recalculation("ftmo-001", result)

        assert "No risk state found" in caplog.text

    async def test_missing_risk_state_does_not_persist(
        self,
        recalculator: DailyPnLRecalculator,
    ) -> None:
        """Test missing risk state does not attempt Redis persist."""
        recalculated = RecalculatedPnL(
            account_id="ftmo-001",
            realized_pnl=Decimal("-200"),
            unrealized_pnl=Decimal("-300"),
            total_daily_pnl=Decimal("-500"),
            trade_count=3,
            calculation_time=datetime.now(timezone.utc),
            day_boundary=datetime(2026, 1, 13, 0, 0, 0, tzinfo=timezone.utc),
        )
        result = RecalculationResult(
            success=True,
            recalculated=recalculated,
            snapshot_value=Decimal("-450"),
            adjustment=Decimal("-50"),
        )

        await recalculator.apply_recalculation("ftmo-001", result)

        # Redis save should not be called when risk state is missing
        recalculator._redis.save_risk_state.assert_not_called()
