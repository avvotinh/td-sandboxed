"""Unit tests for FTMO-specific metrics (drawdown, breach counts, etc.)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.backtesting.metrics.ftmo_metrics import (
    compute_daily_pnl_percentages,
    compute_max_daily_drawdown_pct,
    compute_max_overall_drawdown_pct,
    compute_profit_target_hit,
    compute_recovery_factor,
    compute_trading_days_count,
)


pytestmark = pytest.mark.unit


def _curve(
    *values: float, start: datetime | None = None
) -> list[tuple[datetime, Decimal]]:
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    return [
        (start + timedelta(hours=i), Decimal(str(v))) for i, v in enumerate(values)
    ]


class TestMaxOverallDrawdown:
    def test_flat_equity_zero_dd(self) -> None:
        curve = _curve(100000, 100000, 100000)
        assert compute_max_overall_drawdown_pct(curve) == 0.0

    def test_simple_drawdown_10pct(self) -> None:
        curve = _curve(100000, 110000, 99000, 105000)
        # Peak 110000, trough after peak = 99000 → DD = (110000-99000)/110000 = 10%
        assert compute_max_overall_drawdown_pct(curve) == pytest.approx(10.0)

    def test_multiple_drawdowns_returns_max(self) -> None:
        curve = _curve(100, 120, 100, 130, 90)
        # DD1 = (120-100)/120 = 16.67%; DD2 = (130-90)/130 = 30.77%
        assert compute_max_overall_drawdown_pct(curve) == pytest.approx(
            (130 - 90) / 130 * 100
        )

    def test_empty_curve_zero(self) -> None:
        assert compute_max_overall_drawdown_pct([]) == 0.0

    def test_single_point_zero(self) -> None:
        curve = _curve(100000)
        assert compute_max_overall_drawdown_pct(curve) == 0.0


class TestMaxDailyDrawdown:
    def test_single_day_drop(self) -> None:
        # Day 1: 100k → 95k → 95k (bars within same UTC day)
        day1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        curve = [
            (day1, Decimal("100000")),
            (day1.replace(hour=14), Decimal("95000")),
        ]
        # Daily PnL % = (95000-100000)/100000 = -5%
        max_daily = compute_max_daily_drawdown_pct(curve, initial_balance=Decimal("100000"))
        assert max_daily == pytest.approx(5.0)

    def test_multi_day_returns_worst(self) -> None:
        day1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        day2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        curve = [
            (day1, Decimal("100000")),
            (day1.replace(hour=23), Decimal("98000")),  # Day 1 end: -2%
            (day2, Decimal("98000")),
            (day2.replace(hour=23), Decimal("92000")),  # Day 2 end: vs day-open 98000 → -6.12%
        ]
        # Use initial balance as reference (FTMO convention)
        max_daily = compute_max_daily_drawdown_pct(
            curve, initial_balance=Decimal("100000")
        )
        # Worst daily DD: from day-open to day-close. Day 2: 98k -> 92k = -6000 = 6% of initial
        assert max_daily == pytest.approx(6.0)

    def test_empty_curve_zero(self) -> None:
        assert (
            compute_max_daily_drawdown_pct([], initial_balance=Decimal("100000")) == 0.0
        )


class TestComputeDailyPnlPercentages:
    def test_positive_day(self) -> None:
        day1 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        curve = [
            (day1, Decimal("100000")),
            (day1.replace(hour=23), Decimal("101500")),
        ]
        pct_list = compute_daily_pnl_percentages(curve, initial_balance=Decimal("100000"))
        assert len(pct_list) == 1
        assert pct_list[0] == pytest.approx(1.5)


class TestProfitTargetHit:
    def test_final_balance_above_target(self) -> None:
        assert compute_profit_target_hit(
            initial_balance=Decimal("100000"),
            final_balance=Decimal("110001"),
            target_pct=10.0,
        )

    def test_final_balance_at_target(self) -> None:
        assert compute_profit_target_hit(
            initial_balance=Decimal("100000"),
            final_balance=Decimal("110000"),
            target_pct=10.0,
        )

    def test_final_balance_below_target(self) -> None:
        assert not compute_profit_target_hit(
            initial_balance=Decimal("100000"),
            final_balance=Decimal("109999"),
            target_pct=10.0,
        )


class TestRecoveryFactor:
    def test_normal(self) -> None:
        # net_pnl = 5000, max_dd = 2500 → RF = 2.0
        assert compute_recovery_factor(
            net_pnl=Decimal("5000"), max_dd_abs=Decimal("2500")
        ) == pytest.approx(2.0)

    def test_zero_dd(self) -> None:
        assert (
            compute_recovery_factor(
                net_pnl=Decimal("5000"), max_dd_abs=Decimal("0")
            )
            == 0.0
        )


class TestTradingDaysCount:
    def test_three_distinct_days(self) -> None:
        day1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        day2 = day1 + timedelta(days=1)
        day3 = day1 + timedelta(days=2)
        curve = [
            (day1, Decimal("100000")),
            (day2, Decimal("101000")),
            (day3, Decimal("102000")),
        ]
        assert compute_trading_days_count(curve) == 3

    def test_multiple_bars_same_day(self) -> None:
        day1 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        curve = [
            (day1, Decimal("100000")),
            (day1.replace(hour=12), Decimal("100500")),
            (day1.replace(hour=16), Decimal("101000")),
        ]
        assert compute_trading_days_count(curve) == 1

    def test_empty(self) -> None:
        assert compute_trading_days_count([]) == 0
