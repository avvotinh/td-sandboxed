"""Unit tests for MetricsCalculator — orchestrates per-metric helpers into
the top-level ``FtmoMetricsSchema``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.metrics.calculator import calculate_metrics
from src.backtesting.metrics.schema import FtmoMetricsSchema
from src.backtesting.result import TradeRecord


pytestmark = pytest.mark.unit


def _make_trade(
    trade_id: str, pnl: float, entry_hour: int = 9, exit_hour: int = 10
) -> TradeRecord:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return TradeRecord(
        trade_id=trade_id,
        symbol="XAUUSD",
        side="BUY",
        entry_ts=base.replace(hour=entry_hour),
        exit_ts=base.replace(hour=exit_hour),
        entry_price=Decimal("2400"),
        exit_price=Decimal("2400") + Decimal(str(pnl)),
        quantity=Decimal("0.1"),
        pnl=Decimal(str(pnl)),
    )


def _curve(*points: tuple[int, float]) -> list[tuple[datetime, Decimal]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [(start + timedelta(days=days), Decimal(str(eq))) for days, eq in points]


class TestCalculateMetricsHappyPath:
    def test_returns_ftmo_metrics_schema(self) -> None:
        trades = [_make_trade("1", 100), _make_trade("2", -50), _make_trade("3", 75)]
        curve = _curve((0, 100000), (1, 100050), (2, 100125))
        schema = calculate_metrics(
            strategy_name="ma_crossover",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100125"),
            equity_curve=curve,
            trades=trades,
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert isinstance(schema, FtmoMetricsSchema)
        assert schema.strategy_name == "ma_crossover"
        assert schema.trades.total_trades == 3
        assert schema.trades.winning_trades == 2
        assert schema.trades.losing_trades == 1

    def test_pnl_metrics(self) -> None:
        trades = [_make_trade("1", 100), _make_trade("2", -50)]
        curve = _curve((0, 100000), (1, 100050))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100050"),
            equity_curve=curve,
            trades=trades,
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.pnl.net_pnl == pytest.approx(50.0)
        assert schema.pnl.profit_factor == pytest.approx(2.0)  # 100/50
        assert schema.pnl.return_pct == pytest.approx(0.05)


class TestCalculateMetricsEmptyInputs:
    def test_no_trades_safe_defaults(self) -> None:
        curve = _curve((0, 100000), (1, 100000))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100000"),
            equity_curve=curve,
            trades=[],
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.trades.total_trades == 0
        assert schema.pnl.profit_factor == 0.0
        assert schema.trades.win_rate == 0.0
        assert schema.ftmo_compliance.profit_target_hit is False

    def test_empty_curve_safe_defaults(self) -> None:
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100000"),
            equity_curve=[],
            trades=[],
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.drawdown.max_overall_dd_pct == 0.0
        assert schema.ftmo_compliance.min_trading_days_met is False


class TestFtmoCompliance:
    def test_breach_count_from_breach_events(self) -> None:
        from src.backtesting.result import BreachEvent
        breach = BreachEvent(
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            rule_name="daily_loss_limit",
            current_value=5.2,
            threshold_value=5.0,
            message="Daily loss 5.2% > 5%",
        )
        curve = _curve((0, 100000), (1, 94800))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("94800"),
            equity_curve=curve,
            trades=[_make_trade("1", -5200)],
            breaches=[breach],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.ftmo_compliance.daily_loss_breaches == 1

    def test_max_dd_breach_flag_true_when_over_10pct(self) -> None:
        curve = _curve((0, 100000), (1, 90000), (2, 89000))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("89000"),
            equity_curve=curve,
            trades=[],
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
            max_dd_pct=10.0,
        )
        # peak = 100000, trough = 89000 → DD = 11%, breached
        assert schema.ftmo_compliance.max_dd_breach is True

    def test_profit_target_hit_true(self) -> None:
        curve = _curve((0, 100000), (5, 110500))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("110500"),
            equity_curve=curve,
            trades=[],
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.ftmo_compliance.profit_target_hit is True

    def test_min_trading_days_met(self) -> None:
        curve = _curve((0, 100000), (1, 100100), (2, 100200), (3, 100300), (4, 100400))
        schema = calculate_metrics(
            strategy_name="s",
            initial_balance=Decimal("100000"),
            final_balance=Decimal("100400"),
            equity_curve=curve,
            trades=[],
            breaches=[],
            profit_target_pct=10.0,
            min_trading_days=4,
        )
        assert schema.ftmo_compliance.min_trading_days_met is True
