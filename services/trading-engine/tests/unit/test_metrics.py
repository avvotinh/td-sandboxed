"""Unit tests for AccountMetrics dataclass."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from src.accounts.metrics import AccountMetrics


class TestAccountMetrics:
    """Unit tests for AccountMetrics dataclass."""

    def test_unrealized_pnl_calculation(self):
        """Unrealized P&L = Equity - Balance."""
        metrics = AccountMetrics(
            account_id="test-001",
            account_name="Test Account",
            status="active",
            balance=Decimal("100000"),
            equity=Decimal("98500"),
        )

        assert metrics.unrealized_pnl == Decimal("-1500")

    def test_unrealized_pnl_positive(self):
        """Unrealized P&L when profitable."""
        metrics = AccountMetrics(
            account_id="test-001",
            account_name="Test Account",
            status="active",
            balance=Decimal("100000"),
            equity=Decimal("101500"),
        )

        assert metrics.unrealized_pnl == Decimal("1500")

    def test_format_currency_positive(self):
        """Format positive currency correctly."""
        assert AccountMetrics.format_currency(Decimal("100000")) == "$100,000.00"
        assert AccountMetrics.format_currency(Decimal("1234.56")) == "$1,234.56"

    def test_format_currency_negative(self):
        """Format negative currency correctly."""
        assert AccountMetrics.format_currency(Decimal("-1500")) == "-$1,500.00"

    def test_format_currency_zero(self):
        """Format zero currency correctly."""
        assert AccountMetrics.format_currency(Decimal("0")) == "$0.00"

    def test_format_percent_with_sign(self):
        """Format percentage with sign."""
        assert AccountMetrics.format_percent(Decimal("0.8")) == "+0.8%"
        assert AccountMetrics.format_percent(Decimal("-1.5")) == "-1.5%"

    def test_format_percent_without_sign(self):
        """Format percentage without sign."""
        assert AccountMetrics.format_percent(Decimal("1.5"), show_sign=False) == "1.5%"

    def test_format_percent_zero(self):
        """Format zero percentage."""
        assert AccountMetrics.format_percent(Decimal("0")) == "+0.0%"
        assert AccountMetrics.format_percent(Decimal("0"), show_sign=False) == "0.0%"

    def test_to_status_dict(self):
        """Status dict contains all required fields."""
        metrics = AccountMetrics(
            account_id="ftmo-gold-001",
            account_name="FTMO Gold Challenge",
            status="active",
            balance=Decimal("100000"),
            equity=Decimal("98500"),
            daily_pnl=Decimal("-1500"),
            daily_pnl_percent=Decimal("-1.5"),
            peak_equity=Decimal("100000"),
            max_drawdown_percent=Decimal("1.5"),
        )

        status_dict = metrics.to_status_dict()

        assert status_dict["account_id"] == "ftmo-gold-001"
        assert status_dict["account_name"] == "FTMO Gold Challenge"
        assert status_dict["status"] == "active"
        assert status_dict["balance"] == "$100,000.00"
        assert status_dict["equity"] == "$98,500.00"
        assert "-$1,500.00" in status_dict["daily_pnl"]
        assert "-1.5%" in status_dict["daily_pnl"]
        assert status_dict["max_drawdown"] == "1.5%"
        assert status_dict["peak_equity"] == "$100,000.00"

    def test_to_list_row(self):
        """List row contains columns in correct order."""
        metrics = AccountMetrics(
            account_id="ftmo-gold-001",
            account_name="FTMO Gold Challenge",
            status="active",
            balance=Decimal("100000"),
            daily_pnl_percent=Decimal("-1.5"),
        )

        row = metrics.to_list_row()

        assert row[0] == "ftmo-gold-001"
        assert row[1] == "FTMO Gold Challenge"
        assert row[2] == "active"
        assert row[3] == "$100,000.00"
        assert row[4] == "-1.5%"


class TestAccountMetricsEdgeCases:
    """Edge case tests for AccountMetrics."""

    def test_zero_balance(self):
        """Handle zero balance correctly."""
        metrics = AccountMetrics(
            account_id="new-account",
            account_name="New Account",
            status="active",
            balance=Decimal("0"),
            equity=Decimal("0"),
        )

        assert metrics.unrealized_pnl == Decimal("0")
        assert metrics.format_currency(metrics.balance) == "$0.00"

    def test_large_numbers(self):
        """Handle large account balances."""
        metrics = AccountMetrics(
            account_id="whale",
            account_name="Whale Account",
            status="active",
            balance=Decimal("10000000"),  # 10 million
            equity=Decimal("9999000"),
        )

        assert "$10,000,000.00" in metrics.format_currency(metrics.balance)

    def test_default_values(self):
        """Test default values are applied correctly."""
        metrics = AccountMetrics(
            account_id="test-001",
            account_name="Test Account",
            status="active",
        )

        assert metrics.balance == Decimal("0")
        assert metrics.equity == Decimal("0")
        assert metrics.daily_pnl == Decimal("0")
        assert metrics.daily_pnl_percent == Decimal("0")
        assert metrics.peak_equity == Decimal("0")
        assert metrics.max_drawdown_percent == Decimal("0")
        assert isinstance(metrics.last_updated, datetime)

    def test_last_updated_timezone_aware(self):
        """Last updated is timezone-aware."""
        metrics = AccountMetrics(
            account_id="test-001",
            account_name="Test Account",
            status="active",
        )

        assert metrics.last_updated.tzinfo is not None
