"""Integration tests for Daily Account Snapshots (Story 7.4).

Tests cover:
- 5.9: Full flow from Redis state + trades query → account_snapshots INSERT
- 5.10: Upsert overwrites existing snapshot for same account+date
- 5.11: Engine lifecycle start → snapshot service running → shutdown stops service
- 5.12: Compliance query: trading days count WHERE trades_count > 0
"""

import asyncio
from datetime import date, time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.snapshots.daily_snapshot_service import DailySnapshotService
from src.snapshots.models import AccountSnapshotModel
from src.snapshots.snapshot_db_writer import SnapshotDBWriter


# ======================
# 5.9: Full flow from Redis state + trades query → account_snapshots INSERT
# ======================

class TestFullSnapshotFlow:
    """Integration test: full pipeline from data sources to DB write."""

    @pytest.mark.asyncio
    async def test_full_flow_redis_to_db(self):
        """Test complete flow: Redis state + DB queries → SnapshotDBWriter.write_snapshot()."""
        # Set up mocks for all data sources
        mock_risk_state = MagicMock()
        mock_risk_state.daily_starting_balance = Decimal("100000.00")
        mock_risk_state.daily_pnl = Decimal("-650.00")
        mock_risk_state.daily_pnl_percent = Decimal("-0.65")
        mock_risk_state.total_drawdown_percent = Decimal("3.07")

        mock_state_snapshot = MagicMock()
        mock_state_snapshot.account_balance = Decimal("99350.00")
        mock_state_snapshot.peak_balance = Decimal("102500.00")

        redis_state = AsyncMock()
        redis_state.get_risk_state = AsyncMock(return_value=mock_risk_state)
        redis_state.get_snapshot = AsyncMock(return_value=mock_state_snapshot)

        db_writer = AsyncMock(spec=SnapshotDBWriter)
        account_manager = MagicMock()
        account_manager.get_active_account_ids.return_value = ["ftmo-gold-001"]

        # Mock DB session for queries
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

        session_factory = MagicMock()
        session_factory.return_value = mock_session

        service = DailySnapshotService(
            db_writer=db_writer,
            redis_state=redis_state,
            account_manager=account_manager,
            db_session_factory=session_factory,
        )

        from src.snapshots.daily_snapshot_service import DEFAULT_SESSION
        await service._take_snapshots_for_session(
            DEFAULT_SESSION,
            account_manager.get_active_account_ids.return_value,
            date(2025, 12, 3),
        )

        # Verify write_snapshot was called with correct data
        db_writer.write_snapshot.assert_called_once()
        call_args = db_writer.write_snapshot.call_args[0][0]

        assert call_args["account_id"] == "ftmo-gold-001"
        assert call_args["opening_balance"] == Decimal("100000.00")
        assert call_args["closing_balance"] == Decimal("99350.00")
        assert call_args["high_balance"] == Decimal("101200.00")
        assert call_args["low_balance"] == Decimal("99100.00")
        assert call_args["daily_pnl"] == Decimal("-650.00")
        assert call_args["peak_balance"] == Decimal("102500.00")
        assert call_args["drawdown_from_peak"] == Decimal("3150.00")
        assert call_args["trades_count"] == 8
        assert call_args["winning_trades"] == 3
        assert call_args["losing_trades"] == 5
        assert call_args["total_volume"] == Decimal("1.20")


# ======================
# 5.10: Upsert overwrites existing snapshot for same account+date
# ======================

class TestUpsertIdempotency:
    """Integration test: upsert behavior for duplicate (account_id, snapshot_date)."""

    @pytest.mark.asyncio
    async def test_second_write_updates_not_duplicates(self):
        """Writing twice for the same account+date should produce one upsert each time."""
        snapshot_data = {
            "account_id": "ftmo-gold-001",
            "snapshot_date": date(2025, 12, 3),
            "snapshot_time": time(0, 0, 0),
            "opening_balance": Decimal("100000.00"),
            "closing_balance": Decimal("99350.00"),
            "high_balance": Decimal("101200.00"),
            "low_balance": Decimal("99100.00"),
            "daily_pnl": Decimal("-650.00"),
            "daily_pnl_percent": Decimal("-0.65"),
            "peak_balance": Decimal("102500.00"),
            "drawdown_from_peak": Decimal("3150.00"),
            "drawdown_percent": Decimal("3.07"),
            "trades_count": 8,
            "winning_trades": 3,
            "losing_trades": 5,
            "total_volume": Decimal("1.20"),
        }

        mock_session = MagicMock()
        begin_cm = MagicMock()
        begin_cm.__aenter__ = AsyncMock(return_value=None)
        begin_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.begin = MagicMock(return_value=begin_cm)
        mock_session.execute = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("src.snapshots.snapshot_db_writer.create_async_engine") as mock_eng:
            engine = MagicMock()
            engine.dispose = AsyncMock()
            mock_conn = MagicMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            engine.connect = MagicMock(return_value=mock_conn)
            mock_eng.return_value = engine

            with patch("src.snapshots.snapshot_db_writer.async_sessionmaker") as mock_factory:
                mock_factory.return_value = MagicMock(return_value=mock_session)

                writer = SnapshotDBWriter("postgresql+asyncpg://test@localhost/test")
                await writer.start()

                # First write
                await writer.write_snapshot(snapshot_data)

                # Update closing_balance and write again (simulating engine restart)
                snapshot_data["closing_balance"] = Decimal("99500.00")
                await writer.write_snapshot(snapshot_data)

                # Both calls used ON CONFLICT (verified by statement structure)
                assert mock_session.execute.call_count == 2

                second_stmt = mock_session.execute.call_args_list[1][0][0]
                compiled = second_stmt.compile(
                    dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()
                )
                assert "ON CONFLICT" in str(compiled)


# ======================
# 5.11: Engine lifecycle start → snapshot service running → shutdown stops service
# ======================

class TestEngineLifecycle:
    """Integration test: build_lifecycle wires the daily snapshot service
    into LiveOrchestrator and start/stop drive it (story 10.2 DI flow)."""

    @pytest.mark.asyncio
    async def test_di_builder_wires_snapshot_service_into_live(self):
        """`build_lifecycle` constructs DailySnapshotService and LiveOrchestrator drives it."""
        from src.engine import EngineConfig, build_lifecycle

        redis_manager = AsyncMock()
        account_manager = MagicMock()
        account_manager.get_all_accounts.return_value = []
        session_factory = MagicMock()

        config = EngineConfig(
            redis_manager=redis_manager,
            account_manager=account_manager,
            db_session_factory=session_factory,
            database_url="postgresql+asyncpg://test@localhost/test",
        )

        with patch("src.snapshots.snapshot_db_writer.create_async_engine") as mock_eng, \
             patch("src.snapshots.snapshot_db_writer.async_sessionmaker"):
            mock_sa_engine = MagicMock()
            mock_sa_engine.dispose = AsyncMock()
            mock_conn = MagicMock()
            mock_conn.execute = AsyncMock()
            mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_conn.__aexit__ = AsyncMock(return_value=None)
            mock_sa_engine.connect = MagicMock(return_value=mock_conn)
            mock_eng.return_value = mock_sa_engine

            mock_service_instance = AsyncMock()
            mock_service_instance.is_running = True
            with patch(
                "src.engine.DailySnapshotService",
                return_value=mock_service_instance,
            ):
                lifecycle = build_lifecycle(config)
                assert (
                    lifecycle._live._services.daily_snapshot_service
                    is mock_service_instance
                )

                await lifecycle._live.start()
                mock_service_instance.start.assert_awaited()

                await lifecycle._live.stop()
                mock_service_instance.stop.assert_awaited()


# ======================
# 5.12: Compliance query: trading days count WHERE trades_count > 0
# ======================

class TestComplianceQuery:
    """Integration test: verify AccountSnapshotModel supports compliance queries."""

    def test_model_supports_trading_days_query(self):
        """Verify the model has the trades_count column for compliance queries.

        AC #3: SELECT COUNT(*) as trading_days
               FROM account_snapshots
               WHERE account_id = ? AND trades_count > 0
        """
        # Verify column exists and has correct type
        columns = {c.name: c for c in AccountSnapshotModel.__table__.columns}
        assert "trades_count" in columns
        assert "account_id" in columns
        assert "snapshot_date" in columns

    def test_model_has_unique_constraint(self):
        """Verify UNIQUE(account_id, snapshot_date) constraint exists for upsert."""
        constraints = AccountSnapshotModel.__table__.constraints
        unique_constraints = [
            c for c in constraints
            if hasattr(c, "columns") and len(c.columns) == 2
        ]
        # Should have the composite unique constraint
        assert len(unique_constraints) >= 1

    def test_model_has_all_17_data_columns(self):
        """Verify all 17 data columns from init.sql are mapped."""
        expected_columns = {
            "id", "account_id", "snapshot_date", "snapshot_time",
            "opening_balance", "closing_balance",
            "high_balance", "low_balance",
            "daily_pnl", "daily_pnl_percent",
            "peak_balance", "drawdown_from_peak", "drawdown_percent",
            "trades_count", "winning_trades", "losing_trades", "total_volume",
            "created_at",
        }
        actual_columns = {c.name for c in AccountSnapshotModel.__table__.columns}
        assert expected_columns == actual_columns

    def test_trading_days_count_from_models(self):
        """Create models and count those with trades_count > 0."""
        snapshots = [
            AccountSnapshotModel.from_snapshot_data({
                "account_id": "ftmo-gold-001",
                "snapshot_date": date(2025, 12, d),
                "trades_count": trades,
            })
            for d, trades in [(1, 5), (2, 0), (3, 3), (4, 0), (5, 1)]
        ]

        trading_days = sum(1 for s in snapshots if s.trades_count > 0)
        assert trading_days == 3  # Days 1, 3, 5 had trades


# ======================
# Additional: Multi-account snapshot flow
# ======================

class TestMultiAccountFlow:
    """Integration test: multi-account snapshot collection."""

    @pytest.mark.asyncio
    async def test_multiple_accounts_each_get_snapshot(self):
        """Verify all active accounts get their own snapshot."""
        db_writer = AsyncMock(spec=SnapshotDBWriter)
        redis_state = AsyncMock()
        account_manager = MagicMock()
        account_manager.get_active_account_ids.return_value = [
            "ftmo-gold-001",
            "ftmo-eurusd-002",
        ]

        service = DailySnapshotService(
            db_writer=db_writer,
            redis_state=redis_state,
            account_manager=account_manager,
            db_session_factory=MagicMock(),
        )

        async def mock_collect(account_id, snapshot_date, session=None):
            return {
                "account_id": account_id,
                "snapshot_date": snapshot_date,
                "opening_balance": Decimal("100000"),
                "closing_balance": Decimal("100000"),
            }

        service._collect_snapshot_data = mock_collect

        from src.snapshots.daily_snapshot_service import DEFAULT_SESSION
        await service._take_snapshots_for_session(
            DEFAULT_SESSION,
            account_manager.get_active_account_ids.return_value,
            date(2025, 12, 3),
        )

        assert db_writer.write_snapshot.call_count == 2
        call_accounts = [
            call[0][0]["account_id"]
            for call in db_writer.write_snapshot.call_args_list
        ]
        assert "ftmo-gold-001" in call_accounts
        assert "ftmo-eurusd-002" in call_accounts
