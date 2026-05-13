"""Unit tests for the Epic 13 backtest A/B comparison (Story 13.9)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from src.backtesting.ab_compare import (
    ABComparisonResult,
    WinnerDistribution,
    compare_ab,
    compute_winner_distribution,
    winner_distribution_to_dict,
)
from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    PnlMetrics,
    PropFirmComplianceMetrics,
    PropFirmMetricsSchema,
    RiskMetrics,
    TradeMetrics,
)
from src.backtesting.result import BacktestResult, TradeRecord


def _trade(pnl: float, *, trade_id: str = "t") -> TradeRecord:
    """Build a TradeRecord with only ``pnl`` mattering for these tests."""
    return TradeRecord(
        trade_id=trade_id,
        symbol="XAUUSD",
        side="BUY",
        entry_ts=datetime(2024, 1, 1),
        exit_ts=datetime(2024, 1, 1),
        entry_price=Decimal("2000"),
        exit_price=Decimal("2000"),
        quantity=Decimal("1"),
        pnl=Decimal(str(pnl)),
    )


def _metrics(
    *,
    total_trades: int,
    win_rate: float,
    expectancy: float,
    avg_r_multiple: float,
    return_pct: float = 0.0,
    max_dd_pct: float = 0.0,
    sharpe: float = 0.0,
) -> PropFirmMetricsSchema:
    return PropFirmMetricsSchema(
        strategy_name="supertrend",
        pnl=PnlMetrics(
            gross_pnl=0.0,
            net_pnl=0.0,
            return_pct=return_pct,
            profit_factor=1.0,
            expectancy=expectancy,
            avg_r_multiple=avg_r_multiple,
        ),
        drawdown=DrawdownMetrics(
            max_overall_dd_pct=max_dd_pct,
            max_overall_dd_abs=0.0,
            max_daily_dd_pct=0.0,
            avg_daily_dd_pct=0.0,
            recovery_factor=0.0,
        ),
        risk=RiskMetrics(
            sharpe_ratio=sharpe,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_consecutive_losses=0,
        ),
        trades=TradeMetrics(
            total_trades=total_trades,
            winning_trades=int(round(total_trades * win_rate)),
            losing_trades=total_trades - int(round(total_trades * win_rate)),
            win_rate=win_rate,
            avg_win=0.0,
            avg_loss=0.0,
        ),
        prop_firm_compliance=PropFirmComplianceMetrics(
            daily_loss_breaches=0,
            max_dd_breach=False,
            profit_target_hit=False,
            min_trading_days_met=False,
        ),
    )


def _result(*, trades: list[TradeRecord], metrics: PropFirmMetricsSchema) -> BacktestResult:
    return BacktestResult(
        strategy_name="supertrend",
        start=datetime(2024, 1, 1),
        end=datetime(2026, 1, 1),
        initial_balance=Decimal("100000"),
        final_balance=Decimal("110000"),
        trades=trades,
        metrics=metrics,
    )


@pytest.mark.unit
class TestComputeWinnerDistribution:
    def test_empty_trades_yields_zero_distribution(self) -> None:
        dist = compute_winner_distribution([])
        assert dist.count == 0
        assert dist.avg_loss_abs == 0.0
        assert dist.p95 == 0.0
        assert dist.largest_winner_r == 0.0

    def test_no_losers_yields_undefined_R(self) -> None:
        # All wins → avg_loss = 0 → R is undefined per docstring contract.
        dist = compute_winner_distribution([_trade(100), _trade(200)])
        assert dist.count == 0
        assert dist.avg_loss_abs == 0.0

    def test_single_winner_uses_avg_loss_denominator(self) -> None:
        # 2 losers at -100 each → avg_loss = 100; 1 winner at +200 → R = 2.
        dist = compute_winner_distribution(
            [_trade(-100, trade_id="l1"), _trade(-100, trade_id="l2"), _trade(200, trade_id="w1")]
        )
        assert dist.count == 1
        assert dist.avg_loss_abs == pytest.approx(100.0)
        assert dist.largest_winner_r == pytest.approx(2.0)

    def test_percentiles_track_distribution_shape(self) -> None:
        # avg_loss = 100; winners pnl: 50, 100, 200, 500, 1000 → R: 0.5, 1, 2, 5, 10.
        trades = [_trade(-100, trade_id=f"l{i}") for i in range(3)] + [
            _trade(50),
            _trade(100),
            _trade(200),
            _trade(500),
            _trade(1000),
        ]
        dist = compute_winner_distribution(trades)
        assert dist.count == 5
        assert dist.p50 == pytest.approx(2.0)
        assert dist.largest_winner_r == pytest.approx(10.0)
        # 95th percentile must sit between 5R and 10R.
        assert 5.0 <= dist.p95 <= 10.0


@pytest.mark.unit
class TestCompareAb:
    def test_returns_both_results_and_distributions(self) -> None:
        baseline_trades = [_trade(-100, trade_id=f"bl{i}") for i in range(2)] + [
            _trade(200, trade_id="bw")
        ]
        variant_trades = [_trade(-100, trade_id=f"vl{i}") for i in range(2)] + [
            _trade(500, trade_id="vw")
        ]
        baseline = _result(
            trades=baseline_trades,
            metrics=_metrics(
                total_trades=3, win_rate=0.33, expectancy=0.0, avg_r_multiple=0.0
            ),
        )
        variant = _result(
            trades=variant_trades,
            metrics=_metrics(
                total_trades=3, win_rate=0.33, expectancy=100.0, avg_r_multiple=1.0
            ),
        )

        comp = compare_ab(baseline=baseline, variant=variant)

        assert isinstance(comp, ABComparisonResult)
        assert comp.baseline_winners.largest_winner_r == pytest.approx(2.0)
        assert comp.variant_winners.largest_winner_r == pytest.approx(5.0)

    def test_metric_deltas_quote_baseline_variant_delta_and_pct(self) -> None:
        baseline = _result(
            trades=[],
            metrics=_metrics(
                total_trades=100, win_rate=0.40, expectancy=20.0, avg_r_multiple=0.20
            ),
        )
        variant = _result(
            trades=[],
            metrics=_metrics(
                total_trades=100, win_rate=0.42, expectancy=26.0, avg_r_multiple=0.26
            ),
        )

        comp = compare_ab(baseline=baseline, variant=variant)

        ev = comp.metric_deltas["expectancy"]
        assert ev["baseline"] == 20.0
        assert ev["variant"] == 26.0
        assert ev["delta"] == pytest.approx(6.0)
        assert ev["pct_change"] == pytest.approx(30.0)  # 30% EV uplift cited by quant review

    def test_zero_baseline_pct_change_is_zero_not_inf(self) -> None:
        baseline = _result(
            trades=[],
            metrics=_metrics(
                total_trades=0, win_rate=0.0, expectancy=0.0, avg_r_multiple=0.0
            ),
        )
        variant = _result(
            trades=[],
            metrics=_metrics(
                total_trades=10, win_rate=0.5, expectancy=5.0, avg_r_multiple=0.5
            ),
        )

        comp = compare_ab(baseline=baseline, variant=variant)
        assert comp.metric_deltas["expectancy"]["pct_change"] == 0.0
        assert comp.metric_deltas["expectancy"]["delta"] == pytest.approx(5.0)


@pytest.mark.unit
class TestWinnerDistributionToDict:
    def test_round_trips_all_fields(self) -> None:
        dist = WinnerDistribution(
            count=3,
            avg_loss_abs=100.0,
            p50=2.0,
            p75=3.0,
            p90=5.0,
            p95=7.0,
            p99=9.0,
            largest_winner_r=10.0,
        )
        out = winner_distribution_to_dict(dist)
        assert out == {
            "count": 3,
            "avg_loss_abs": 100.0,
            "p50": 2.0,
            "p75": 3.0,
            "p90": 5.0,
            "p95": 7.0,
            "p99": 9.0,
            "largest_winner_r": 10.0,
        }
