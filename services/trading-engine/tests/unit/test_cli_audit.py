"""Unit tests for CLI audit commands."""

from __future__ import annotations

import csv
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
# Test data factories
# ---------------------------------------------------------------------------

def _make_trade_record(
    account_id: str = "test-001",
    symbol: str = "XAUUSD",
    side: str = "BUY",
    quantity: Decimal = Decimal("0.10"),
    entry_price: Decimal = Decimal("1850.25000"),
    exit_price: Decimal | None = Decimal("1858.50000"),
    entry_time: datetime | None = None,
    exit_time: datetime | None = None,
    pnl_dollars: Decimal | None = Decimal("82.50"),
    pnl_percent: Decimal | None = Decimal("0.0825"),
    strategy_name: str = "ma_crossover",
    status: str = "closed",
) -> MagicMock:
    """Create a mock TradeRecord."""
    record = MagicMock()
    record.trade_id = uuid.uuid4()
    record.account_id = account_id
    record.symbol = symbol
    record.side = side
    record.quantity = quantity
    record.entry_price = entry_price
    record.exit_price = exit_price
    record.entry_time = entry_time or datetime(2025, 12, 3, 10, 0, 0, tzinfo=timezone.utc)
    record.exit_time = exit_time or datetime(2025, 12, 3, 11, 0, 0, tzinfo=timezone.utc)
    record.pnl_dollars = pnl_dollars
    record.pnl_percent = pnl_percent
    record.strategy_name = strategy_name
    record.status = status
    record.to_dict.return_value = {
        "trade_id": str(record.trade_id),
        "account_id": account_id,
        "symbol": symbol,
        "side": side,
        "quantity": str(quantity),
        "entry_price": str(entry_price),
        "exit_price": str(exit_price) if exit_price is not None else None,
        "entry_time": record.entry_time.isoformat(),
        "exit_time": record.exit_time.isoformat() if record.exit_time else None,
        "pnl_dollars": str(pnl_dollars) if pnl_dollars is not None else None,
        "pnl_percent": str(pnl_percent) if pnl_percent is not None else None,
        "strategy_name": strategy_name,
        "status": status,
    }
    return record


def _make_violation_record(
    account_id: str = "test-001",
    rule_type: str = "daily_loss_limit",
    rule_name: str = "Daily Loss Limit",
    severity: str = "CRITICAL",
    current_value: Decimal | None = Decimal("4.8000"),
    threshold_value: Decimal | None = Decimal("5.0000"),
    action_taken: str = "blocked",
    message: str = "Approaching daily loss limit",
    timestamp: datetime | None = None,
) -> MagicMock:
    """Create a mock RuleViolationModel."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.account_id = account_id
    record.timestamp = timestamp or datetime(2025, 12, 3, 14, 30, 0, tzinfo=timezone.utc)
    record.rule_type = rule_type
    record.rule_name = rule_name
    record.severity = severity
    record.current_value = current_value
    record.threshold_value = threshold_value
    record.action_taken = action_taken
    record.message = message
    record.order_blocked = action_taken == "blocked"
    record.to_dict.return_value = {
        "id": str(record.id),
        "account_id": account_id,
        "timestamp": record.timestamp.isoformat(),
        "rule_type": rule_type,
        "rule_name": rule_name,
        "severity": severity,
        "current_value": str(current_value) if current_value is not None else None,
        "threshold_value": str(threshold_value) if threshold_value is not None else None,
        "action_taken": action_taken,
        "message": message,
        "order_blocked": record.order_blocked,
    }
    return record


def _make_snapshot_record(
    account_id: str = "test-001",
    snapshot_date: date | None = None,
    opening_balance: Decimal = Decimal("100000.00"),
    closing_balance: Decimal = Decimal("99350.00"),
    daily_pnl: Decimal = Decimal("-650.00"),
    daily_pnl_percent: Decimal = Decimal("-0.6500"),
    drawdown_percent: Decimal = Decimal("3.0700"),
    trades_count: int = 8,
    winning_trades: int = 3,
    losing_trades: int = 5,
    high_balance: Decimal = Decimal("100200.00"),
    low_balance: Decimal = Decimal("99200.00"),
) -> MagicMock:
    """Create a mock AccountSnapshotModel."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.account_id = account_id
    record.snapshot_date = snapshot_date or date(2025, 12, 3)
    record.opening_balance = opening_balance
    record.closing_balance = closing_balance
    record.high_balance = high_balance
    record.low_balance = low_balance
    record.daily_pnl = daily_pnl
    record.daily_pnl_percent = daily_pnl_percent
    record.drawdown_percent = drawdown_percent
    record.trades_count = trades_count
    record.winning_trades = winning_trades
    record.losing_trades = losing_trades
    record.to_dict.return_value = {
        "id": str(record.id),
        "account_id": account_id,
        "snapshot_date": record.snapshot_date.isoformat(),
        "opening_balance": str(opening_balance),
        "closing_balance": str(closing_balance),
        "high_balance": str(high_balance),
        "low_balance": str(low_balance),
        "daily_pnl": str(daily_pnl),
        "daily_pnl_percent": str(daily_pnl_percent),
        "drawdown_percent": str(drawdown_percent),
        "trades_count": trades_count,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
    }
    return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db_session():
    """Create a mock async DB session that returns configurable results."""
    session = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    session.scalars.return_value = scalars_result
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Create a mock async_sessionmaker."""
    factory = MagicMock()
    # async context manager: async with factory() as session
    context = AsyncMock()
    context.__aenter__.return_value = mock_db_session
    context.__aexit__.return_value = None
    factory.return_value = context
    return factory


@pytest.fixture
def patch_db_factory(mock_session_factory):
    """Patch _get_db_session_factory to return mock session factory."""
    with patch(
        "src.cli.audit._get_db_session_factory",
        return_value=mock_session_factory,
    ):
        yield mock_session_factory


# ---------------------------------------------------------------------------
# Test 7.1: audit trades command - formatted table
# ---------------------------------------------------------------------------

class TestAuditTradesCommand:
    """Tests for audit trades command (AC #1)."""

    def test_trades_returns_formatted_table(self, patch_db_factory, mock_db_session):
        """Test audit trades returns formatted table with trade data."""
        trades = [
            _make_trade_record(
                symbol="XAUUSD", side="BUY", pnl_dollars=Decimal("82.50"),
                entry_price=Decimal("1850.25000"), exit_price=Decimal("1858.50000"),
            ),
            _make_trade_record(
                symbol="XAUUSD", side="SELL", pnl_dollars=Decimal("-60.00"),
                entry_price=Decimal("1858.00000"), exit_price=Decimal("1852.00000"),
            ),
        ]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "--account", "test-001", "--days", "7"])

        assert result.exit_code == 0
        assert "Trades for test-001" in result.output
        assert "XAUUSD" in result.output
        assert "BUY" in result.output
        assert "SELL" in result.output
        assert "Total:" in result.output or "trades" in result.output.lower()

    def test_trades_open_trade_shows_open(self, patch_db_factory, mock_db_session):
        """Test open trades show OPEN in exit column."""
        trades = [
            _make_trade_record(
                exit_price=None, exit_time=None, pnl_dollars=None,
                pnl_percent=None, status="open",
            ),
        ]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001"])

        assert result.exit_code == 0
        assert "OPEN" in result.output

    def test_trades_requires_account(self):
        """Test trades command requires --account option."""
        result = runner.invoke(app, ["audit", "trades"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Test 7.2: audit trades --json
# ---------------------------------------------------------------------------

class TestAuditTradesJson:
    """Tests for audit trades JSON output (AC #4)."""

    def test_trades_json_output(self, patch_db_factory, mock_db_session):
        """Test --json returns valid JSON with all trade fields."""
        trades = [_make_trade_record()]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert "trade_id" in data[0]
        assert "pnl_dollars" in data[0]
        # Financial values must be strings for precision
        assert isinstance(data[0]["pnl_dollars"], str)


# ---------------------------------------------------------------------------
# Test 7.3: audit violations command - formatted table
# ---------------------------------------------------------------------------

class TestAuditViolationsCommand:
    """Tests for audit violations command (AC #2)."""

    def test_violations_returns_formatted_table(self, patch_db_factory, mock_db_session):
        """Test audit violations returns formatted table."""
        violations = [
            _make_violation_record(
                rule_type="daily_loss_limit",
                current_value=Decimal("4.8000"),
                threshold_value=Decimal("5.0000"),
                action_taken="blocked",
            ),
        ]
        scalars = MagicMock()
        scalars.all.return_value = violations
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "violations", "-a", "test-001"])

        assert result.exit_code == 0
        assert "Violations for test-001" in result.output or "Rule Violations" in result.output
        assert "daily_loss_limit" in result.output
        assert "blocked" in result.output.lower()


# ---------------------------------------------------------------------------
# Test 7.4: audit daily command - formatted table
# ---------------------------------------------------------------------------

class TestAuditDailyCommand:
    """Tests for audit daily command (AC #3)."""

    def test_daily_returns_formatted_table(self, patch_db_factory, mock_db_session):
        """Test audit daily returns formatted snapshot table."""
        snapshots = [
            _make_snapshot_record(
                snapshot_date=date(2025, 12, 3),
                opening_balance=Decimal("100000.00"),
                closing_balance=Decimal("99350.00"),
                daily_pnl=Decimal("-650.00"),
            ),
        ]
        scalars = MagicMock()
        scalars.all.return_value = snapshots
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "daily", "-a", "test-001"])

        assert result.exit_code == 0
        assert "Snapshots for test-001" in result.output or "Daily" in result.output
        assert "2025-12-03" in result.output


# ---------------------------------------------------------------------------
# Test 7.5: --export csv writes file
# ---------------------------------------------------------------------------

class TestAuditExportCsv:
    """Tests for CSV export (AC #5)."""

    def test_export_csv_trades_writes_file(self, patch_db_factory, mock_db_session, tmp_path, monkeypatch):
        """Test trades --export csv writes CSV file with correct headers and data."""
        trades = [_make_trade_record()]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        # Change CWD to tmp_path so CSV is written there
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001", "--export", "csv"])

        assert result.exit_code == 0
        assert "Exported" in result.output

        # Find the CSV file
        csv_files = list(tmp_path.glob("trades-*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0]) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert "Symbol" in header or "symbol" in header
            rows = list(reader)
            assert len(rows) == 1

    def test_export_csv_violations_writes_file(self, patch_db_factory, mock_db_session, tmp_path, monkeypatch):
        """Test violations --export csv writes CSV file with correct headers."""
        violations = [_make_violation_record()]
        scalars = MagicMock()
        scalars.all.return_value = violations
        mock_db_session.scalars.return_value = scalars

        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit", "violations", "-a", "test-001", "--export", "csv"])

        assert result.exit_code == 0
        assert "Exported" in result.output

        csv_files = list(tmp_path.glob("violations-*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0]) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert "Rule" in header
            rows = list(reader)
            assert len(rows) == 1

    def test_export_csv_daily_writes_file(self, patch_db_factory, mock_db_session, tmp_path, monkeypatch):
        """Test daily --export csv writes CSV file with correct headers."""
        snapshots = [_make_snapshot_record()]
        scalars = MagicMock()
        scalars.all.return_value = snapshots
        mock_db_session.scalars.return_value = scalars

        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["audit", "daily", "-a", "test-001", "--export", "csv"])

        assert result.exit_code == 0
        assert "Exported" in result.output

        csv_files = list(tmp_path.glob("daily-*.csv"))
        assert len(csv_files) == 1

        with open(csv_files[0]) as f:
            reader = csv.reader(f)
            header = next(reader)
            assert "Date" in header
            assert "P&L" in header
            rows = list(reader)
            assert len(rows) == 1


# ---------------------------------------------------------------------------
# Test 7.6: Missing DATABASE_URL error
# ---------------------------------------------------------------------------

class TestAuditDatabaseError:
    """Tests for database connection error handling (AC #6)."""

    def test_missing_database_url_shows_error(self, monkeypatch):
        """Test missing DATABASE_URL shows clear error and exits with code 1."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001"])

        assert result.exit_code == 1
        assert "Database connection required" in result.output
        assert "DATABASE_URL" in result.output


# ---------------------------------------------------------------------------
# Test 7.7: Empty results
# ---------------------------------------------------------------------------

class TestAuditEmptyResults:
    """Tests for empty result handling."""

    def test_empty_trades(self, patch_db_factory, mock_db_session):
        """Test empty trades show 'No trades found' message."""
        scalars = MagicMock()
        scalars.all.return_value = []
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001"])

        assert result.exit_code == 0
        assert "No trades found" in result.output

    def test_empty_violations(self, patch_db_factory, mock_db_session):
        """Test empty violations show 'No violations found' message."""
        scalars = MagicMock()
        scalars.all.return_value = []
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "violations", "-a", "test-001"])

        assert result.exit_code == 0
        assert "No violations found" in result.output

    def test_empty_snapshots(self, patch_db_factory, mock_db_session):
        """Test empty snapshots show 'No snapshots found' message."""
        scalars = MagicMock()
        scalars.all.return_value = []
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "daily", "-a", "test-001"])

        assert result.exit_code == 0
        assert "No snapshots found" in result.output


# ---------------------------------------------------------------------------
# Test 7.8: DECIMAL precision in JSON
# ---------------------------------------------------------------------------

class TestAuditDecimalPrecision:
    """Tests for DECIMAL precision in JSON output."""

    def test_json_decimal_as_strings(self, patch_db_factory, mock_db_session):
        """Test DECIMAL values are serialized as strings in JSON output."""
        trades = [_make_trade_record(
            pnl_dollars=Decimal("82.50"),
            pnl_percent=Decimal("0.0825"),
            entry_price=Decimal("1850.25000"),
        )]
        scalars = MagicMock()
        scalars.all.return_value = trades
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "trades", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data[0]["pnl_dollars"], str)
        assert isinstance(data[0]["entry_price"], str)

    def test_violations_json_decimal_as_strings(self, patch_db_factory, mock_db_session):
        """Test violation DECIMAL values are strings in JSON."""
        violations = [_make_violation_record(
            current_value=Decimal("4.8000"),
            threshold_value=Decimal("5.0000"),
        )]
        scalars = MagicMock()
        scalars.all.return_value = violations
        mock_db_session.scalars.return_value = scalars

        result = runner.invoke(app, ["audit", "violations", "-a", "test-001", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data[0]["current_value"], str)
        assert isinstance(data[0]["threshold_value"], str)


# ---------------------------------------------------------------------------
# Test 7.9: _compute_trade_summary
# ---------------------------------------------------------------------------

class TestComputeTradeSummary:
    """Tests for _compute_trade_summary helper."""

    def test_compute_summary_correct_totals(self):
        """Test summary calculates correct totals and win rate."""
        from src.cli.audit import _compute_trade_summary

        trades = [
            _make_trade_record(pnl_dollars=Decimal("100.00")),
            _make_trade_record(pnl_dollars=Decimal("-50.00")),
            _make_trade_record(pnl_dollars=Decimal("75.00")),
        ]

        summary = _compute_trade_summary(trades)

        assert summary["total_trades"] == 3
        assert summary["net_pnl"] == Decimal("125.00")
        assert summary["winning"] == 2
        assert summary["losing"] == 1
        assert summary["win_rate"] == pytest.approx(66.67, abs=0.01)

    def test_compute_summary_empty_list(self):
        """Test summary handles empty list."""
        from src.cli.audit import _compute_trade_summary

        summary = _compute_trade_summary([])

        assert summary["total_trades"] == 0
        assert summary["net_pnl"] == Decimal("0")
        assert summary["win_rate"] == 0.0

    def test_compute_summary_open_trades_excluded_from_pnl(self):
        """Test open trades (None pnl) are counted but excluded from P&L."""
        from src.cli.audit import _compute_trade_summary

        trades = [
            _make_trade_record(pnl_dollars=Decimal("100.00")),
            _make_trade_record(pnl_dollars=None, status="open"),
        ]

        summary = _compute_trade_summary(trades)

        assert summary["total_trades"] == 2
        assert summary["net_pnl"] == Decimal("100.00")
        assert summary["winning"] == 1
        assert summary["losing"] == 0
