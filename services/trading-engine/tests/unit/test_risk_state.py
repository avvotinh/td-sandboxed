"""Unit tests for RiskState dataclass."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.accounts.risk_state import RiskState


class TestRiskStateInitialization:
    """Tests for RiskState initialization and defaults."""

    def test_default_values(self):
        """RiskState should initialize with zero values."""
        state = RiskState()

        assert state.daily_pnl == Decimal("0")
        assert state.daily_pnl_percent == Decimal("0")
        assert state.current_equity == Decimal("0")
        assert state.peak_equity == Decimal("0")
        assert state.total_drawdown_percent == Decimal("0")
        assert state.daily_starting_balance == Decimal("0")
        assert isinstance(state.last_updated, datetime)

    def test_custom_initialization(self):
        """RiskState should accept custom values."""
        state = RiskState(
            daily_pnl=Decimal("-1000"),
            daily_pnl_percent=Decimal("-1.5"),
            current_equity=Decimal("99000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("1.0"),
            daily_starting_balance=Decimal("100000"),
        )

        assert state.daily_pnl == Decimal("-1000")
        assert state.daily_pnl_percent == Decimal("-1.5")
        assert state.current_equity == Decimal("99000")
        assert state.peak_equity == Decimal("100000")


class TestDrawdownFromPeak:
    """Tests for drawdown_from_peak computed property."""

    def test_no_drawdown(self):
        """Drawdown should be 0 when equity equals peak."""
        state = RiskState(
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
        )

        assert state.drawdown_from_peak == Decimal("0")

    def test_calculate_drawdown(self):
        """Drawdown should be calculated correctly."""
        state = RiskState(
            current_equity=Decimal("95000"),
            peak_equity=Decimal("100000"),
        )

        # (100000 - 95000) / 100000 * 100 = 5%
        assert state.drawdown_from_peak == Decimal("5")

    def test_zero_peak_returns_zero(self):
        """Drawdown should be 0 when peak is 0 (prevent division by zero)."""
        state = RiskState(
            current_equity=Decimal("1000"),
            peak_equity=Decimal("0"),
        )

        assert state.drawdown_from_peak == Decimal("0")

    def test_negative_peak_returns_zero(self):
        """Drawdown should be 0 when peak is negative."""
        state = RiskState(
            current_equity=Decimal("1000"),
            peak_equity=Decimal("-1000"),
        )

        assert state.drawdown_from_peak == Decimal("0")


class TestUpdateEquity:
    """Tests for update_equity method."""

    def test_update_equity_below_peak(self):
        """Update equity below peak should update drawdown."""
        state = RiskState(
            peak_equity=Decimal("100000"),
        )

        state.update_equity(Decimal("95000"))

        assert state.current_equity == Decimal("95000")
        assert state.peak_equity == Decimal("100000")  # Unchanged
        assert state.total_drawdown_percent == Decimal("5")

    def test_update_equity_new_peak(self):
        """Update equity above peak should update peak."""
        state = RiskState(
            current_equity=Decimal("100000"),
            peak_equity=Decimal("100000"),
        )

        state.update_equity(Decimal("105000"))

        assert state.current_equity == Decimal("105000")
        assert state.peak_equity == Decimal("105000")  # Updated
        assert state.total_drawdown_percent == Decimal("0")

    def test_update_equity_updates_timestamp(self):
        """Update equity should update last_updated timestamp."""
        state = RiskState()
        old_timestamp = state.last_updated

        state.update_equity(Decimal("100000"))

        assert state.last_updated >= old_timestamp


class TestRecordTrade:
    """Tests for record_trade method."""

    def test_record_winning_trade(self):
        """Record a winning trade should increase daily P&L."""
        state = RiskState(
            daily_starting_balance=Decimal("100000"),
        )

        state.record_trade(Decimal("500"))

        assert state.daily_pnl == Decimal("500")
        assert state.daily_pnl_percent == Decimal("0.5")

    def test_record_losing_trade(self):
        """Record a losing trade should decrease daily P&L."""
        state = RiskState(
            daily_starting_balance=Decimal("100000"),
        )

        state.record_trade(Decimal("-2500"))

        assert state.daily_pnl == Decimal("-2500")
        assert state.daily_pnl_percent == Decimal("-2.5")

    def test_record_multiple_trades(self):
        """Record multiple trades should accumulate P&L."""
        state = RiskState(
            daily_starting_balance=Decimal("100000"),
        )

        state.record_trade(Decimal("500"))  # Win
        state.record_trade(Decimal("-200"))  # Loss
        state.record_trade(Decimal("300"))  # Win

        assert state.daily_pnl == Decimal("600")
        assert state.daily_pnl_percent == Decimal("0.6")

    def test_record_trade_zero_balance(self):
        """Record trade with zero starting balance should not divide by zero."""
        state = RiskState(
            daily_starting_balance=Decimal("0"),
        )

        state.record_trade(Decimal("500"))

        assert state.daily_pnl == Decimal("500")
        assert state.daily_pnl_percent == Decimal("0")  # No percentage calculation


class TestResetDaily:
    """Tests for reset_daily method."""

    def test_reset_daily_clears_pnl(self):
        """Reset daily should clear P&L and set new starting balance."""
        state = RiskState(
            daily_pnl=Decimal("-3000"),
            daily_pnl_percent=Decimal("-3.0"),
            daily_starting_balance=Decimal("100000"),
        )

        state.reset_daily(Decimal("97000"))

        assert state.daily_pnl == Decimal("0")
        assert state.daily_pnl_percent == Decimal("0")
        assert state.daily_starting_balance == Decimal("97000")

    def test_reset_daily_preserves_equity(self):
        """Reset daily should not affect equity or peak."""
        state = RiskState(
            current_equity=Decimal("95000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("5"),
        )

        state.reset_daily(Decimal("95000"))

        assert state.current_equity == Decimal("95000")  # Preserved
        assert state.peak_equity == Decimal("100000")  # Preserved
        assert state.total_drawdown_percent == Decimal("5")  # Preserved


class TestSerialization:
    """Tests for to_dict and from_dict methods."""

    def test_to_dict(self):
        """to_dict should serialize all fields to strings."""
        now = datetime.now(timezone.utc)
        state = RiskState(
            daily_pnl=Decimal("-1000"),
            daily_pnl_percent=Decimal("-1.0"),
            current_equity=Decimal("99000"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("1.0"),
            daily_starting_balance=Decimal("100000"),
            last_updated=now,
        )

        data = state.to_dict()

        assert data["daily_pnl"] == "-1000"
        assert data["daily_pnl_percent"] == "-1.0"
        assert data["current_equity"] == "99000"
        assert data["peak_equity"] == "100000"
        assert data["total_drawdown_percent"] == "1.0"
        assert data["daily_starting_balance"] == "100000"
        assert data["last_updated"] == now.isoformat()

    def test_from_dict(self):
        """from_dict should deserialize all fields from strings."""
        now = datetime.now(timezone.utc)
        data = {
            "daily_pnl": "-1000",
            "daily_pnl_percent": "-1.0",
            "current_equity": "99000",
            "peak_equity": "100000",
            "total_drawdown_percent": "1.0",
            "daily_starting_balance": "100000",
            "last_updated": now.isoformat(),
        }

        state = RiskState.from_dict(data)

        assert state.daily_pnl == Decimal("-1000")
        assert state.daily_pnl_percent == Decimal("-1.0")
        assert state.current_equity == Decimal("99000")
        assert state.peak_equity == Decimal("100000")

    def test_round_trip(self):
        """to_dict -> from_dict should preserve values."""
        original = RiskState(
            daily_pnl=Decimal("-2500"),
            daily_pnl_percent=Decimal("-2.5"),
            current_equity=Decimal("97500"),
            peak_equity=Decimal("100000"),
            total_drawdown_percent=Decimal("2.5"),
            daily_starting_balance=Decimal("100000"),
        )

        restored = RiskState.from_dict(original.to_dict())

        assert restored.daily_pnl == original.daily_pnl
        assert restored.daily_pnl_percent == original.daily_pnl_percent
        assert restored.current_equity == original.current_equity
        assert restored.peak_equity == original.peak_equity

    def test_from_dict_with_missing_fields(self):
        """from_dict should use defaults for missing fields."""
        data = {}

        state = RiskState.from_dict(data)

        assert state.daily_pnl == Decimal("0")
        assert state.daily_pnl_percent == Decimal("0")
        assert state.current_equity == Decimal("0")
