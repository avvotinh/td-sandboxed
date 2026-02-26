"""Unit tests for Daily Account Snapshots (Story 7.4).

Tests cover:
- AccountSnapshotModel.from_snapshot_data() maps all 17 columns correctly (5.1)
- AccountSnapshotModel.to_dict() preserves DECIMAL precision (5.2)
- SnapshotDBWriter.write_snapshot() calls session with correct model (5.3)
- SnapshotDBWriter.write_snapshot() upsert handles duplicate (5.4)
- DailySnapshotService._collect_snapshot_data() aggregates from Redis + DB (5.5)
- DailySnapshotService._calculate_seconds_until_midnight() returns correct delay (5.6)
- DailySnapshotService._take_all_snapshots() continues on per-account failure (5.7)
- drawdown_from_peak calculation: peak_balance - closing_balance (5.8)
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.snapshots.daily_snapshot_service import DailySnapshotService
from src.snapshots.models import AccountSnapshotModel
from src.snapshots.snapshot_db_writer import SnapshotDBWriter


# -- Fixtures --


@pytest.fixture
def sample_snapshot_data() -> dict:
    """Complete snapshot data dict as produced by _collect_snapshot_data."""
    return {
        "account_id": "ftmo-gold-001",
        "snapshot_date": date(2025, 12, 3),
        "snapshot_time": time(0, 0, 0),
        "opening_balance": Decimal("100000.00"),
        "closing_balance": Decimal("99350.00"),
        "high_balance": Decimal("101200.00"),
        "low_balance": Decimal("99100.00"),
        "daily_pnl": Decimal("-650.00"),
        "daily_pnl_percent": Decimal("-0.6500"),
        "peak_balance": Decimal("102500.00"),
        "drawdown_from_peak": Decimal("3150.00"),
        "drawdown_percent": Decimal("3.0732"),
        "trades_count": 8,
        "winning_trades": 3,
        "losing_trades": 5,
        "total_volume": Decimal("1.20"),
    }


@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy async engine with connect() context manager."""
    with patch("src.snapshots.snapshot_db_writer.create_async_engine") as mock:
        engine = MagicMock()
        engine.dispose = AsyncMock()
        # Support start() connection validation: async with engine.connect() as conn
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        engine.connect = MagicMock(return_value=mock_conn)
        mock.return_value = engine
        yield engine


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy async session with begin() context manager."""
    session = MagicMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=None)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_cm)
    session.execute = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    return session


# ======================
# 5.1: from_snapshot_data maps all 17 columns
# ======================

class TestAccountSnapshotModelFromSnapshotData:
    """Test AccountSnapshotModel.from_snapshot_data() mapping."""

    def test_maps_all_17_columns(self, sample_snapshot_data):
        model = AccountSnapshotModel.from_snapshot_data(sample_snapshot_data)

        assert model.account_id == "ftmo-gold-001"
        assert model.snapshot_date == date(2025, 12, 3)
        assert model.snapshot_time == time(0, 0, 0)
        assert model.opening_balance == Decimal("100000.00")
        assert model.closing_balance == Decimal("99350.00")
        assert model.high_balance == Decimal("101200.00")
        assert model.low_balance == Decimal("99100.00")
        assert model.daily_pnl == Decimal("-650.00")
        assert model.daily_pnl_percent == Decimal("-0.6500")
        assert model.peak_balance == Decimal("102500.00")
        assert model.drawdown_from_peak == Decimal("3150.00")
        assert model.drawdown_percent == Decimal("3.0732")
        assert model.trades_count == 8
        assert model.winning_trades == 3
        assert model.losing_trades == 5
        assert model.total_volume == Decimal("1.20")

    def test_handles_none_financial_fields(self):
        data = {
            "account_id": "ftmo-test-001",
            "snapshot_date": date(2025, 12, 3),
            "opening_balance": None,
            "closing_balance": None,
            "high_balance": None,
            "low_balance": None,
            "daily_pnl": None,
            "daily_pnl_percent": None,
            "peak_balance": None,
            "drawdown_from_peak": None,
            "drawdown_percent": None,
            "total_volume": None,
        }
        model = AccountSnapshotModel.from_snapshot_data(data)

        assert model.opening_balance is None
        assert model.closing_balance is None
        assert model.daily_pnl is None
        assert model.trades_count == 0
        assert model.total_volume == Decimal("0")

    def test_converts_float_to_decimal_via_str(self):
        """Ensure floats are converted to Decimal through str() to avoid precision loss."""
        data = {
            "account_id": "ftmo-test-001",
            "snapshot_date": date(2025, 12, 3),
            "opening_balance": 100000.00,
            "closing_balance": 99350.50,
        }
        model = AccountSnapshotModel.from_snapshot_data(data)
        # Decimal(str(100000.00)) == Decimal('100000.0')
        assert isinstance(model.opening_balance, Decimal)
        assert isinstance(model.closing_balance, Decimal)

    def test_default_snapshot_time(self):
        data = {"account_id": "test", "snapshot_date": date(2025, 12, 3)}
        model = AccountSnapshotModel.from_snapshot_data(data)
        assert model.snapshot_time == time(0, 0, 0)


# ======================
# 5.2: to_dict preserves DECIMAL precision
# ======================

class TestAccountSnapshotModelToDict:
    """Test AccountSnapshotModel.to_dict() serialization."""

    def test_financial_fields_as_strings(self, sample_snapshot_data):
        model = AccountSnapshotModel.from_snapshot_data(sample_snapshot_data)
        d = model.to_dict()

        assert d["opening_balance"] == "100000.00"
        assert d["closing_balance"] == "99350.00"
        assert d["high_balance"] == "101200.00"
        assert d["low_balance"] == "99100.00"
        assert d["daily_pnl"] == "-650.00"
        assert d["daily_pnl_percent"] == "-0.6500"
        assert d["peak_balance"] == "102500.00"
        assert d["drawdown_from_peak"] == "3150.00"
        assert d["drawdown_percent"] == "3.0732"
        assert d["total_volume"] == "1.20"

    def test_none_fields_serialize_as_none(self):
        data = {
            "account_id": "test",
            "snapshot_date": date(2025, 12, 3),
            "opening_balance": None,
        }
        model = AccountSnapshotModel.from_snapshot_data(data)
        d = model.to_dict()
        assert d["opening_balance"] is None

    def test_integer_fields_as_integers(self, sample_snapshot_data):
        model = AccountSnapshotModel.from_snapshot_data(sample_snapshot_data)
        d = model.to_dict()

        assert d["trades_count"] == 8
        assert d["winning_trades"] == 3
        assert d["losing_trades"] == 5
        assert isinstance(d["trades_count"], int)

    def test_no_float_conversion(self, sample_snapshot_data):
        """Verify that Decimal values are serialized as strings, never floats."""
        model = AccountSnapshotModel.from_snapshot_data(sample_snapshot_data)
        d = model.to_dict()
        for key in ["opening_balance", "closing_balance", "daily_pnl", "peak_balance"]:
            assert isinstance(d[key], str), f"{key} should be str, got {type(d[key])}"


# ======================
# 5.3: SnapshotDBWriter.write_snapshot() calls session correctly
# ======================

class TestSnapshotDBWriterWriteSnapshot:
    """Test SnapshotDBWriter.write_snapshot()."""

    @pytest.mark.asyncio
    async def test_write_snapshot_executes_upsert(
        self, sample_snapshot_data, mock_engine, mock_session,
    ):
        with patch("src.snapshots.snapshot_db_writer.async_sessionmaker") as mock_factory:
            mock_factory.return_value = MagicMock(return_value=mock_session)

            writer = SnapshotDBWriter("postgresql+asyncpg://test:test@localhost/test")
            await writer.start()
            await writer.write_snapshot(sample_snapshot_data)

            # Session execute was called with the upsert statement
            mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, mock_engine):
        with patch("src.snapshots.snapshot_db_writer.async_sessionmaker"):
            writer = SnapshotDBWriter("postgresql+asyncpg://test:test@localhost/test")

            assert not writer.is_running
            await writer.start()
            assert writer.is_running
            await writer.stop()
            assert not writer.is_running


# ======================
# 5.4: Upsert handles duplicate (account_id, snapshot_date)
# ======================

class TestSnapshotDBWriterUpsert:
    """Test SnapshotDBWriter upsert behavior."""

    @pytest.mark.asyncio
    async def test_upsert_uses_on_conflict_do_update(
        self, sample_snapshot_data, mock_engine, mock_session,
    ):
        """Verify the INSERT statement uses ON CONFLICT DO UPDATE."""
        with patch("src.snapshots.snapshot_db_writer.async_sessionmaker") as mock_factory:
            mock_factory.return_value = MagicMock(return_value=mock_session)

            writer = SnapshotDBWriter("postgresql+asyncpg://test:test@localhost/test")
            await writer.start()
            await writer.write_snapshot(sample_snapshot_data)

            call_args = mock_session.execute.call_args
            stmt = call_args[0][0]
            # The compiled statement should be a PostgreSQL INSERT with ON CONFLICT
            compiled = stmt.compile(
                dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()
            )
            sql_text = str(compiled)
            assert "ON CONFLICT" in sql_text
            assert "DO UPDATE SET" in sql_text


# ======================
# 5.5: _collect_snapshot_data aggregates from Redis + DB
# ======================

class TestDailySnapshotServiceCollectData:
    """Test DailySnapshotService._collect_snapshot_data()."""

    @pytest.fixture
    def mock_risk_state(self):
        risk = MagicMock()
        risk.daily_starting_balance = Decimal("100000.00")
        risk.daily_pnl = Decimal("-650.00")
        risk.daily_pnl_percent = Decimal("-0.65")
        risk.total_drawdown_percent = Decimal("3.07")
        return risk

    @pytest.fixture
    def mock_state_snapshot(self):
        snap = MagicMock()
        snap.account_balance = Decimal("99350.00")
        snap.peak_balance = Decimal("102500.00")
        return snap

    @pytest.fixture
    def service(self):
        db_writer = MagicMock(spec=SnapshotDBWriter)
        redis_state = AsyncMock()
        account_manager = MagicMock()
        session_factory = MagicMock()
        return DailySnapshotService(
            db_writer=db_writer,
            redis_state=redis_state,
            account_manager=account_manager,
            db_session_factory=session_factory,
        )

    @pytest.mark.asyncio
    async def test_collects_from_redis_and_db(
        self, service, mock_risk_state, mock_state_snapshot,
    ):
        service._redis_state.get_risk_state = AsyncMock(return_value=mock_risk_state)
        service._redis_state.get_snapshot = AsyncMock(return_value=mock_state_snapshot)

        # Mock the DB queries
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # High/low balance query result
        high_low_row = MagicMock()
        high_low_row.high = Decimal("101200.00")
        high_low_row.low = Decimal("99100.00")

        # Trades query result
        trades_row = MagicMock()
        trades_row.trades_count = 8
        trades_row.winning_trades = 3
        trades_row.losing_trades = 5
        trades_row.total_volume = Decimal("1.20")

        high_low_result = MagicMock()
        high_low_result.one_or_none.return_value = high_low_row

        trades_result = MagicMock()
        trades_result.one.return_value = trades_row

        mock_session.execute = AsyncMock(side_effect=[high_low_result, trades_result])
        service._session_factory.return_value = mock_session

        data = await service._collect_snapshot_data("ftmo-gold-001", date(2025, 12, 3))

        assert data["account_id"] == "ftmo-gold-001"
        assert data["opening_balance"] == Decimal("100000.00")
        assert data["closing_balance"] == Decimal("99350.00")
        assert data["high_balance"] == Decimal("101200.00")
        assert data["low_balance"] == Decimal("99100.00")
        assert data["daily_pnl"] == Decimal("-650.00")
        assert data["peak_balance"] == Decimal("102500.00")
        assert data["drawdown_from_peak"] == Decimal("3150.00")
        assert data["trades_count"] == 8
        assert data["winning_trades"] == 3
        assert data["losing_trades"] == 5
        assert data["total_volume"] == Decimal("1.20")

    @pytest.mark.asyncio
    async def test_fallback_when_no_state_snapshots(self, service, mock_risk_state, mock_state_snapshot):
        """When no state_snapshots exist for the day, high/low fallback to closing_balance."""
        service._redis_state.get_risk_state = AsyncMock(return_value=mock_risk_state)
        service._redis_state.get_snapshot = AsyncMock(return_value=mock_state_snapshot)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # No state_snapshots for the day
        high_low_row = MagicMock()
        high_low_row.high = None
        high_low_row.low = None
        high_low_result = MagicMock()
        high_low_result.one_or_none.return_value = high_low_row

        trades_row = MagicMock()
        trades_row.trades_count = 0
        trades_row.winning_trades = 0
        trades_row.losing_trades = 0
        trades_row.total_volume = Decimal("0")
        trades_result = MagicMock()
        trades_result.one.return_value = trades_row

        mock_session.execute = AsyncMock(side_effect=[high_low_result, trades_result])
        service._session_factory.return_value = mock_session

        data = await service._collect_snapshot_data("ftmo-gold-001", date(2025, 12, 3))

        # Fallback: closing_balance used for both high and low
        assert data["high_balance"] == Decimal("99350.00")
        assert data["low_balance"] == Decimal("99350.00")


# ======================
# 5.6: _calculate_seconds_until_midnight
# ======================

class TestCalculateSecondsUntilMidnight:
    """Test DailySnapshotService._calculate_seconds_until_midnight()."""

    def test_returns_positive_seconds(self):
        delay = DailySnapshotService._calculate_seconds_until_midnight()
        assert delay > 0

    def test_delay_less_than_24_hours(self):
        delay = DailySnapshotService._calculate_seconds_until_midnight()
        assert delay <= 86400  # 24 * 60 * 60

    @patch("src.snapshots.daily_snapshot_service.datetime")
    def test_at_2300_returns_approximately_1_hour(self, mock_dt):
        """At 23:00 UTC, should return ~3600 seconds."""
        fixed_now = datetime(2025, 12, 3, 23, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        delay = DailySnapshotService._calculate_seconds_until_midnight()
        assert 3500 <= delay <= 3700  # ~1 hour with some tolerance

    @patch("src.snapshots.daily_snapshot_service.datetime")
    def test_at_0001_returns_approximately_24_hours(self, mock_dt):
        """At 00:01 UTC, should return ~86340 seconds."""
        fixed_now = datetime(2025, 12, 3, 0, 1, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        delay = DailySnapshotService._calculate_seconds_until_midnight()
        assert 86200 <= delay <= 86400


# ======================
# 5.7: _take_all_snapshots continues on per-account failure
# ======================

class TestTakeAllSnapshotsErrorIsolation:
    """Test fire-and-forget error isolation in _take_all_snapshots()."""

    @pytest.mark.asyncio
    async def test_continues_after_account_failure(self):
        """If one account fails, others should still be processed."""
        db_writer = AsyncMock(spec=SnapshotDBWriter)
        redis_state = AsyncMock()
        account_manager = MagicMock()
        account_manager.get_active_account_ids.return_value = ["acc1", "acc2", "acc3"]

        service = DailySnapshotService(
            db_writer=db_writer,
            redis_state=redis_state,
            account_manager=account_manager,
            db_session_factory=MagicMock(),
        )

        call_count = 0

        async def mock_collect(account_id, snapshot_date):
            nonlocal call_count
            call_count += 1
            if account_id == "acc2":
                raise RuntimeError("Redis connection lost")
            return {
                "account_id": account_id,
                "snapshot_date": snapshot_date,
                "opening_balance": Decimal("100000"),
                "closing_balance": Decimal("100000"),
            }

        service._collect_snapshot_data = mock_collect

        await service._take_all_snapshots()

        # All 3 accounts were attempted
        assert call_count == 3
        # 2 writes succeeded (acc1, acc3)
        assert db_writer.write_snapshot.call_count == 2

    @pytest.mark.asyncio
    async def test_no_accounts_no_error(self):
        """Empty active accounts list should complete without error."""
        db_writer = AsyncMock(spec=SnapshotDBWriter)
        account_manager = MagicMock()
        account_manager.get_active_account_ids.return_value = []

        service = DailySnapshotService(
            db_writer=db_writer,
            redis_state=AsyncMock(),
            account_manager=account_manager,
            db_session_factory=MagicMock(),
        )

        await service._take_all_snapshots()
        db_writer.write_snapshot.assert_not_called()


# ======================
# 5.8: drawdown_from_peak calculation
# ======================

class TestDrawdownFromPeakCalculation:
    """Test drawdown_from_peak = peak_balance - closing_balance."""

    @pytest.mark.asyncio
    async def test_drawdown_from_peak_correct(self):
        """Verify derived field: drawdown_from_peak = peak_balance - closing_balance."""
        service = DailySnapshotService(
            db_writer=AsyncMock(spec=SnapshotDBWriter),
            redis_state=AsyncMock(),
            account_manager=MagicMock(),
            db_session_factory=MagicMock(),
        )

        risk_state = MagicMock()
        risk_state.daily_starting_balance = Decimal("100000.00")
        risk_state.daily_pnl = Decimal("-650.00")
        risk_state.daily_pnl_percent = Decimal("-0.65")
        risk_state.total_drawdown_percent = Decimal("3.07")

        state_snapshot = MagicMock()
        state_snapshot.account_balance = Decimal("99350.00")
        state_snapshot.peak_balance = Decimal("102500.00")

        service._redis_state.get_risk_state = AsyncMock(return_value=risk_state)
        service._redis_state.get_snapshot = AsyncMock(return_value=state_snapshot)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        high_low_row = MagicMock()
        high_low_row.high = Decimal("101200.00")
        high_low_row.low = Decimal("99100.00")
        high_low_result = MagicMock()
        high_low_result.one_or_none.return_value = high_low_row

        trades_row = MagicMock()
        trades_row.trades_count = 8
        trades_row.winning_trades = 3
        trades_row.losing_trades = 5
        trades_row.total_volume = Decimal("1.20")
        trades_result = MagicMock()
        trades_result.one.return_value = trades_row

        mock_session.execute = AsyncMock(side_effect=[high_low_result, trades_result])
        service._session_factory.return_value = mock_session

        data = await service._collect_snapshot_data("ftmo-gold-001", date(2025, 12, 3))

        # drawdown_from_peak = 102500.00 - 99350.00 = 3150.00
        assert data["drawdown_from_peak"] == Decimal("3150.00")

    @pytest.mark.asyncio
    async def test_drawdown_none_when_peak_or_closing_missing(self):
        """drawdown_from_peak should be None when peak or closing balance is unavailable."""
        service = DailySnapshotService(
            db_writer=AsyncMock(spec=SnapshotDBWriter),
            redis_state=AsyncMock(),
            account_manager=MagicMock(),
            db_session_factory=MagicMock(),
        )

        # No Redis data
        service._redis_state.get_risk_state = AsyncMock(return_value=None)
        service._redis_state.get_snapshot = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        high_low_row = MagicMock()
        high_low_row.high = None
        high_low_row.low = None
        high_low_result = MagicMock()
        high_low_result.one_or_none.return_value = high_low_row

        trades_row = MagicMock()
        trades_row.trades_count = 0
        trades_row.winning_trades = 0
        trades_row.losing_trades = 0
        trades_row.total_volume = Decimal("0")
        trades_result = MagicMock()
        trades_result.one.return_value = trades_row

        mock_session.execute = AsyncMock(side_effect=[high_low_result, trades_result])
        service._session_factory.return_value = mock_session

        data = await service._collect_snapshot_data("ftmo-gold-001", date(2025, 12, 3))

        assert data["drawdown_from_peak"] is None


# ======================
# Additional: AccountManager.get_active_account_ids
# ======================

class TestAccountManagerGetActiveAccountIds:
    """Test the new get_active_account_ids method."""

    def test_returns_only_active_accounts(self):
        from src.accounts.account_manager import AccountManager

        manager = AccountManager(redis_manager=MagicMock())
        # Simulate loaded accounts with various statuses
        mock_active = MagicMock()
        mock_active.status = "active"
        mock_stopped = MagicMock()
        mock_stopped.status = "stopped"
        mock_paused = MagicMock()
        mock_paused.status = "active"

        manager._accounts = {
            "acc1": mock_active,
            "acc2": mock_stopped,
            "acc3": mock_paused,
        }

        result = manager.get_active_account_ids()
        assert sorted(result) == ["acc1", "acc3"]

    def test_returns_empty_when_no_accounts(self):
        from src.accounts.account_manager import AccountManager

        manager = AccountManager(redis_manager=MagicMock())
        manager._accounts = {}
        assert manager.get_active_account_ids() == []


# ======================
# Additional: Engine integration
# ======================

class TestEngineSnapshotIntegration:
    """Test TradingEngine daily snapshot initialization."""

    @pytest.mark.asyncio
    async def test_initialize_daily_snapshots_without_database_url(self):
        """Should skip when no database URL configured."""
        from src.engine import TradingEngine

        engine = TradingEngine(database_url=None)
        await engine._initialize_daily_snapshots()
        assert engine._daily_snapshot_service is None

    @pytest.mark.asyncio
    async def test_initialize_daily_snapshots_without_dependencies(self):
        """Should skip when required dependencies missing."""
        from src.engine import TradingEngine

        engine = TradingEngine(
            database_url="postgresql+asyncpg://test@localhost/test",
            redis_manager=None,
        )
        await engine._initialize_daily_snapshots()
        assert engine._daily_snapshot_service is None
