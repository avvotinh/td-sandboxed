"""Unit tests for ParameterSweep (Story 8.8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.parameter_sweep import (
    EarlyStopConfig,
    ParameterSweep,
    SweepResult,
    expand_grid,
    sample_random,
)
from src.backtesting.result import BacktestResult


def _job() -> BacktestJobConfig:
    return BacktestJobConfig(
        strategy="ma_crossover",
        strategy_params={
            "fast_period": 5,
            "slow_period": 20,
            "trade_size": "10000",
        },
        venue=VenueSpec(
            name="SIM", starting_balance=Decimal("100000"), currency="USD"
        ),
        instrument_symbol="EUR/USD",
        data=SyntheticDataSpec(
            pattern="trending", count=100, start_price=1.10, seed=7
        ),
    )


def _fake_result(
    *, net_pnl: float = 0.0, max_dd: float = 0.0, final_balance: float = 100000.0
) -> BacktestResult:
    # We keep metrics=None because the sweep reads it through a pluggable
    # objective — the test's `objective_fn` reaches into the result via
    # final_balance when metrics are None.
    return BacktestResult(
        strategy_name="ma_crossover",
        start=datetime(2024, 1, 1),
        end=datetime(2024, 1, 2),
        initial_balance=Decimal("100000"),
        final_balance=Decimal(str(final_balance)),
    )


@pytest.mark.unit
class TestComboExpansion:
    def test_grid_cartesian_product(self) -> None:
        combos = expand_grid({"a": [1, 2], "b": [3, 4]})
        expected = [
            {"a": 1, "b": 3},
            {"a": 1, "b": 4},
            {"a": 2, "b": 3},
            {"a": 2, "b": 4},
        ]
        assert combos == expected

    def test_grid_empty_grid_yields_single_empty_combo(self) -> None:
        combos = expand_grid({})
        assert combos == [{}]

    def test_random_sample_deterministic_with_seed(self) -> None:
        grid = {"a": [1, 2, 3, 4], "b": [10, 20, 30, 40]}
        a = sample_random(grid, n_iter=5, seed=42)
        b = sample_random(grid, n_iter=5, seed=42)
        assert a == b

    def test_random_sample_caps_at_grid_size(self) -> None:
        grid = {"a": [1, 2]}
        combos = sample_random(grid, n_iter=100, seed=1)
        assert len(combos) <= 2

    def test_random_sample_different_seeds_differ(self) -> None:
        grid = {"a": list(range(20)), "b": list(range(20))}
        a = sample_random(grid, n_iter=5, seed=1)
        b = sample_random(grid, n_iter=5, seed=2)
        assert a != b


@pytest.mark.unit
class TestParameterSweep:
    def test_grid_sweep_runs_all_combos(self) -> None:
        grid = {"fast_period": [3, 5], "slow_period": [10, 20]}
        fake = _fake_result(final_balance=100500)

        with patch(
            "src.backtesting.parameter_sweep.run_backtest", return_value=fake
        ) as rb:
            sweep = ParameterSweep(
                job=_job(),
                param_grid=grid,
                search="grid",
            )
            result = sweep.run(max_workers=1)

        assert isinstance(result, SweepResult)
        assert len(result.combos) == 4
        assert rb.call_count == 4
        assert all(c.status == "ok" for c in result.combos)

    def test_random_sweep_respects_n_iter(self) -> None:
        grid = {"fast_period": [3, 5, 7, 9], "slow_period": [10, 20, 30, 40]}
        fake = _fake_result()

        with patch(
            "src.backtesting.parameter_sweep.run_backtest", return_value=fake
        ) as rb:
            sweep = ParameterSweep(
                job=_job(),
                param_grid=grid,
                search="random",
                n_iter=5,
                seed=99,
            )
            sweep.run(max_workers=1)

        assert rb.call_count == 5

    def test_failed_combo_is_recorded_not_fatal(self) -> None:
        grid = {"fast_period": [3, 5], "slow_period": [10, 20]}

        call_counter = {"n": 0}

        def flaky(job, *, strategy_overrides=None):
            call_counter["n"] += 1
            if call_counter["n"] == 2:
                raise RuntimeError("engine failed")
            return _fake_result()

        with patch("src.backtesting.parameter_sweep.run_backtest", side_effect=flaky):
            sweep = ParameterSweep(
                job=_job(), param_grid=grid, search="grid"
            )
            result = sweep.run(max_workers=1)

        statuses = [c.status for c in result.combos]
        assert "failed" in statuses
        assert statuses.count("ok") == 3

    def test_early_stop_records_skipped_combos(self) -> None:
        grid = {"fast_period": [3, 5], "slow_period": [10, 20]}

        # First combo breaches, rest are fine. Early-stop semantics =
        # still record breaching combos with status="early_stop".
        results_iter = iter(
            [
                _fake_result(final_balance=90000),  # -10% → breach in mocked metric
                _fake_result(final_balance=100500),
                _fake_result(final_balance=100200),
                _fake_result(final_balance=100800),
            ]
        )

        def mock_run(job, *, strategy_overrides=None):
            return next(results_iter)

        # Use a custom objective so our mocked BacktestResult (metrics=None) works.
        def drawdown_proxy(res: BacktestResult) -> float:
            # Treat (1 - final/initial) * 100 as "max_overall_dd_pct" proxy
            return float(
                (res.initial_balance - res.final_balance) / res.initial_balance * 100
            )

        with patch("src.backtesting.parameter_sweep.run_backtest", side_effect=mock_run):
            sweep = ParameterSweep(
                job=_job(),
                param_grid=grid,
                search="grid",
                early_stop=EarlyStopConfig(
                    metric_fn=drawdown_proxy, threshold=5.0, mode="gt"
                ),
            )
            result = sweep.run(max_workers=1)

        early_stops = [c for c in result.combos if c.status == "early_stop"]
        assert len(early_stops) == 1
        assert early_stops[0].params in [
            {"fast_period": 3, "slow_period": 10},
            # Grid-order preserved by expand_grid — first combo breaches.
        ]

    def test_sweep_ranks_by_objective_descending(self) -> None:
        grid = {"fast_period": [3, 5], "slow_period": [10, 20]}
        balances = iter([100100, 100500, 100200, 100800])

        def mock_run(job, *, strategy_overrides=None):
            return _fake_result(final_balance=next(balances))

        def pnl(res: BacktestResult) -> float:
            return float(res.final_balance - res.initial_balance)

        with patch("src.backtesting.parameter_sweep.run_backtest", side_effect=mock_run):
            sweep = ParameterSweep(
                job=_job(),
                param_grid=grid,
                search="grid",
                objective_fn=pnl,
            )
            result = sweep.run(max_workers=1)

        scores = [c.score for c in result.ranked()]
        assert scores == sorted(scores, reverse=True)
        assert result.best().score == max(scores)

    def test_max_workers_zero_rejected(self) -> None:
        sweep = ParameterSweep(
            job=_job(), param_grid={"fast_period": [3]}, search="grid"
        )
        with pytest.raises(ValueError, match="max_workers"):
            sweep.run(max_workers=0)

    def test_empty_grid_produces_one_combo(self) -> None:
        fake = _fake_result()
        with patch(
            "src.backtesting.parameter_sweep.run_backtest", return_value=fake
        ) as rb:
            sweep = ParameterSweep(job=_job(), param_grid={}, search="grid")
            result = sweep.run(max_workers=1)
        assert rb.call_count == 1
        assert len(result.combos) == 1
        assert result.combos[0].params == {}
