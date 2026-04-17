"""Unit tests for trade-level metrics (profit factor, Sharpe, etc.)."""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from src.backtesting.metrics.trade_metrics import (
    compute_avg_loss,
    compute_avg_win,
    compute_expectancy,
    compute_max_consecutive_losses,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_win_rate,
)


pytestmark = pytest.mark.unit


class TestProfitFactor:
    def test_basic(self) -> None:
        pnls = [100, 50, -30, -20]
        # winners = 150, losers = 50 → PF = 3.0
        assert compute_profit_factor(pnls) == pytest.approx(3.0)

    def test_all_wins_infinite(self) -> None:
        assert math.isinf(compute_profit_factor([10, 20, 30]))

    def test_all_losses_zero(self) -> None:
        assert compute_profit_factor([-10, -20, -30]) == 0.0

    def test_empty_zero(self) -> None:
        assert compute_profit_factor([]) == 0.0


class TestWinRate:
    def test_mixed(self) -> None:
        assert compute_win_rate([1, 2, -1, -2]) == pytest.approx(0.5)

    def test_all_wins(self) -> None:
        assert compute_win_rate([1, 2, 3]) == 1.0

    def test_all_losses(self) -> None:
        assert compute_win_rate([-1, -2]) == 0.0

    def test_empty(self) -> None:
        assert compute_win_rate([]) == 0.0


class TestAvgWinLoss:
    def test_avg_win(self) -> None:
        assert compute_avg_win([10, 20, -5, -15]) == pytest.approx(15.0)

    def test_avg_loss(self) -> None:
        # losers = [-5, -15], avg = -10
        assert compute_avg_loss([10, 20, -5, -15]) == pytest.approx(-10.0)

    def test_no_wins_returns_zero(self) -> None:
        assert compute_avg_win([-1, -2]) == 0.0

    def test_no_losses_returns_zero(self) -> None:
        assert compute_avg_loss([1, 2]) == 0.0


class TestExpectancy:
    def test_expectancy_formula(self) -> None:
        # 2 wins avg 10, 2 losses avg -5. win_rate=0.5.
        # expectancy = 0.5*10 + 0.5*(-5) = 5 - 2.5 = 2.5
        assert compute_expectancy([10, 10, -5, -5]) == pytest.approx(2.5)

    def test_empty_zero(self) -> None:
        assert compute_expectancy([]) == 0.0


class TestMaxConsecutiveLosses:
    def test_basic(self) -> None:
        assert compute_max_consecutive_losses([1, -1, -1, -1, 1, -1, -1]) == 3

    def test_no_losses(self) -> None:
        assert compute_max_consecutive_losses([1, 2, 3]) == 0

    def test_all_losses(self) -> None:
        assert compute_max_consecutive_losses([-1, -2, -3]) == 3

    def test_empty(self) -> None:
        assert compute_max_consecutive_losses([]) == 0


class TestSharpeRatio:
    def test_known_inputs(self) -> None:
        # mean=0.001, std=0.01, n=252 → sharpe ≈ (0.001/0.01) * sqrt(252) ≈ 1.587
        returns = [0.001] * 252
        # constant returns = zero std, Sharpe should be 0 or inf — guard
        assert compute_sharpe_ratio(returns) == 0.0

    def test_mixed_returns_positive(self) -> None:
        # Synthetic: 100 returns centered at 0.1% with small noise
        returns = [0.001 + (0.0005 if i % 2 == 0 else -0.0005) for i in range(252)]
        s = compute_sharpe_ratio(returns)
        assert s > 0

    def test_empty_zero(self) -> None:
        assert compute_sharpe_ratio([]) == 0.0


class TestSortinoRatio:
    def test_positive_when_downside_controlled(self) -> None:
        returns = [0.01, 0.02, -0.005, 0.01, 0.015, -0.003]
        s = compute_sortino_ratio(returns)
        assert s > 0

    def test_empty_zero(self) -> None:
        assert compute_sortino_ratio([]) == 0.0

    def test_no_negative_returns_infinite(self) -> None:
        # All-positive returns → no downside deviation → inf
        assert math.isinf(compute_sortino_ratio([0.01, 0.02, 0.005]))


class TestAcceptsDecimal:
    def test_decimal_pnls(self) -> None:
        pnls = [Decimal("10"), Decimal("20"), Decimal("-5")]
        assert compute_profit_factor(pnls) == pytest.approx(6.0)
        assert compute_win_rate(pnls) == pytest.approx(2 / 3)
