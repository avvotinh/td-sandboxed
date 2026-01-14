"""Unit tests for ColdStorageService."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.state.cold_storage_service import ColdStorageService
from src.state.cold_storage_writer import ColdStorageWriter
from src.state.snapshot import StateSnapshot


@pytest.fixture
def sample_snapshot() -> StateSnapshot:
    """Create a sample StateSnapshot for testing."""
    snapshot = StateSnapshot(
        account_id="ftmo-gold-001",
        timestamp=datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc),
        positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
        pending_orders=[],
        account_balance=Decimal("100000.00"),
        equity=Decimal("99850.00"),
        peak_balance=Decimal("102500.00"),
        daily_starting_balance=Decimal("100500.00"),
        checksum="",
    )
    snapshot.checksum = snapshot.compute_checksum()
    return snapshot


@pytest.fixture
def mock_writer():
    """Create a mock ColdStorageWriter."""
    writer = MagicMock(spec=ColdStorageWriter)
    writer.start = AsyncMock()
    writer.stop = AsyncMock()
    writer.write_snapshot = AsyncMock()
    writer.write_snapshots = AsyncMock()
    return writer


@pytest.fixture
def mock_snapshot_service(sample_snapshot: StateSnapshot):
    """Create a mock SnapshotService."""
    service = MagicMock()
    service._get_active_account_ids = AsyncMock(return_value=["ftmo-gold-001"])
    service._collect_snapshot_data = AsyncMock(return_value=sample_snapshot)
    return service


class TestColdStorageServiceInitialization:
    """Tests for ColdStorageService initialization."""

    def test_init_stores_dependencies(self, mock_writer, mock_snapshot_service):
        """__init__ should store writer and snapshot service."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        assert service._writer is mock_writer
        assert service._snapshot_service is mock_snapshot_service

    def test_init_default_interval(self, mock_writer, mock_snapshot_service):
        """__init__ should use 60s default interval."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        assert service._interval == 60.0

    def test_init_custom_interval(self, mock_writer, mock_snapshot_service):
        """__init__ should accept custom interval."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
            interval_seconds=30.0,
        )

        assert service._interval == 30.0

    def test_init_not_running(self, mock_writer, mock_snapshot_service):
        """__init__ should start with running=False."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        assert service.is_running is False

    def test_default_interval_constant(self):
        """DEFAULT_INTERVAL_SECONDS should be 60."""
        assert ColdStorageService.DEFAULT_INTERVAL_SECONDS == 60


class TestStartStop:
    """Tests for start() and stop() methods."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, mock_writer, mock_snapshot_service):
        """start() should set running to True."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        # Patch asyncio.sleep to avoid waiting
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            assert service.is_running is True
            # Clean up
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_starts_writer(self, mock_writer, mock_snapshot_service):
        """start() should start the writer."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            mock_writer.start.assert_called_once()
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_creates_task(self, mock_writer, mock_snapshot_service):
        """start() should create background task."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            assert service._task is not None
            await service.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_writer, mock_snapshot_service):
        """start() should be idempotent."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            await service.start()  # Second call should not error
            assert mock_writer.start.call_count == 1  # Only called once
            await service.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self, mock_writer, mock_snapshot_service):
        """stop() should set running to False."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            await service.stop()
            assert service.is_running is False

    @pytest.mark.asyncio
    async def test_stop_stops_writer(self, mock_writer, mock_snapshot_service):
        """stop() should stop the writer."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            await service.stop()
            mock_writer.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, mock_writer, mock_snapshot_service):
        """stop() should cancel the background task."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            await service.stop()
            assert service._task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, mock_writer, mock_snapshot_service):
        """stop() should be safe to call when not running."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        await service.stop()  # Should not error
        mock_writer.stop.assert_not_called()


class TestSnapshotAllAccounts:
    """Tests for _snapshot_all_accounts() method."""

    @pytest.mark.asyncio
    async def test_snapshot_all_accounts_empty(
        self, mock_writer, mock_snapshot_service
    ):
        """_snapshot_all_accounts should handle no active accounts."""
        mock_snapshot_service._get_active_account_ids = AsyncMock(return_value=[])

        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        await service._snapshot_all_accounts()

        # Should not write any snapshots
        mock_writer.write_snapshots.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapshot_all_accounts_collects_data(
        self, mock_writer, mock_snapshot_service, sample_snapshot: StateSnapshot
    ):
        """_snapshot_all_accounts should collect snapshot data for each account."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        await service._snapshot_all_accounts()

        mock_snapshot_service._collect_snapshot_data.assert_called_once_with(
            "ftmo-gold-001"
        )

    @pytest.mark.asyncio
    async def test_snapshot_all_accounts_writes_batch(
        self, mock_writer, mock_snapshot_service, sample_snapshot: StateSnapshot
    ):
        """_snapshot_all_accounts should write snapshots in batch."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        await service._snapshot_all_accounts()

        mock_writer.write_snapshots.assert_called_once()
        call_args = mock_writer.write_snapshots.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].account_id == sample_snapshot.account_id

    @pytest.mark.asyncio
    async def test_snapshot_all_accounts_handles_errors(
        self, mock_writer, mock_snapshot_service
    ):
        """_snapshot_all_accounts should continue on per-account errors."""
        mock_snapshot_service._get_active_account_ids = AsyncMock(
            return_value=["account-1", "account-2"]
        )
        mock_snapshot_service._collect_snapshot_data = AsyncMock(
            side_effect=[
                Exception("Collection failed"),
                StateSnapshot(
                    account_id="account-2",
                    timestamp=datetime.now(timezone.utc),
                    positions=[],
                    pending_orders=[],
                    account_balance=Decimal("0"),
                    equity=Decimal("0"),
                    peak_balance=Decimal("0"),
                    daily_starting_balance=Decimal("0"),
                    checksum="test",
                ),
            ]
        )

        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        await service._snapshot_all_accounts()

        # Should still write the successful snapshot
        mock_writer.write_snapshots.assert_called_once()
        call_args = mock_writer.write_snapshots.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].account_id == "account-2"


class TestFinalSnapshot:
    """Tests for final snapshot on stop."""

    @pytest.mark.asyncio
    async def test_stop_performs_final_snapshot(
        self, mock_writer, mock_snapshot_service
    ):
        """stop() should perform final snapshot before stopping."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            mock_writer.write_snapshots.reset_mock()
            await service.stop()

        # Final snapshot should be written
        mock_writer.write_snapshots.assert_called()

    @pytest.mark.asyncio
    async def test_stop_continues_on_final_snapshot_error(
        self, mock_writer, mock_snapshot_service
    ):
        """stop() should continue even if final snapshot fails."""
        mock_snapshot_service._collect_snapshot_data = AsyncMock(
            side_effect=Exception("Final snapshot failed")
        )

        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service.start()
            await service.stop()  # Should not raise

        assert service.is_running is False
        mock_writer.stop.assert_called_once()


class TestColdStorageLoop:
    """Tests for the cold storage loop behavior."""

    @pytest.mark.asyncio
    async def test_loop_uses_interval(self, mock_writer, mock_snapshot_service):
        """_cold_storage_loop should sleep for configured interval."""
        service = ColdStorageService(
            cold_storage_writer=mock_writer,
            snapshot_service=mock_snapshot_service,
            interval_seconds=5.0,  # Short interval for test
        )

        # Track sleep calls
        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            service._running = False  # Stop after first iteration

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await service.start()
            # Wait for the task to complete
            if service._task:
                try:
                    await asyncio.wait_for(service._task, timeout=1.0)
                except asyncio.TimeoutError:
                    pass
                except asyncio.CancelledError:
                    pass

        # Sleep should have been called with the interval
        if sleep_calls:
            assert sleep_calls[0] == 5.0
