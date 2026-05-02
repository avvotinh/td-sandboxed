"""Unit tests for SnapshotService."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.state.snapshot import StateSnapshot
from src.state.snapshot_service import SnapshotService


@pytest.fixture
def mock_redis_manager():
    """Create mock RedisStateManager."""
    manager = MagicMock()
    manager.save_snapshot = AsyncMock()
    manager.get_account_balance = AsyncMock(return_value=Decimal("100000"))
    return manager


@pytest.fixture
def mock_account_manager():
    """Create mock AccountManager."""
    manager = MagicMock()
    manager.get_all_accounts = MagicMock(return_value=["account-1", "account-2"])
    manager.get_account_status = AsyncMock(return_value="active")
    return manager


@pytest.fixture
def mock_position_tracker():
    """Create mock PositionTracker."""
    tracker = MagicMock()
    tracker.get_positions_dict = MagicMock(
        return_value=[
            {
                "symbol": "XAUUSD",
                "side": "BUY",
                "volume": "0.1",
                "entry_price": "1850.25",
                "entry_time": "2026-01-03T10:00:00+00:00",
                "order_id": "order-123",
            }
        ]
    )
    return tracker


@pytest.fixture
def mock_risk_registry():
    """Create mock RiskStateRegistry."""
    registry = MagicMock()
    mock_risk_state = MagicMock()
    mock_risk_state.current_equity = Decimal("99000")
    mock_risk_state.peak_equity = Decimal("100000")
    mock_risk_state.daily_starting_balance = Decimal("100000")
    registry.get_risk_state = MagicMock(return_value=mock_risk_state)
    return registry


@pytest.fixture
def snapshot_service(
    mock_redis_manager,
    mock_account_manager,
    mock_position_tracker,
    mock_risk_registry,
):
    """Create SnapshotService with mocked dependencies."""
    return SnapshotService(
        redis_manager=mock_redis_manager,
        account_manager=mock_account_manager,
        position_tracker=mock_position_tracker,
        risk_registry=mock_risk_registry,
        interval_seconds=0.1,  # Short interval for testing
    )


class TestSnapshotServiceConstants:
    """Tests for SnapshotService constants."""

    def test_snapshot_ttl_is_one_hour(self):
        """TTL should be 3600 seconds (1 hour)."""
        assert SnapshotService.SNAPSHOT_TTL_SECONDS == 3600


class TestSnapshotServiceInit:
    """Tests for SnapshotService initialization."""

    def test_init_stores_dependencies(
        self,
        mock_redis_manager,
        mock_account_manager,
        mock_position_tracker,
        mock_risk_registry,
    ):
        """Init should store all dependencies."""
        service = SnapshotService(
            redis_manager=mock_redis_manager,
            account_manager=mock_account_manager,
            position_tracker=mock_position_tracker,
            risk_registry=mock_risk_registry,
            interval_seconds=5.0,
        )

        assert service._redis is mock_redis_manager
        assert service._account_manager is mock_account_manager
        assert service._position_tracker is mock_position_tracker
        assert service._risk_registry is mock_risk_registry
        assert service._interval == 5.0
        assert service._running is False
        assert service._task is None

    def test_default_interval(
        self,
        mock_redis_manager,
        mock_account_manager,
        mock_position_tracker,
        mock_risk_registry,
    ):
        """Default interval should be 5 seconds."""
        service = SnapshotService(
            redis_manager=mock_redis_manager,
            account_manager=mock_account_manager,
            position_tracker=mock_position_tracker,
            risk_registry=mock_risk_registry,
        )

        assert service._interval == 5.0


class TestGetActiveAccountIds:
    """Tests for _get_active_account_ids method."""

    @pytest.mark.asyncio
    async def test_returns_active_accounts(self, snapshot_service, mock_account_manager):
        """Should return only accounts with 'active' status."""
        mock_account_manager.get_all_accounts.return_value = [
            "account-1",
            "account-2",
            "account-3",
        ]
        mock_account_manager.get_account_status.side_effect = [
            "active",
            "paused",
            "active",
        ]

        result = await snapshot_service._get_active_account_ids()

        assert result == ["account-1", "account-3"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_active(
        self, snapshot_service, mock_account_manager
    ):
        """Should return empty list when no accounts are active."""
        mock_account_manager.get_all_accounts.return_value = ["account-1"]
        mock_account_manager.get_account_status.return_value = "stopped"

        result = await snapshot_service._get_active_account_ids()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_accounts(
        self, snapshot_service, mock_account_manager
    ):
        """Should return empty list when no accounts exist."""
        mock_account_manager.get_all_accounts.return_value = []

        result = await snapshot_service._get_active_account_ids()

        assert result == []


class TestCollectSnapshotData:
    """Tests for _collect_snapshot_data method."""

    @pytest.mark.asyncio
    async def test_collects_all_data(
        self,
        snapshot_service,
        mock_position_tracker,
        mock_redis_manager,
        mock_risk_registry,
    ):
        """Should collect positions, balance, and risk data."""
        snapshot = await snapshot_service._collect_snapshot_data("account-1")

        assert snapshot.account_id == "account-1"
        assert isinstance(snapshot.timestamp, datetime)
        assert len(snapshot.positions) == 1
        assert snapshot.positions[0]["symbol"] == "XAUUSD"
        assert snapshot.pending_orders == []
        assert snapshot.account_balance == Decimal("100000")
        assert snapshot.equity == Decimal("99000")
        assert snapshot.peak_balance == Decimal("100000")
        assert snapshot.daily_starting_balance == Decimal("100000")
        assert snapshot.checksum != ""

    @pytest.mark.asyncio
    async def test_uses_fallback_when_no_risk_state(
        self,
        snapshot_service,
        mock_risk_registry,
        mock_redis_manager,
    ):
        """Should use balance as fallback when no risk state."""
        mock_risk_registry.get_risk_state.return_value = None
        mock_redis_manager.get_account_balance.return_value = Decimal("50000")

        snapshot = await snapshot_service._collect_snapshot_data("account-1")

        assert snapshot.account_balance == Decimal("50000")
        assert snapshot.equity == Decimal("50000")  # Fallback to balance
        assert snapshot.peak_balance == Decimal("50000")
        assert snapshot.daily_starting_balance == Decimal("50000")

    @pytest.mark.asyncio
    async def test_handles_none_balance(
        self,
        snapshot_service,
        mock_redis_manager,
        mock_risk_registry,
    ):
        """Should use 0 when balance is None."""
        mock_redis_manager.get_account_balance.return_value = None
        mock_risk_registry.get_risk_state.return_value = None

        snapshot = await snapshot_service._collect_snapshot_data("account-1")

        assert snapshot.account_balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_checksum_is_computed(self, snapshot_service):
        """Should compute valid checksum."""
        snapshot = await snapshot_service._collect_snapshot_data("account-1")

        assert snapshot.validate_checksum() is True


class TestSnapshotAccount:
    """Tests for _snapshot_account method."""

    @pytest.mark.asyncio
    async def test_saves_snapshot_with_ttl(
        self,
        snapshot_service,
        mock_redis_manager,
    ):
        """Should save snapshot with TTL."""
        await snapshot_service._snapshot_account("account-1")

        mock_redis_manager.save_snapshot.assert_called_once()
        call_args = mock_redis_manager.save_snapshot.call_args
        assert call_args[0][0] == "account-1"
        assert isinstance(call_args[0][1], StateSnapshot)
        assert call_args[1]["ttl_seconds"] == 3600


class TestSnapshotAllAccounts:
    """Tests for _snapshot_all_accounts method."""

    @pytest.mark.asyncio
    async def test_snapshots_all_active_accounts(
        self,
        snapshot_service,
        mock_account_manager,
        mock_redis_manager,
    ):
        """Should snapshot all active accounts."""
        mock_account_manager.get_all_accounts.return_value = [
            "account-1",
            "account-2",
        ]
        mock_account_manager.get_account_status.return_value = "active"

        await snapshot_service._snapshot_all_accounts()

        assert mock_redis_manager.save_snapshot.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_when_no_active_accounts(
        self,
        snapshot_service,
        mock_account_manager,
        mock_redis_manager,
    ):
        """Should skip when no active accounts."""
        mock_account_manager.get_all_accounts.return_value = ["account-1"]
        mock_account_manager.get_account_status.return_value = "stopped"

        await snapshot_service._snapshot_all_accounts()

        mock_redis_manager.save_snapshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_error(
        self,
        snapshot_service,
        mock_account_manager,
        mock_redis_manager,
    ):
        """Should continue when one account fails."""
        mock_account_manager.get_all_accounts.return_value = [
            "account-1",
            "account-2",
        ]
        mock_account_manager.get_account_status.return_value = "active"
        mock_redis_manager.save_snapshot.side_effect = [
            Exception("Redis error"),
            None,  # Second succeeds
        ]

        # Should not raise
        await snapshot_service._snapshot_all_accounts()

        # Both were attempted
        assert mock_redis_manager.save_snapshot.call_count == 2


class TestStartStop:
    """Tests for start() and stop() methods."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, snapshot_service):
        """start() should set _running to True."""
        await snapshot_service.start()

        try:
            assert snapshot_service._running is True
            assert snapshot_service._task is not None
        finally:
            await snapshot_service.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, snapshot_service):
        """start() should be idempotent."""
        await snapshot_service.start()
        task1 = snapshot_service._task

        await snapshot_service.start()
        task2 = snapshot_service._task

        try:
            # Should be same task
            assert task1 is task2
        finally:
            await snapshot_service.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self, snapshot_service):
        """stop() should set _running to False."""
        await snapshot_service.start()
        await snapshot_service.stop()

        assert snapshot_service._running is False
        assert snapshot_service._task is None

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, snapshot_service):
        """stop() should be idempotent."""
        # Should not raise when not running
        await snapshot_service.stop()
        await snapshot_service.stop()

    @pytest.mark.asyncio
    async def test_stop_performs_final_snapshot(
        self,
        snapshot_service,
        mock_redis_manager,
    ):
        """stop() should perform final snapshot."""
        await snapshot_service.start()
        mock_redis_manager.save_snapshot.reset_mock()

        await snapshot_service.stop()

        # Should have done final snapshot
        assert mock_redis_manager.save_snapshot.call_count >= 1


class TestSnapshotLoop:
    """Tests for _snapshot_loop method."""

    @pytest.mark.asyncio
    async def test_loop_runs_until_stopped(self, snapshot_service, mock_redis_manager):
        """Loop should run multiple cycles until stopped."""
        await snapshot_service.start()

        # Let it run a few cycles
        await asyncio.sleep(0.25)

        await snapshot_service.stop()

        # Should have called save_snapshot multiple times
        assert mock_redis_manager.save_snapshot.call_count >= 2

    @pytest.mark.asyncio
    async def test_loop_continues_on_error(
        self, snapshot_service, mock_redis_manager, mock_account_manager
    ):
        """Loop should continue after errors."""
        # First call fails, second succeeds
        call_count = [0]

        async def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Redis error")

        mock_redis_manager.save_snapshot.side_effect = side_effect

        await snapshot_service.start()
        await asyncio.sleep(0.25)
        await snapshot_service.stop()

        # Should have continued running after error
        assert call_count[0] >= 2


class TestSnapshotTiming:
    """Tests for snapshot timing (AC7: < 10ms)."""

    @pytest.mark.asyncio
    async def test_single_snapshot_under_10ms(
        self,
        mock_redis_manager,
        mock_account_manager,
        mock_position_tracker,
        mock_risk_registry,
    ):
        """Single account snapshot should complete in under 10ms."""
        import time

        service = SnapshotService(
            redis_manager=mock_redis_manager,
            account_manager=mock_account_manager,
            position_tracker=mock_position_tracker,
            risk_registry=mock_risk_registry,
        )

        start = time.perf_counter()
        await service._snapshot_account("account-1")
        elapsed_ms = (time.perf_counter() - start) * 1000

        # With mocked dependencies, should be well under 10ms
        assert elapsed_ms < 10, f"Snapshot took {elapsed_ms:.2f}ms"


class TestConcurrentSnapshots:
    """Tests for concurrent snapshot handling (AC5)."""

    @pytest.mark.asyncio
    async def test_uses_asyncio_gather(
        self,
        snapshot_service,
        mock_account_manager,
        mock_redis_manager,
    ):
        """Should use asyncio.gather for concurrent snapshots."""
        mock_account_manager.get_all_accounts.return_value = [
            "account-1",
            "account-2",
            "account-3",
        ]
        mock_account_manager.get_account_status.return_value = "active"

        # Track call order
        call_times = []

        async def track_call(*args, **kwargs):
            import time

            call_times.append(time.perf_counter())
            await asyncio.sleep(0.01)  # Simulate work

        mock_redis_manager.save_snapshot.side_effect = track_call

        await snapshot_service._snapshot_all_accounts()

        # All calls should happen nearly simultaneously (within 5ms)
        assert len(call_times) == 3
        time_spread = max(call_times) - min(call_times)
        assert time_spread < 0.005, f"Calls not concurrent: spread={time_spread}s"
