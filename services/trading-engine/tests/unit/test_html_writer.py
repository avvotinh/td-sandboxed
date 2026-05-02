"""Unit tests for the HTML report writer (Story 8.9)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from src.backtesting.reports.html_writer import render_html_report, write_html_report
from src.backtesting.result import BacktestResult, BreachEvent, TradeRecord


def _trade(ts: datetime, pnl: float) -> TradeRecord:
    return TradeRecord(
        trade_id=f"T-{int(ts.timestamp())}",
        symbol="EUR/USD",
        side="BUY",
        entry_ts=ts,
        exit_ts=ts,
        entry_price=Decimal("1.10"),
        exit_price=Decimal("1.11"),
        quantity=Decimal("10000"),
        pnl=Decimal(str(pnl)),
    )


def _result(*, trades=(), breaches=()) -> BacktestResult:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)
    return BacktestResult(
        strategy_name="ma_crossover",
        start=start,
        end=end,
        initial_balance=Decimal("100000"),
        final_balance=Decimal("101500"),
        equity_curve=[
            (start, Decimal("100000")),
            (end, Decimal("101500")),
        ],
        trades=list(trades),
        breaches=list(breaches),
    )


@pytest.mark.unit
class TestRenderHtmlReport:
    def test_contains_summary_fields(self) -> None:
        html = render_html_report(_result())
        assert "ma_crossover" in html
        assert "100000" in html
        assert "101500" in html
        assert "<svg" in html  # equity curve SVG inline

    def test_no_trades_section_hidden_when_empty(self) -> None:
        html = render_html_report(_result())
        # "No trades recorded" message instead of table
        assert "No trades recorded" in html

    def test_breach_table_rendered(self) -> None:
        breach = BreachEvent(
            ts=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            rule_name="DailyLossLimit",
            current_value=-5.2,
            threshold_value=5.0,
            message="daily loss 5.2% exceeded 5.0%",
        )
        html = render_html_report(_result(breaches=[breach]))
        assert "DailyLossLimit" in html
        assert "daily loss 5.2" in html

    def test_deterministic_same_input_same_html(self) -> None:
        result = _result(trades=[_trade(datetime(2024, 1, 1, 10, tzinfo=UTC), 50.0)])
        h1 = hashlib.sha256(render_html_report(result).encode()).hexdigest()
        h2 = hashlib.sha256(render_html_report(result).encode()).hexdigest()
        assert h1 == h2

    def test_escapes_html_unsafe_strings(self) -> None:
        breach = BreachEvent(
            ts=datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            rule_name="<script>alert('xss')</script>",
            current_value=-1.0,
            threshold_value=5.0,
            message="x",
        )
        html = render_html_report(_result(breaches=[breach]))
        assert "<script>alert" not in html
        # Escaped form must appear instead
        assert "&lt;script&gt;" in html


@pytest.mark.unit
class TestWriteHtmlReport:
    def test_writes_file(self, tmp_path: Path) -> None:
        out = tmp_path / "subdir" / "report.html"
        write_html_report(_result(), out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "ma_crossover" in content

    def test_rejects_traversal_path(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="traversal"):
            write_html_report(_result(), Path("../etc/report.html"))

    def test_writes_utf8(self, tmp_path: Path) -> None:
        # Strategy name with non-ASCII must round-trip under UTF-8.
        out = tmp_path / "report.html"
        result = _result()
        result = BacktestResult(
            strategy_name="chiến_lược",
            start=result.start,
            end=result.end,
            initial_balance=result.initial_balance,
            final_balance=result.final_balance,
        )
        write_html_report(result, out)
        assert "chiến_lược" in out.read_text(encoding="utf-8")
