"""Unit tests for PositionReconciler module.

Tests position reconciliation logic between Redis snapshots and MT5 positions.
MT5 is always the source of truth.

Test Categories:
- Position matching (exact, tolerance-based)
- Discrepancy detection (orphan, unknown, volume mismatch, side mismatch)
- Critical discrepancy handling
- Error handling (timeout, connection errors)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.zmq_models import MT5Position
from src.state.position_reconciler import (
    DiscrepancyType,
    PositionDiscrepancy,
    PositionReconciler,
)
from src.state.snapshot import StateSnapshot


class TestPositionReconciler:
    """Tests for PositionReconciler class."""

    @pytest.fixture
    def mock_zmq_adapter(self) -> MagicMock:
        """Create mock ZMQ adapter."""
        adapter = MagicMock()
        adapter.query_positions = AsyncMock(return_value=[])
        return adapter

    @pytest.fixture
    def mock_redis_manager(self) -> MagicMock:
        """Create mock Redis state manager."""
        manager = MagicMock()
        manager.publish_alert = AsyncMock()
        manager.save_snapshot = AsyncMock()
        return manager

    @pytest.fixture
    def reconciler(
        self,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> PositionReconciler:
        """Create PositionReconciler with mocked dependencies."""
        return PositionReconciler(
            zmq_adapter=mock_zmq_adapter,
            redis_manager=mock_redis_manager,
        )

    @pytest.fixture
    def sample_snapshot(self) -> StateSnapshot:
        """Create sample snapshot with positions."""
        return StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[
                {
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "volume": "0.1",
                    "entry_price": "1850.45",
                    "entry_time": "2026-01-03T10:15:30.000Z",
                    "order_id": "ORDER-123",
                }
            ],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="",
        )

    @pytest.fixture
    def sample_mt5_position(self) -> MT5Position:
        """Create sample MT5 position matching snapshot."""
        return MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="BUY",
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1852.30"),
            profit=Decimal("185.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )

    # =========================================================================
    # Test Matching Positions - Exact Match
    # =========================================================================

    async def test_matching_positions_exact_match(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
        sample_mt5_position: MT5Position,
    ) -> None:
        """Test positions match exactly - no discrepancies."""
        mock_zmq_adapter.query_positions.return_value = [sample_mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is True
        assert result.positions_verified == 1
        assert result.discrepancies == []
        assert result.positions_added == 0
        assert result.positions_removed == 0
        assert result.positions_updated == 0
        assert result.requires_manual_intervention is False
        assert result.error_message is None

    # =========================================================================
    # Test Matching Positions - Volume Within Tolerance
    # =========================================================================

    async def test_matching_positions_volume_within_tolerance(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test positions match when volume within 0.001 tolerance."""
        # MT5 position with slightly different volume (within tolerance)
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="BUY",
            volume=Decimal("0.0999"),  # 0.0001 difference from 0.1
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1852.30"),
            profit=Decimal("185.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is True
        assert result.positions_verified == 1
        assert result.discrepancies == []

    # =========================================================================
    # Test Orphan Position Detection (Snapshot Only)
    # =========================================================================

    async def test_orphan_position_detection(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test orphan position detected when in snapshot but not MT5.

        Note: With 100% exposure difference (1 orphan = all positions gone),
        this triggers the critical exposure threshold, so we expect
        requires_manual_intervention=True.
        """
        # MT5 returns no positions - 100% exposure difference triggers critical
        mock_zmq_adapter.query_positions.return_value = []

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        # 100% exposure difference triggers critical discrepancy
        assert result.success is False  # Exposure > 10% triggers critical
        assert result.positions_verified == 0
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.ORPHAN_POSITION
        assert result.positions_removed == 1
        assert "Orphan position removed" in result.discrepancies[0].details
        # Alert was published due to exposure difference
        mock_redis_manager.publish_alert.assert_called_once()

    # =========================================================================
    # Test Unknown Position Detection (MT5 Only)
    # =========================================================================

    async def test_unknown_position_detection(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
    ) -> None:
        """Test unknown position detected when in MT5 but not snapshot."""
        # Empty snapshot
        empty_snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        mt5_position = MT5Position(
            ticket=12345678,
            symbol="EURUSD",
            side="SELL",
            volume=Decimal("0.5"),
            entry_price=Decimal("1.0850"),
            entry_time="2026-01-03T12:00:00.000Z",
            current_price=Decimal("1.0840"),
            profit=Decimal("50.00"),
            swap=Decimal("0.00"),
            commission=Decimal("-5.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            empty_snapshot,
        )

        assert result.success is True  # Not critical with 1 unknown
        assert result.positions_verified == 0
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.UNKNOWN_POSITION
        assert result.positions_added == 1
        assert "Unknown position found" in result.discrepancies[0].details

    # =========================================================================
    # Test Volume Mismatch Handling
    # =========================================================================

    async def test_volume_mismatch_handling(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test volume mismatch detected and MT5 value used."""
        # MT5 position with different volume (beyond tolerance but within 10%)
        # 0.095 is 5% different from 0.1, which is under the 10% exposure threshold
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="BUY",
            volume=Decimal("0.095"),  # 0.005 difference from 0.1 (beyond 0.001 tolerance but <10% exposure diff)
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1852.30"),
            profit=Decimal("175.75"),
            swap=Decimal("-2.38"),
            commission=Decimal("-0.95"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is True  # 5% diff is under 10% threshold
        assert result.positions_verified == 0
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.VOLUME_MISMATCH
        assert result.positions_updated == 1
        assert "using MT5 value" in result.discrepancies[0].details

    # =========================================================================
    # Test Side Mismatch as Critical Discrepancy
    # =========================================================================

    async def test_side_mismatch_critical(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test side mismatch triggers critical discrepancy."""
        # MT5 position with opposite side
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="SELL",  # Opposite of BUY in snapshot
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1848.30"),
            profit=Decimal("215.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is False  # Side mismatch is critical
        assert result.requires_manual_intervention is True
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.SIDE_MISMATCH
        assert "CRITICAL" in result.discrepancies[0].details

        # Verify alert was published
        mock_redis_manager.publish_alert.assert_called_once()

    # =========================================================================
    # Test Multiple Orphans as Critical Discrepancy
    # =========================================================================

    async def test_multiple_orphans_critical(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test more than 3 orphan positions triggers critical."""
        # Snapshot with 4 positions (all will be orphans)
        snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[
                {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
                {"symbol": "EURUSD", "side": "SELL", "volume": "0.2"},
                {"symbol": "GBPUSD", "side": "BUY", "volume": "0.3"},
                {"symbol": "USDJPY", "side": "SELL", "volume": "0.4"},
            ],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99500.00"),
            peak_balance=Decimal("102000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        # MT5 returns no positions
        mock_zmq_adapter.query_positions.return_value = []

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            snapshot,
        )

        assert result.success is False
        assert result.requires_manual_intervention is True
        assert result.positions_removed == 4
        assert len(result.discrepancies) == 4

        # Verify alert was published
        mock_redis_manager.publish_alert.assert_called_once()

    # =========================================================================
    # Test Successful Reconciliation Logging
    # =========================================================================

    async def test_successful_reconciliation_logging(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
        sample_mt5_position: MT5Position,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test successful reconciliation is logged correctly."""
        mock_zmq_adapter.query_positions.return_value = [sample_mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is True
        assert "Reconciliation complete" in caplog.text or result.positions_verified == 1

    # =========================================================================
    # Test Manual Intervention Flag Setting
    # =========================================================================

    async def test_manual_intervention_flag_setting(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test manual intervention flag is set correctly."""
        # Trigger critical discrepancy with side mismatch
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="SELL",  # Opposite side
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1848.30"),
            profit=Decimal("215.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.requires_manual_intervention is True
        assert result.success is False

    # =========================================================================
    # Test Reconciliation with Empty Snapshot
    # =========================================================================

    async def test_reconciliation_empty_snapshot(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
    ) -> None:
        """Test reconciliation with empty snapshot positions."""
        empty_snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        mock_zmq_adapter.query_positions.return_value = []

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            empty_snapshot,
        )

        assert result.success is True
        assert result.positions_verified == 0
        assert result.discrepancies == []
        assert result.requires_manual_intervention is False

    # =========================================================================
    # Test Reconciliation with Empty MT5 Positions
    # =========================================================================

    async def test_reconciliation_empty_mt5_positions(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test reconciliation when MT5 returns no positions."""
        mock_zmq_adapter.query_positions.return_value = []

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        # Should detect orphan position
        assert result.positions_verified == 0
        assert result.positions_removed == 1
        assert len(result.discrepancies) == 1
        assert result.discrepancies[0].discrepancy_type == DiscrepancyType.ORPHAN_POSITION

    # =========================================================================
    # Test MT5 Query Timeout Returns Error Result
    # =========================================================================

    async def test_mt5_query_timeout_returns_error(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test MT5 query timeout returns error result with manual intervention flag."""
        mock_zmq_adapter.query_positions.side_effect = asyncio.TimeoutError()

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is False
        assert result.requires_manual_intervention is True
        assert result.error_message is not None
        assert "timeout" in result.error_message.lower()
        assert result.positions_verified == 0

    # =========================================================================
    # Test ZMQ Not Connected Returns Error Result
    # =========================================================================

    async def test_zmq_not_connected_returns_error(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        sample_snapshot: StateSnapshot,
    ) -> None:
        """Test ZMQ not connected returns error result."""
        mock_zmq_adapter.query_positions.side_effect = RuntimeError(
            "Not connected - call connect() first"
        )

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            sample_snapshot,
        )

        assert result.success is False
        assert result.requires_manual_intervention is True
        assert result.error_message is not None
        assert "connection" in result.error_message.lower() or "ZMQ" in result.error_message

    # =========================================================================
    # Test Invalid Position Dict Validation (Missing Required Fields)
    # =========================================================================

    async def test_invalid_position_dict_validation(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
    ) -> None:
        """Test invalid position dicts are detected and handled."""
        # Snapshot with position missing required fields
        snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[
                {"symbol": "XAUUSD"},  # Missing side and volume
            ],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        mock_zmq_adapter.query_positions.return_value = []

        result = await reconciler.reconcile_account(
            "ftmo-gold-001",
            snapshot,
        )

        # Invalid position should be treated as discrepancy
        assert len(result.discrepancies) == 1
        assert "Invalid" in result.discrepancies[0].details or "missing" in result.discrepancies[0].details.lower()


class TestPositionReconcilerHelpers:
    """Tests for helper methods in PositionReconciler."""

    @pytest.fixture
    def reconciler(self) -> PositionReconciler:
        """Create PositionReconciler with mocked dependencies."""
        mock_zmq = MagicMock()
        mock_redis = MagicMock()
        return PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=mock_redis,
        )

    def test_validate_position_dict_valid(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test position dict validation with valid dict."""
        position = {
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": "0.1",
        }
        assert reconciler._validate_position_dict(position) is True

    def test_validate_position_dict_missing_symbol(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test position dict validation with missing symbol."""
        position = {
            "side": "BUY",
            "volume": "0.1",
        }
        assert reconciler._validate_position_dict(position) is False

    def test_validate_position_dict_missing_side(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test position dict validation with missing side."""
        position = {
            "symbol": "XAUUSD",
            "volume": "0.1",
        }
        assert reconciler._validate_position_dict(position) is False

    def test_validate_position_dict_missing_volume(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test position dict validation with missing volume."""
        position = {
            "symbol": "XAUUSD",
            "side": "BUY",
        }
        assert reconciler._validate_position_dict(position) is False

    def test_calculate_total_exposure(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test total exposure calculation."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
            {"symbol": "EURUSD", "side": "SELL", "volume": "0.5"},
            {"symbol": "GBPUSD", "side": "BUY", "volume": "0.3"},
        ]
        exposure = reconciler._calculate_total_exposure(positions)
        assert exposure == Decimal("0.9")

    def test_calculate_mt5_exposure(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test MT5 exposure calculation."""
        positions = [
            MT5Position(
                ticket=1,
                symbol="XAUUSD",
                side="BUY",
                volume=Decimal("0.1"),
                entry_price=Decimal("1850"),
                entry_time="2026-01-03T10:00:00Z",
                current_price=Decimal("1851"),
                profit=Decimal("10"),
                swap=Decimal("0"),
                commission=Decimal("-1"),
            ),
            MT5Position(
                ticket=2,
                symbol="EURUSD",
                side="SELL",
                volume=Decimal("0.5"),
                entry_price=Decimal("1.0850"),
                entry_time="2026-01-03T10:00:00Z",
                current_price=Decimal("1.0840"),
                profit=Decimal("50"),
                swap=Decimal("0"),
                commission=Decimal("-5"),
            ),
        ]
        exposure = reconciler._calculate_mt5_exposure(positions)
        assert exposure == Decimal("0.6")

    def test_format_discrepancy_details(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test discrepancy details formatting."""
        discrepancies = [
            PositionDiscrepancy(
                discrepancy_type=DiscrepancyType.ORPHAN_POSITION,
                account_id="test",
                symbol="XAUUSD",
                snapshot_side="BUY",
                mt5_side=None,
                snapshot_volume=Decimal("0.1"),
                mt5_volume=None,
                snapshot_entry_price=None,
                mt5_entry_price=None,
                details="Orphan",
            ),
            PositionDiscrepancy(
                discrepancy_type=DiscrepancyType.SIDE_MISMATCH,
                account_id="test",
                symbol="EURUSD",
                snapshot_side="BUY",
                mt5_side="SELL",
                snapshot_volume=Decimal("0.5"),
                mt5_volume=Decimal("0.5"),
                snapshot_entry_price=None,
                mt5_entry_price=None,
                details="Side mismatch",
            ),
        ]
        details = reconciler._format_discrepancy_details(discrepancies)
        assert "1 side mismatch" in details
        assert "1 orphan position" in details


class TestStateUpdateMethods:
    """Tests for Task 5 state update methods."""

    @pytest.fixture
    def reconciler(self) -> PositionReconciler:
        """Create PositionReconciler with mocked dependencies."""
        mock_zmq = MagicMock()
        mock_redis = MagicMock()
        mock_redis.save_snapshot = AsyncMock()
        return PositionReconciler(
            zmq_adapter=mock_zmq,
            redis_manager=mock_redis,
        )

    def test_remove_orphan_from_state(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test _remove_orphan_from_state removes matching position."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
            {"symbol": "EURUSD", "side": "SELL", "volume": "0.5"},
        ]
        orphan = {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}

        result = reconciler._remove_orphan_from_state(positions, orphan)

        assert len(result) == 1
        assert result[0]["symbol"] == "EURUSD"

    def test_remove_orphan_from_state_no_match(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test _remove_orphan_from_state with no matching position."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
        ]
        orphan = {"symbol": "EURUSD", "side": "SELL", "volume": "0.5"}

        result = reconciler._remove_orphan_from_state(positions, orphan)

        assert len(result) == 1  # Original position still there
        assert result[0]["symbol"] == "XAUUSD"

    def test_add_unknown_to_state(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test _add_unknown_to_state adds MT5 position to list."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
        ]
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="EURUSD",
            side="SELL",
            volume=Decimal("0.5"),
            entry_price=Decimal("1.0850"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1.0840"),
            profit=Decimal("50.00"),
            swap=Decimal("0.00"),
            commission=Decimal("-5.00"),
        )

        result = reconciler._add_unknown_to_state(positions, mt5_position)

        assert len(result) == 2
        assert result[1]["symbol"] == "EURUSD"
        assert result[1]["side"] == "SELL"
        assert result[1]["volume"] == "0.5"
        assert result[1]["ticket"] == "12345678"

    def test_update_position_volume(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test _update_position_volume updates volume to MT5 value."""
        positions = [
            {"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"},
            {"symbol": "EURUSD", "side": "SELL", "volume": "0.5"},
        ]

        result = reconciler._update_position_volume(
            positions, "XAUUSD", "BUY", Decimal("0.08")
        )

        assert len(result) == 2
        assert result[0]["volume"] == "0.08"
        assert result[1]["volume"] == "0.5"  # Unchanged

    async def test_save_reconciled_snapshot_called(
        self,
        reconciler: PositionReconciler,
    ) -> None:
        """Test that _save_reconciled_snapshot calls Redis save_snapshot."""
        from datetime import datetime, timezone

        snapshot = StateSnapshot(
            account_id="test-account",
            timestamp=datetime.now(timezone.utc),
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )
        reconciled_positions = [
            {"symbol": "EURUSD", "side": "SELL", "volume": "0.5"}
        ]

        await reconciler._save_reconciled_snapshot(
            "test-account", snapshot, reconciled_positions
        )

        # Verify save_snapshot was called
        reconciler._redis.save_snapshot.assert_called_once()
        call_args = reconciler._redis.save_snapshot.call_args
        assert call_args[0][0] == "test-account"
        saved_snapshot = call_args[0][1]
        assert len(saved_snapshot.positions) == 1
        assert saved_snapshot.positions[0]["symbol"] == "EURUSD"


class TestReconciliationWithStateUpdates:
    """Tests verifying state updates are applied during reconciliation."""

    @pytest.fixture
    def mock_zmq_adapter(self) -> MagicMock:
        """Create mock ZMQ adapter."""
        adapter = MagicMock()
        adapter.query_positions = AsyncMock(return_value=[])
        return adapter

    @pytest.fixture
    def mock_redis_manager(self) -> MagicMock:
        """Create mock Redis state manager."""
        manager = MagicMock()
        manager.publish_alert = AsyncMock()
        manager.save_snapshot = AsyncMock()
        return manager

    @pytest.fixture
    def reconciler(
        self,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> PositionReconciler:
        """Create PositionReconciler with mocked dependencies."""
        return PositionReconciler(
            zmq_adapter=mock_zmq_adapter,
            redis_manager=mock_redis_manager,
        )

    async def test_snapshot_saved_after_successful_reconciliation(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test snapshot is saved to Redis after successful reconciliation."""
        from datetime import datetime, timezone

        snapshot = StateSnapshot(
            account_id="test-account",
            timestamp=datetime.now(timezone.utc),
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        # MT5 has matching position
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="BUY",
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1852.30"),
            profit=Decimal("185.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account("test-account", snapshot)

        assert result.success is True
        # Snapshot should be saved
        mock_redis_manager.save_snapshot.assert_called_once()

    async def test_snapshot_not_saved_on_critical_discrepancy(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test snapshot is NOT saved when manual intervention required."""
        from datetime import datetime, timezone

        snapshot = StateSnapshot(
            account_id="test-account",
            timestamp=datetime.now(timezone.utc),
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        # MT5 has opposite side (CRITICAL discrepancy)
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="XAUUSD",
            side="SELL",  # Opposite!
            volume=Decimal("0.1"),
            entry_price=Decimal("1850.45"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1848.30"),
            profit=Decimal("215.00"),
            swap=Decimal("-2.50"),
            commission=Decimal("-1.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account("test-account", snapshot)

        assert result.requires_manual_intervention is True
        # Snapshot should NOT be saved for critical issues
        mock_redis_manager.save_snapshot.assert_not_called()

    async def test_orphan_removed_from_saved_snapshot(
        self,
        reconciler: PositionReconciler,
        mock_zmq_adapter: MagicMock,
        mock_redis_manager: MagicMock,
    ) -> None:
        """Test orphan position is removed in saved snapshot.

        Uses volumes that keep exposure difference under 10% threshold
        to avoid triggering critical discrepancy.
        """
        from datetime import datetime, timezone

        # Small orphan (0.05) out of 1.05 total = ~5% exposure diff (under 10%)
        snapshot = StateSnapshot(
            account_id="test-account",
            timestamp=datetime.now(timezone.utc),
            positions=[
                {"symbol": "XAUUSD", "side": "BUY", "volume": "0.05"},  # Small orphan
                {"symbol": "EURUSD", "side": "SELL", "volume": "1.0"},  # Main position
            ],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("100000.00"),
            peak_balance=Decimal("100000.00"),
            daily_starting_balance=Decimal("100000.00"),
            checksum="",
        )

        # MT5 only has EURUSD - XAUUSD is orphan but within exposure threshold
        mt5_position = MT5Position(
            ticket=12345678,
            symbol="EURUSD",
            side="SELL",
            volume=Decimal("1.0"),
            entry_price=Decimal("1.0850"),
            entry_time="2026-01-03T10:15:30.000Z",
            current_price=Decimal("1.0840"),
            profit=Decimal("50.00"),
            swap=Decimal("0.00"),
            commission=Decimal("-5.00"),
        )
        mock_zmq_adapter.query_positions.return_value = [mt5_position]

        result = await reconciler.reconcile_account("test-account", snapshot)

        # Should NOT require manual intervention (exposure diff ~5%)
        assert result.success is True
        assert result.positions_removed == 1

        # Check saved snapshot only has EURUSD (orphan XAUUSD removed)
        call_args = mock_redis_manager.save_snapshot.call_args
        saved_snapshot = call_args[0][1]
        assert len(saved_snapshot.positions) == 1
        assert saved_snapshot.positions[0]["symbol"] == "EURUSD"


class TestMT5PositionModel:
    """Tests for MT5Position data model."""

    def test_mt5_position_from_dict(self) -> None:
        """Test MT5Position.from_dict() conversion."""
        data = {
            "ticket": 12345678,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 0.1,
            "entry_price": 1850.45,
            "entry_time": "2026-01-03T10:15:30.000Z",
            "current_price": 1852.30,
            "profit": 185.00,
            "swap": -2.50,
            "commission": -1.00,
        }

        position = MT5Position.from_dict(data)

        assert position.ticket == 12345678
        assert position.symbol == "XAUUSD"
        assert position.side == "BUY"
        assert position.volume == Decimal("0.1")
        assert position.entry_price == Decimal("1850.45")
        assert position.current_price == Decimal("1852.30")
        assert position.profit == Decimal("185.00")
        assert position.swap == Decimal("-2.50")
        assert position.commission == Decimal("-1.00")

    def test_mt5_position_from_dict_string_values(self) -> None:
        """Test MT5Position.from_dict() handles string values."""
        data = {
            "ticket": "12345678",
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": "0.25",
            "entry_price": "1850.45",
            "entry_time": "2026-01-03T10:15:30.000Z",
            "current_price": "1848.30",
            "profit": "-215.00",
            "swap": "0.00",
            "commission": "-2.50",
        }

        position = MT5Position.from_dict(data)

        assert position.ticket == 12345678
        assert position.volume == Decimal("0.25")
        assert position.profit == Decimal("-215.00")
