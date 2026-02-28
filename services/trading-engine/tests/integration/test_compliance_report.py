"""Integration tests for compliance report CLI commands (Story 7.6)."""

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
# Test data factories
# ---------------------------------------------------------------------------


def _make_trade_record(**kwargs) -> MagicMock:
    """Create a mock TradeRecord with defaults."""
    defaults = {
        "trade_id": uuid.uuid4(),
        "account_id": "test-001",
        "symbol": "XAUUSD",
        "side": "BUY",
        "quantity": Decimal("0.10"),
        "entry_price": Decimal("1850.25000"),
        "exit_price": Decimal("1858.50000"),
        "entry_time": datetime(2025, 12, 3, 10, 0, 0, tzinfo=timezone.utc),
        "exit_time": datetime(2025, 12, 3, 11, 0, 0, tzinfo=timezone.utc),
        "pnl_dollars": Decimal("82.50"),
        "pnl_percent": Decimal("0.0825"),
        "strategy_name": "ma_crossover",
        "status": "closed",
    }
    defaults.update(kwargs)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    record.to_dict.return_value = {
        k: str(v) if isinstance(v, (Decimal, uuid.UUID)) else
        v.isoformat() if isinstance(v, datetime) else v
        for k, v in defaults.items()
    }
    return record


def _make_violation_record(**kwargs) -> MagicMock:
    """Create a mock RuleViolationModel with defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "account_id": "test-001",
        "timestamp": datetime(2025, 12, 3, 14, 30, 0, tzinfo=timezone.utc),
        "rule_type": "daily_loss_limit",
        "rule_name": "Daily Loss Limit",
        "severity": "CRITICAL",
        "current_value": Decimal("4.8000"),
        "threshold_value": Decimal("5.0000"),
        "action_taken": "blocked",
        "order_blocked": True,
        "message": "Daily loss limit approaching",
    }
    defaults.update(kwargs)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    record.to_dict.return_value = {
        k: str(v) if isinstance(v, (Decimal, uuid.UUID)) else
        v.isoformat() if isinstance(v, datetime) else v
        for k, v in defaults.items()
    }
    return record


def _make_snapshot_record(**kwargs) -> MagicMock:
    """Create a mock AccountSnapshotModel with defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "account_id": "test-001",
        "snapshot_date": date(2025, 12, 3),
        "opening_balance": Decimal("100000.00"),
        "closing_balance": Decimal("100500.00"),
        "high_balance": Decimal("100800.00"),
        "low_balance": Decimal("99500.00"),
        "daily_pnl": Decimal("500.00"),
        "daily_pnl_percent": Decimal("0.5000"),
        "drawdown_percent": Decimal("1.5000"),
        "peak_balance": Decimal("101000.00"),
        "trades_count": 5,
        "winning_trades": 3,
        "losing_trades": 2,
    }
    defaults.update(kwargs)
    record = MagicMock()
    for k, v in defaults.items():
        setattr(record, k, v)
    record.to_dict.return_value = {
        k: str(v) if isinstance(v, (Decimal, uuid.UUID)) else
        v.isoformat() if isinstance(v, (datetime, date)) else v
        for k, v in defaults.items()
    }
    return record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db_session():
    """Create a mock async DB session returning test data."""
    session = AsyncMock()
    trades = [_make_trade_record()]
    violations = [_make_violation_record()]
    snapshots = [_make_snapshot_record()]

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

    session.scalars = AsyncMock(side_effect=mock_scalars)
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
def patch_report_db(mock_session_factory):
    """Patch _get_db_session_factory in report module."""
    with patch(
        "src.cli.report._get_db_session_factory",
        return_value=mock_session_factory,
    ):
        yield mock_session_factory


# ---------------------------------------------------------------------------
# Test 8.12: Full CLI report --format json
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReportJsonCli:
    """Integration test: Full CLI report --format json."""

    def test_report_json_via_cli(self, patch_report_db):
        """Test full CLI invocation of report generate --format json."""
        result = runner.invoke(
            app, ["report", "--account", "test-001", "--format", "json"]
        )

        assert result.exit_code == 0
        # Output should contain valid JSON (before the "saved" message)
        lines = result.output.strip().split("\n")
        # Find the JSON block (everything before "JSON report saved")
        json_lines = []
        for line in lines:
            if "JSON report saved" in line:
                break
            json_lines.append(line)
        json_str = "\n".join(json_lines)
        data = json.loads(json_str)
        assert data["report"]["account_id"] == "test-001"
        assert "trades" in data
        assert "violations" in data
        assert "summary" in data


# ---------------------------------------------------------------------------
# Test 8.13: Full CLI report --format pdf
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReportPdfCli:
    """Integration test: Full CLI report --format pdf."""

    def test_report_pdf_via_cli(self, patch_report_db, tmp_path, monkeypatch):
        """Test full CLI invocation of report generate --format pdf."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["report", "--account", "test-001", "--format", "pdf"]
        )

        assert result.exit_code == 0
        assert "PDF report generated" in result.output

        # Verify PDF file was created
        pdf_files = list(tmp_path.glob("compliance-report-*.pdf"))
        assert len(pdf_files) == 1
        assert pdf_files[0].stat().st_size > 0


# ---------------------------------------------------------------------------
# Test 8.14: Full CLI report --compare-dashboard
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReportCompareDashboardCli:
    """Integration test: Full CLI report --compare-dashboard."""

    def test_compare_dashboard_via_cli(self, patch_report_db):
        """Test full CLI invocation of report generate --compare-dashboard."""
        result = runner.invoke(
            app,
            ["report", "--account", "test-001", "--compare-dashboard"],
        )

        assert result.exit_code == 0
        assert "FTMO Dashboard Comparison" in result.output
        assert "System Value" in result.output
        assert "[___]" in result.output


# ---------------------------------------------------------------------------
# Test 8.15: Full CLI report --format csv
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestReportCsvCli:
    """Integration test: Full CLI report --format csv."""

    def test_report_csv_via_cli(self, patch_report_db, tmp_path, monkeypatch):
        """Test full CLI invocation of report generate --format csv."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app, ["report", "--account", "test-001", "--format", "csv"]
        )

        assert result.exit_code == 0
        assert "Exported to" in result.output
        assert "CSV files generated" in result.output

        # Verify CSV files were created
        csv_files = list(tmp_path.glob("report-test-001-*.csv"))
        assert len(csv_files) == 4  # trades, violations, snapshots, summary
