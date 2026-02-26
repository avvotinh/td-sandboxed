"""Integration tests for CLI audit commands - full CLI invocation via CliRunner."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

def _mock_trade(
    account_id: str = "test-001",
    symbol: str = "EURUSD",
    side: str = "BUY",
    pnl_dollars: Decimal = Decimal("50.00"),
    status: str = "closed",
) -> MagicMock:
    record = MagicMock()
    record.trade_id = uuid.uuid4()
    record.account_id = account_id
    record.symbol = symbol
    record.side = side
    record.quantity = Decimal("0.10")
    record.entry_price = Decimal("1.10500")
    record.exit_price = Decimal("1.11000") if status == "closed" else None
    record.entry_time = datetime(2025, 12, 1, 10, 0, 0, tzinfo=timezone.utc)
    record.exit_time = datetime(2025, 12, 1, 11, 0, 0, tzinfo=timezone.utc) if status == "closed" else None
    record.pnl_dollars = pnl_dollars if status == "closed" else None
    record.pnl_percent = Decimal("0.0500") if status == "closed" else None
    record.strategy_name = "ma_crossover"
    record.status = status
    record.to_dict.return_value = {
        "trade_id": str(record.trade_id),
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "quantity": str(record.quantity),
        "entry_price": str(record.entry_price),
        "exit_price": str(record.exit_price) if record.exit_price else None,
        "entry_time": record.entry_time.isoformat(),
        "exit_time": record.exit_time.isoformat() if record.exit_time else None,
        "pnl_dollars": str(pnl_dollars) if pnl_dollars else None,
        "pnl_percent": str(record.pnl_percent) if record.pnl_percent else None,
        "strategy_name": "ma_crossover",
        "status": status,
    }
    return record


def _mock_violation(
    account_id: str = "test-001",
    rule_type: str = "daily_loss_limit",
) -> MagicMock:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.account_id = account_id
    record.timestamp = datetime(2025, 12, 1, 14, 0, 0, tzinfo=timezone.utc)
    record.rule_type = rule_type
    record.rule_name = "Daily Loss Limit"
    record.severity = "CRITICAL"
    record.current_value = Decimal("4.8000")
    record.threshold_value = Decimal("5.0000")
    record.action_taken = "blocked"
    record.message = "Approaching daily loss limit"
    record.order_blocked = True
    record.to_dict.return_value = {
        "id": str(record.id),
        "account_id": account_id,
        "timestamp": record.timestamp.isoformat(),
        "rule_type": rule_type,
        "rule_name": "Daily Loss Limit",
        "severity": "CRITICAL",
        "current_value": "4.8000",
        "threshold_value": "5.0000",
        "action_taken": "blocked",
        "message": "Approaching daily loss limit",
    }
    return record


def _mock_snapshot(
    account_id: str = "test-001",
    snap_date: date | None = None,
) -> MagicMock:
    record = MagicMock()
    record.id = uuid.uuid4()
    record.account_id = account_id
    record.snapshot_date = snap_date or date(2025, 12, 1)
    record.opening_balance = Decimal("100000.00")
    record.closing_balance = Decimal("100450.00")
    record.high_balance = Decimal("100600.00")
    record.low_balance = Decimal("99800.00")
    record.daily_pnl = Decimal("450.00")
    record.daily_pnl_percent = Decimal("0.4500")
    record.drawdown_percent = Decimal("0.2000")
    record.trades_count = 5
    record.winning_trades = 3
    record.losing_trades = 2
    record.to_dict.return_value = {
        "id": str(record.id),
        "account_id": account_id,
        "snapshot_date": record.snapshot_date.isoformat(),
        "opening_balance": "100000.00",
        "closing_balance": "100450.00",
        "daily_pnl": "450.00",
        "daily_pnl_percent": "0.4500",
        "drawdown_percent": "0.2000",
        "trades_count": 5,
        "winning_trades": 3,
        "losing_trades": 2,
    }
    return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    session.scalars.return_value = scalars_result
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    factory = MagicMock()
    context = AsyncMock()
    context.__aenter__.return_value = mock_db_session
    context.__aexit__.return_value = None
    factory.return_value = context
    return factory


@pytest.fixture
def patch_db(mock_session_factory):
    with patch(
        "src.cli.audit._get_db_session_factory",
        return_value=mock_session_factory,
    ):
        yield mock_session_factory


# ---------------------------------------------------------------------------
# Integration tests: Full CLI invocation
# ---------------------------------------------------------------------------


class TestAuditTradesIntegration:
    """Integration test 7.11: Full CLI invocation for audit trades."""

    def test_full_trades_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit trades --account test-001 --days 7."""
        trades = [_mock_trade(), _mock_trade(side="SELL", pnl_dollars=Decimal("-30.00"))]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "--account", "test-001", "--days", "7"])

        assert result.exit_code == 0
        assert "Trades for test-001" in result.output
        assert "EURUSD" in result.output
        assert "Total:" in result.output

    def test_trades_json_full_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit trades --account test-001 --json."""
        trades = [_mock_trade()]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_trades_with_symbol_filter(self, patch_db, mock_db_session):
        """Full invocation with --symbol filter."""
        trades = [_mock_trade(symbol="XAUUSD")]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(
            app, ["audit", "trades", "-a", "test-001", "-s", "XAUUSD"]
        )

        assert result.exit_code == 0
        assert "XAUUSD" in result.output


class TestAuditViolationsIntegration:
    """Integration test 7.12: Full CLI invocation for audit violations."""

    def test_full_violations_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit violations --account test-001."""
        violations = [_mock_violation()]
        scalars = MagicMock()
        scalars.all.return_value = violations
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "violations", "--account", "test-001"])

        assert result.exit_code == 0
        assert "Violations" in result.output or "violations" in result.output
        assert "daily_loss_limit" in result.output

    def test_violations_json_full_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit violations --account test-001 --json."""
        violations = [_mock_violation()]
        scalars = MagicMock()
        scalars.all.return_value = violations
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "violations", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["severity"] == "CRITICAL"


class TestAuditDailyIntegration:
    """Integration test 7.13: Full CLI invocation for audit daily."""

    def test_full_daily_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit daily --account test-001."""
        snapshots = [_mock_snapshot()]
        scalars = MagicMock()
        scalars.all.return_value = snapshots
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "daily", "--account", "test-001"])

        assert result.exit_code == 0
        assert "Daily" in result.output or "Snapshots" in result.output
        assert "2025-12-01" in result.output

    def test_daily_json_full_invocation(self, patch_db, mock_db_session):
        """Full CLI invocation: audit daily --account test-001 --json."""
        snapshots = [_mock_snapshot()]
        scalars = MagicMock()
        scalars.all.return_value = snapshots
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "daily", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["snapshot_date"] == "2025-12-01"

    def test_daily_with_days_option(self, patch_db, mock_db_session):
        """Full invocation with --days option."""
        snapshots = [_mock_snapshot()]
        scalars = MagicMock()
        scalars.all.return_value = snapshots
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "daily", "-a", "test-001", "-d", "14"])

        assert result.exit_code == 0
        assert "last 14 days" in result.output


class TestAuditHelpIntegration:
    """Integration test: audit subcommand help."""

    def test_audit_help(self):
        """Test audit --help shows subcommands."""
        result = runner.invoke(app, ["audit", "--help"])
        assert result.exit_code == 0
        assert "trades" in result.output
        assert "violations" in result.output
        assert "daily" in result.output

    def test_audit_visible_in_main_help(self):
        """Test audit appears in main CLI help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "audit" in result.output
