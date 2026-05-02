"""Unit tests for WalkForward fold generation + execution (Story 8.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from src.backtesting.job_config import (
    BacktestJobConfig,
    SyntheticDataSpec,
    VenueSpec,
)
from src.backtesting.parameter_sweep import (
    CombinationResult,
    SweepResult,
)
from src.backtesting.result import BacktestResult
from src.backtesting.walk_forward import (
    FoldSpec,
    WalkForward,
    WalkForwardFolds,
    WalkForwardResult,
)


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
            pattern="trending", count=500, start_price=1.10, seed=7
        ),
    )


def _fake_result(balance: float) -> BacktestResult:
    return BacktestResult(
        strategy_name="ma_crossover",
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 31, tzinfo=UTC),
        initial_balance=Decimal("100000"),
        final_balance=Decimal(str(balance)),
    )


@pytest.mark.unit
class TestWalkForwardFolds:
    def test_anchored_keeps_train_start_fixed(self) -> None:
        total_start = datetime(2024, 1, 1, tzinfo=UTC)
        total_end = datetime(2024, 7, 1, tzinfo=UTC)
        folds = WalkForwardFolds.generate(
            total_start=total_start,
            total_end=total_end,
            train_window=timedelta(days=60),
            test_window=timedelta(days=30),
            step=timedelta(days=30),
            mode="anchored",
        )
        assert len(folds) >= 2
        for f in folds:
            assert f.train_start == total_start
            assert f.train_end <= f.test_start
            assert f.test_end <= total_end

    def test_rolling_slides_train_start(self) -> None:
        total_start = datetime(2024, 1, 1, tzinfo=UTC)
        total_end = datetime(2024, 7, 1, tzinfo=UTC)
        folds = WalkForwardFolds.generate(
            total_start=total_start,
            total_end=total_end,
            train_window=timedelta(days=60),
            test_window=timedelta(days=30),
            step=timedelta(days=30),
            mode="rolling",
        )
        assert len(folds) >= 2
        starts = [f.train_start for f in folds]
        assert starts == sorted(starts)
        assert starts[1] > starts[0]

    def test_no_test_window_overlap(self) -> None:
        folds = WalkForwardFolds.generate(
            total_start=datetime(2024, 1, 1, tzinfo=UTC),
            total_end=datetime(2024, 12, 1, tzinfo=UTC),
            train_window=timedelta(days=60),
            test_window=timedelta(days=30),
            step=timedelta(days=30),
            mode="rolling",
        )
        prev_end = datetime.min.replace(tzinfo=UTC)
        for f in folds:
            assert f.test_start >= prev_end
            prev_end = f.test_end

    def test_fold_train_strictly_precedes_test(self) -> None:
        folds = WalkForwardFolds.generate(
            total_start=datetime(2024, 1, 1, tzinfo=UTC),
            total_end=datetime(2024, 7, 1, tzinfo=UTC),
            train_window=timedelta(days=60),
            test_window=timedelta(days=30),
            step=timedelta(days=30),
            mode="anchored",
        )
        for f in folds:
            assert f.train_end <= f.test_start

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            WalkForwardFolds.generate(
                total_start=datetime(2024, 1, 1, tzinfo=UTC),
                total_end=datetime(2024, 7, 1, tzinfo=UTC),
                train_window=timedelta(days=60),
                test_window=timedelta(days=30),
                step=timedelta(days=30),
                mode="sliding",  # type: ignore[arg-type]
            )

    def test_raises_when_range_too_short(self) -> None:
        with pytest.raises(ValueError):
            WalkForwardFolds.generate(
                total_start=datetime(2024, 1, 1, tzinfo=UTC),
                total_end=datetime(2024, 1, 15, tzinfo=UTC),
                train_window=timedelta(days=60),
                test_window=timedelta(days=30),
                step=timedelta(days=30),
                mode="anchored",
            )


@pytest.mark.unit
class TestWalkForwardRun:
    def _two_folds(self) -> list[FoldSpec]:
        s = datetime(2024, 1, 1, tzinfo=UTC)
        return [
            FoldSpec(
                train_start=s,
                train_end=s + timedelta(days=30),
                test_start=s + timedelta(days=30),
                test_end=s + timedelta(days=60),
            ),
            FoldSpec(
                train_start=s,
                train_end=s + timedelta(days=60),
                test_start=s + timedelta(days=60),
                test_end=s + timedelta(days=90),
            ),
        ]

    def test_run_optimizes_per_fold_and_evaluates_oos(self) -> None:
        folds = self._two_folds()

        # Sweep returns a best combo per fold, then run_backtest is
        # called once per fold to evaluate on the test window.
        best_per_fold = [
            CombinationResult(
                params={"fast_period": 3},
                status="ok",
                result=_fake_result(101000),
                score=1000.0,
            ),
            CombinationResult(
                params={"fast_period": 7},
                status="ok",
                result=_fake_result(102000),
                score=2000.0,
            ),
        ]
        sweep_iter = iter(
            [
                SweepResult(combos=[best_per_fold[0]]),
                SweepResult(combos=[best_per_fold[1]]),
            ]
        )
        oos_iter = iter([_fake_result(100500), _fake_result(101500)])

        with (
            patch(
                "src.backtesting.walk_forward.ParameterSweep"
            ) as sweep_cls,
            patch(
                "src.backtesting.walk_forward.run_backtest",
                side_effect=lambda job, strategy_overrides=None: next(oos_iter),
            ),
        ):
            sweep_cls.return_value.run.side_effect = lambda **kwargs: next(sweep_iter)

            wf = WalkForward(
                job=_job(),
                folds=folds,
                param_grid={"fast_period": [3, 5, 7]},
            )
            result = wf.run(max_workers=1)

        assert isinstance(result, WalkForwardResult)
        assert len(result.folds) == 2
        assert result.folds[0].best_params == {"fast_period": 3}
        assert result.folds[1].best_params == {"fast_period": 7}
        # Train + test results carried through
        assert result.folds[0].test_result is not None
        assert result.folds[1].test_result is not None

    def test_run_derives_distinct_seed_per_fold(self) -> None:
        folds = self._two_folds()
        best = CombinationResult(
            params={"fast_period": 3},
            status="ok",
            result=_fake_result(101000),
            score=100.0,
        )

        seeds_per_fold: list[int] = []

        def capture_sweep(**kwargs):
            seeds_per_fold.append(kwargs.get("seed") if kwargs else None)
            return SweepResult(combos=[best])

        with (
            patch(
                "src.backtesting.walk_forward.ParameterSweep"
            ) as sweep_cls,
            patch(
                "src.backtesting.walk_forward.run_backtest",
                return_value=_fake_result(100500),
            ),
        ):
            def _record(*args, **kwargs):
                seeds_per_fold.append(kwargs.get("seed"))
                m = sweep_cls.return_value
                m.run.return_value = SweepResult(combos=[best])
                return m

            sweep_cls.side_effect = _record

            wf = WalkForward(
                job=_job(),
                folds=folds,
                param_grid={"fast_period": [3, 5]},
                search="random",
                n_iter=2,
                seed=100,
            )
            wf.run(max_workers=1)

        assert seeds_per_fold == [100, 101]

    def test_run_carries_window_into_train_and_test(self) -> None:
        folds = self._two_folds()
        best = CombinationResult(
            params={"fast_period": 3},
            status="ok",
            result=_fake_result(101000),
            score=100.0,
        )

        captured_jobs: list[BacktestJobConfig] = []

        def capture_run(**kwargs):
            return SweepResult(combos=[best])

        with (
            patch(
                "src.backtesting.walk_forward.ParameterSweep"
            ) as sweep_cls,
            patch(
                "src.backtesting.walk_forward.run_backtest",
            ) as rb,
        ):
            sweep_cls.return_value.run.side_effect = capture_run
            rb.return_value = _fake_result(100500)

            def _record_job(*args, **kwargs):
                # ParameterSweep is constructed with a windowed job
                captured_jobs.append(args[0] if args else kwargs.get("job"))
                m = sweep_cls.return_value
                m.run.side_effect = capture_run
                return m

            sweep_cls.side_effect = _record_job

            wf = WalkForward(
                job=_job(),
                folds=folds,
                param_grid={"fast_period": [3, 5]},
            )
            wf.run(max_workers=1)

        # Each fold constructs a ParameterSweep with a train-windowed job
        assert len(captured_jobs) == 2
        assert captured_jobs[0].start == folds[0].train_start
        assert captured_jobs[0].end == folds[0].train_end
