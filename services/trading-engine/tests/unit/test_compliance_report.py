"""Unit tests for compliance report generation (Story 7.6)."""

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
from src.reports.compliance_report import ComplianceReportGenerator
from src.reports.data_gatherer import _compute_summary
from src.reports.models import ReportData

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
    order_blocked: bool = True,
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
    record.order_blocked = order_blocked
    record.message = message
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
        "order_blocked": order_blocked,
    }
    return record


def _make_snapshot_record(
    account_id: str = "test-001",
    snapshot_date: date | None = None,
    opening_balance: Decimal = Decimal("100000.00"),
    closing_balance: Decimal = Decimal("100500.00"),
    daily_pnl: Decimal = Decimal("500.00"),
    daily_pnl_percent: Decimal = Decimal("0.5000"),
    drawdown_percent: Decimal = Decimal("1.5000"),
    peak_balance: Decimal = Decimal("101000.00"),
    trades_count: int = 5,
    winning_trades: int = 3,
    losing_trades: int = 2,
) -> MagicMock:
    """Create a mock AccountSnapshotModel."""
    record = MagicMock()
    record.id = uuid.uuid4()
    record.account_id = account_id
    record.snapshot_date = snapshot_date or date(2025, 12, 3)
    record.opening_balance = opening_balance
    record.closing_balance = closing_balance
    record.daily_pnl = daily_pnl
    record.daily_pnl_percent = daily_pnl_percent
    record.drawdown_percent = drawdown_percent
    record.peak_balance = peak_balance
    record.trades_count = trades_count
    record.winning_trades = winning_trades
    record.losing_trades = losing_trades
    record.high_balance = Decimal("100800.00")
    record.low_balance = Decimal("99500.00")
    record.to_dict.return_value = {
        "id": str(record.id),
        "account_id": account_id,
        "snapshot_date": record.snapshot_date.isoformat(),
        "opening_balance": str(opening_balance),
        "closing_balance": str(closing_balance),
        "daily_pnl": str(daily_pnl),
        "daily_pnl_percent": str(daily_pnl_percent),
        "drawdown_percent": str(drawdown_percent),
        "peak_balance": str(peak_balance),
        "trades_count": trades_count,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
    }
    return record


def _make_report_data(
    trades: list | None = None,
    violations: list | None = None,
    snapshots: list | None = None,
) -> ReportData:
    """Create a ReportData instance with default test data."""
    t = trades if trades is not None else [
        _make_trade_record(pnl_dollars=Decimal("100.00")),
        _make_trade_record(pnl_dollars=Decimal("-50.00"), side="SELL"),
        _make_trade_record(pnl_dollars=Decimal("75.00")),
    ]
    v = violations if violations is not None else [
        _make_violation_record(),
    ]
    s = snapshots if snapshots is not None else [
        _make_snapshot_record(snapshot_date=date(2025, 12, 1)),
        _make_snapshot_record(
            snapshot_date=date(2025, 12, 2),
            closing_balance=Decimal("100200.00"),
            daily_pnl=Decimal("200.00"),
        ),
        _make_snapshot_record(
            snapshot_date=date(2025, 12, 3),
            closing_balance=Decimal("100500.00"),
            daily_pnl=Decimal("300.00"),
        ),
    ]

    summary = _compute_summary(
        t, v, s,
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 3),
    )

    return ReportData(
        account_id="test-001",
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 3),
        generated_at=datetime(2025, 12, 3, 18, 0, 0, tzinfo=timezone.utc),
        trades=t,
        violations=v,
        snapshots=s,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session():
    """Create a mock async DB session."""
    session = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    session.scalars.return_value = scalars_result
    return session


@pytest.fixture
def mock_session_factory(mock_db_session):
    """Create a mock async_sessionmaker."""
    factory = MagicMock()
    context = AsyncMock()
    context.__aenter__.return_value = mock_db_session
    context.__aexit__.return_value = None
    factory.return_value = context
    return factory


@pytest.fixture
def patch_report_db_factory(mock_session_factory):
    """Patch _get_db_session_factory in report module."""
    with patch(
        "src.cli.report._get_db_session_factory",
        return_value=mock_session_factory,
    ):
        yield mock_session_factory


# ---------------------------------------------------------------------------
# Test 8.1: ReportDataGatherer.gather() with mocked DB
# ---------------------------------------------------------------------------


class TestReportDataGatherer:
    """Tests for ReportDataGatherer.gather()."""

    def test_gather_returns_report_data(self, mock_db_session):
        """Test gather() returns correct ReportData with mocked DB session."""
        import asyncio

        from src.reports.data_gatherer import ReportDataGatherer

        trades = [_make_trade_record()]
        violations = [_make_violation_record()]
        snapshots = [_make_snapshot_record()]

        # Mock scalars to return different results for each call
        call_count = 0

        async def mock_scalars(stmt):
            nonlocal call_count
            result = MagicMock()
            if call_count == 0:
                result.all.return_value = trades
            elif call_count == 1:
                result.all.return_value = violations
            else:
                result.all.return_value = snapshots
            call_count += 1
            return result

        mock_db_session.scalars = AsyncMock(side_effect=mock_scalars)

        gatherer = ReportDataGatherer()
        report = asyncio.run(
            gatherer.gather(mock_db_session, "test-001", date(2025, 12, 1), date(2025, 12, 3))
        )

        assert report.account_id == "test-001"
        assert report.period_start == date(2025, 12, 1)
        assert report.period_end == date(2025, 12, 3)
        assert len(report.trades) == 1
        assert len(report.violations) == 1
        assert len(report.snapshots) == 1
        assert report.summary.total_trades == 1


# ---------------------------------------------------------------------------
# Test 8.2-8.4: _compute_summary
# ---------------------------------------------------------------------------


class TestComputeSummary:
    """Tests for _compute_summary helper."""

    def test_trade_stats_correct(self):
        """Test trade stats: win rate, net P&L, best/worst day."""
        trades = [
            _make_trade_record(pnl_dollars=Decimal("100.00")),
            _make_trade_record(pnl_dollars=Decimal("-50.00")),
            _make_trade_record(pnl_dollars=Decimal("75.00")),
        ]

        summary = _compute_summary(
            trades, [], [], date(2025, 12, 1), date(2025, 12, 3)
        )

        assert summary.total_trades == 3
        assert summary.winning_trades == 2
        assert summary.losing_trades == 1
        assert summary.net_pnl == Decimal("125.00")
        assert float(summary.win_rate) == pytest.approx(66.67, abs=0.01)

    def test_snapshot_stats_correct(self):
        """Test snapshot stats: trading days, max drawdown, balance progression."""
        snapshots = [
            _make_snapshot_record(
                snapshot_date=date(2025, 12, 1),
                opening_balance=Decimal("100000.00"),
                closing_balance=Decimal("100500.00"),
                daily_pnl=Decimal("500.00"),
                drawdown_percent=Decimal("1.5000"),
                peak_balance=Decimal("100500.00"),
                trades_count=5,
            ),
            _make_snapshot_record(
                snapshot_date=date(2025, 12, 2),
                opening_balance=Decimal("100500.00"),
                closing_balance=Decimal("99800.00"),
                daily_pnl=Decimal("-700.00"),
                drawdown_percent=Decimal("3.0000"),
                peak_balance=Decimal("100500.00"),
                trades_count=3,
            ),
            _make_snapshot_record(
                snapshot_date=date(2025, 12, 3),
                opening_balance=Decimal("99800.00"),
                closing_balance=Decimal("100200.00"),
                daily_pnl=Decimal("400.00"),
                drawdown_percent=Decimal("2.0000"),
                peak_balance=Decimal("100500.00"),
                trades_count=0,
            ),
        ]

        summary = _compute_summary(
            [], [], snapshots, date(2025, 12, 1), date(2025, 12, 3)
        )

        assert summary.trading_days == 2  # day 3 has 0 trades
        assert summary.opening_balance == Decimal("100000.00")
        assert summary.closing_balance == Decimal("100200.00")
        assert summary.max_drawdown_percent == Decimal("3.0000")
        assert summary.best_day_pnl == Decimal("500.00")
        assert summary.worst_day_pnl == Decimal("-700.00")
        assert summary.calendar_days == 3

    def test_violation_stats_correct(self):
        """Test violation stats: total, by rule type, blocked count."""
        violations = [
            _make_violation_record(
                rule_type="daily_loss_limit", order_blocked=True
            ),
            _make_violation_record(
                rule_type="daily_loss_limit", order_blocked=False
            ),
            _make_violation_record(
                rule_type="max_drawdown", order_blocked=True
            ),
        ]

        summary = _compute_summary(
            [], violations, [], date(2025, 12, 1), date(2025, 12, 3)
        )

        assert summary.total_violations == 3
        assert summary.blocked_count == 2
        assert summary.violations_by_rule == {
            "daily_loss_limit": 2,
            "max_drawdown": 1,
        }

    def test_empty_data(self):
        """Test summary handles empty data."""
        summary = _compute_summary([], [], [], date(2025, 12, 1), date(2025, 12, 3))

        assert summary.total_trades == 0
        assert summary.win_rate == Decimal("0")
        assert summary.net_pnl == Decimal("0")
        assert summary.trading_days == 0
        assert summary.total_violations == 0


# ---------------------------------------------------------------------------
# Test 8.5: PDF generation
# ---------------------------------------------------------------------------


class TestPdfGeneration:
    """Tests for PDF report generation."""

    def test_generate_pdf_creates_file(self, tmp_path):
        """Test generate_pdf creates a valid PDF file."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()
        output_path = tmp_path / "test-report.pdf"

        gen.generate_pdf(report_data, output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0
        # Check PDF magic bytes
        with open(output_path, "rb") as f:
            header = f.read(4)
            assert header == b"%PDF"

    def test_generate_pdf_empty_data(self, tmp_path):
        """Test PDF generation with empty data produces valid file."""
        report_data = _make_report_data(trades=[], violations=[], snapshots=[])
        gen = ComplianceReportGenerator()
        output_path = tmp_path / "empty-report.pdf"

        gen.generate_pdf(report_data, output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Test 8.6: JSON generation
# ---------------------------------------------------------------------------


class TestJsonGeneration:
    """Tests for JSON report generation."""

    def test_generate_json_returns_valid_json(self):
        """Test generate_json returns valid JSON with all sections."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()

        json_str = gen.generate_json(report_data)

        data = json.loads(json_str)
        assert "report" in data
        assert "summary" in data
        assert "trades" in data
        assert "violations" in data
        assert "snapshots" in data
        assert data["report"]["account_id"] == "test-001"

    def test_generate_json_financial_values_as_strings(self):
        """Test financial values are strings, not floats."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()

        json_str = gen.generate_json(report_data)

        data = json.loads(json_str)
        summary = data["summary"]
        assert isinstance(summary["net_pnl"], str)
        assert isinstance(summary["win_rate"], str)
        assert isinstance(summary["opening_balance"], str)
        assert isinstance(summary["max_drawdown_percent"], str)

    def test_generate_json_writes_file(self, tmp_path):
        """Test generate_json writes to file when path provided."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()
        output_path = tmp_path / "test-report.json"

        gen.generate_json(report_data, output_path)

        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["report"]["account_id"] == "test-001"


# ---------------------------------------------------------------------------
# Test 8.7: CSV generation
# ---------------------------------------------------------------------------


class TestCsvGeneration:
    """Tests for CSV report generation."""

    def test_generate_csv_writes_files(self, tmp_path):
        """Test generate_csv writes CSV files with correct headers and data."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()

        filenames = gen.generate_csv(report_data, tmp_path)

        assert len(filenames) == 4  # trades, violations, snapshots, summary

        # Check trades CSV
        trades_files = list(tmp_path.glob("report-test-001-trades-*.csv"))
        assert len(trades_files) == 1
        with open(trades_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3
            assert "symbol" in reader.fieldnames
            assert "pnl_dollars" in reader.fieldnames

        # Check violations CSV
        viol_files = list(tmp_path.glob("report-test-001-violations-*.csv"))
        assert len(viol_files) == 1
        with open(viol_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert "rule_type" in reader.fieldnames

        # Check snapshots CSV
        snap_files = list(tmp_path.glob("report-test-001-snapshots-*.csv"))
        assert len(snap_files) == 1
        with open(snap_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 3

        # Check summary CSV
        summary_files = list(tmp_path.glob("report-test-001-summary-*.csv"))
        assert len(summary_files) == 1


# ---------------------------------------------------------------------------
# Test 8.8: Dashboard comparison
# ---------------------------------------------------------------------------


class TestDashboardComparison:
    """Tests for dashboard comparison output."""

    def test_generate_comparison_returns_table(self):
        """Test generate_comparison returns formatted table with all metrics."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()

        output = gen.generate_comparison(report_data)

        assert "FTMO Dashboard Comparison for test-001" in output
        assert "System Value" in output
        assert "FTMO Dashboard" in output
        assert "Daily Loss" in output
        assert "Max Drawdown" in output
        assert "Trading Days" in output
        assert "Profit Target" in output
        assert "Total Trades" in output
        assert "Win Rate" in output
        assert "[___]" in output


# ---------------------------------------------------------------------------
# Test 8.9: Missing DATABASE_URL
# ---------------------------------------------------------------------------


class TestMissingDatabaseUrl:
    """Tests for missing DATABASE_URL error."""

    def test_missing_database_url_shows_error(self, monkeypatch):
        """Test missing DATABASE_URL shows error and exits with code 1."""
        monkeypatch.delenv("DATABASE_URL", raising=False)

        result = runner.invoke(app, ["report", "--account", "test-001"])

        assert result.exit_code == 1
        assert "Database connection required" in result.output
        assert "DATABASE_URL" in result.output


# ---------------------------------------------------------------------------
# Test 8.10: Empty data produces valid reports
# ---------------------------------------------------------------------------


class TestEmptyDataReports:
    """Tests for empty data handling."""

    def test_empty_data_pdf(self, tmp_path):
        """Test empty data produces valid PDF with 'No data' messages."""
        report_data = _make_report_data(trades=[], violations=[], snapshots=[])
        gen = ComplianceReportGenerator()
        output_path = tmp_path / "empty.pdf"

        gen.generate_pdf(report_data, output_path)

        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_empty_data_json(self):
        """Test empty data produces valid JSON."""
        report_data = _make_report_data(trades=[], violations=[], snapshots=[])
        gen = ComplianceReportGenerator()

        json_str = gen.generate_json(report_data)

        data = json.loads(json_str)
        assert data["trades"] == []
        assert data["violations"] == []
        assert data["snapshots"] == []
        assert data["summary"]["total_trades"] == 0

    def test_empty_data_csv(self, tmp_path):
        """Test empty data produces CSV files with headers only."""
        report_data = _make_report_data(trades=[], violations=[], snapshots=[])
        gen = ComplianceReportGenerator()

        filenames = gen.generate_csv(report_data, tmp_path)

        assert len(filenames) == 4
        # Trades CSV should have header but no data rows
        trades_files = list(tmp_path.glob("report-test-001-trades-*.csv"))
        with open(trades_files[0]) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 0

    def test_empty_data_comparison(self):
        """Test empty data produces valid comparison table."""
        report_data = _make_report_data(trades=[], violations=[], snapshots=[])
        gen = ComplianceReportGenerator()

        output = gen.generate_comparison(report_data)

        assert "FTMO Dashboard Comparison" in output
        assert "0" in output  # Trading days should be 0


# ---------------------------------------------------------------------------
# Test 8.11: DECIMAL precision in JSON
# ---------------------------------------------------------------------------


class TestDecimalPrecision:
    """Tests for DECIMAL precision preservation."""

    def test_decimal_precision_in_json(self):
        """Test DECIMAL precision is preserved as strings in JSON output."""
        report_data = _make_report_data()
        gen = ComplianceReportGenerator()

        json_str = gen.generate_json(report_data)

        data = json.loads(json_str)
        # Summary values must be strings
        assert isinstance(data["summary"]["net_pnl"], str)
        assert isinstance(data["summary"]["opening_balance"], str)
        assert isinstance(data["summary"]["max_drawdown_percent"], str)

        # Trade values must be strings
        if data["trades"]:
            trade = data["trades"][0]
            assert isinstance(trade["pnl_dollars"], str)
            assert isinstance(trade["entry_price"], str)

        # Violation values must be strings
        if data["violations"]:
            viol = data["violations"][0]
            assert isinstance(viol["current_value"], str)
