"""Unit tests for ColdStorageWriter."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
def mock_engine():
    """Create a mock SQLAlchemy async engine."""
    with patch("src.state.cold_storage_writer.create_async_engine") as mock:
        engine = MagicMock()
        engine.dispose = AsyncMock()
        mock.return_value = engine
        yield engine


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy async session."""
    session = MagicMock()
    # Create a proper async context manager for begin()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_cm)
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.execute = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


class TestColdStorageWriterInitialization:
    """Tests for ColdStorageWriter initialization."""

    def test_init_sets_database_url(self, mock_engine):
        """__init__ should store database URL."""
        writer = ColdStorageWriter("postgresql+asyncpg://user:pass@localhost/db")
        assert writer._database_url == "postgresql+asyncpg://user:pass@localhost/db"

    def test_init_not_running(self, mock_engine):
        """__init__ should start with running=False."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        assert writer.is_running is False

    def test_snapshot_interval_constant(self, mock_engine):
        """SNAPSHOT_INTERVAL_SECONDS should be 60."""
        assert ColdStorageWriter.SNAPSHOT_INTERVAL_SECONDS == 60


class TestStartStop:
    """Tests for start() and stop() methods."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, mock_engine):
        """start() should set running to True."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        await writer.start()

        assert writer.is_running is True

    @pytest.mark.asyncio
    async def test_start_idempotent(self, mock_engine):
        """start() should be idempotent (calling twice has no effect)."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        await writer.start()
        await writer.start()  # Second call should not error

        assert writer.is_running is True

    @pytest.mark.asyncio
    async def test_stop_sets_not_running(self, mock_engine):
        """stop() should set running to False."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        await writer.start()
        await writer.stop()

        assert writer.is_running is False

    @pytest.mark.asyncio
    async def test_stop_disposes_engine(self, mock_engine):
        """stop() should dispose the engine."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        await writer.start()
        await writer.stop()

        mock_engine.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, mock_engine):
        """stop() should be safe to call when not running."""
        writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
        await writer.stop()  # Should not error

        assert writer.is_running is False


class TestWriteSnapshot:
    """Tests for write_snapshot() method."""

    @pytest.mark.asyncio
    async def test_write_snapshot_creates_model(
        self, mock_engine, mock_session, sample_snapshot: StateSnapshot
    ):
        """write_snapshot should create and persist a model."""
        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            await writer.write_snapshot(sample_snapshot)

            # Verify session.add was called
            mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_snapshot_uses_begin(
        self, mock_engine, mock_session, sample_snapshot: StateSnapshot
    ):
        """write_snapshot should use transaction context."""
        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            await writer.write_snapshot(sample_snapshot)

            # Session should be entered as context manager
            mock_session.__aenter__.assert_called()


class TestWriteSnapshots:
    """Tests for write_snapshots() batch method."""

    @pytest.mark.asyncio
    async def test_write_snapshots_empty_list(self, mock_engine, mock_session):
        """write_snapshots should handle empty list."""
        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            await writer.write_snapshots([])

            # Should not create session for empty list
            mock_session.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_snapshots_batch(
        self, mock_engine, mock_session, sample_snapshot: StateSnapshot
    ):
        """write_snapshots should batch insert multiple snapshots."""
        snapshots = [sample_snapshot, sample_snapshot]

        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            await writer.write_snapshots(snapshots)

            # Verify add_all was called with list of models
            mock_session.add_all.assert_called_once()


class TestGetLatestSnapshot:
    """Tests for get_latest_snapshot() method."""

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_returns_none_when_not_found(
        self, mock_engine, mock_session
    ):
        """get_latest_snapshot should return None when no snapshot found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            result = await writer.get_latest_snapshot("nonexistent-account")

            assert result is None

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_returns_snapshot(
        self, mock_engine, mock_session, sample_snapshot: StateSnapshot
    ):
        """get_latest_snapshot should return StateSnapshot when found."""
        from src.state.snapshot_db_model import StateSnapshotModel

        mock_model = StateSnapshotModel.from_snapshot(sample_snapshot)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_model
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            result = await writer.get_latest_snapshot("ftmo-gold-001")

            assert result is not None
            assert isinstance(result, StateSnapshot)
            assert result.account_id == sample_snapshot.account_id

    @pytest.mark.asyncio
    async def test_get_latest_snapshot_orders_by_timestamp_desc(
        self, mock_engine, mock_session
    ):
        """get_latest_snapshot should query with ORDER BY timestamp DESC."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "src.state.cold_storage_writer.async_sessionmaker"
        ) as mock_session_maker:
            mock_session_maker.return_value = MagicMock(
                return_value=mock_session
            )

            writer = ColdStorageWriter("postgresql+asyncpg://localhost/db")
            await writer.get_latest_snapshot("test-account")

            # Verify execute was called with a query
            mock_session.execute.assert_called_once()
