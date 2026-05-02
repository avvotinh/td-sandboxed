"""Walk-forward analysis — anchored + rolling fold generation + OOS run.

Each fold owns a train window (used to tune parameters via a nested
``ParameterSweep``) and a test window (used to evaluate the tuned
parameters out-of-sample). Anchored mode keeps ``train_start`` fixed
while ``train_end`` grows; rolling mode slides both forward by ``step``.
Test windows never overlap.

The caller may pass pre-built ``FoldSpec`` instances or ask
``WalkForwardFolds.generate`` to produce them from a total range +
window/step sizes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from src.backtesting.job_config import BacktestJobConfig
from src.backtesting.parameter_sweep import (
    EarlyStopConfig,
    ParameterSweep,
    _default_objective,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest

logger = logging.getLogger(__name__)


WalkForwardMode = Literal["anchored", "rolling"]


@dataclass(frozen=True, slots=True)
class FoldSpec:
    """Time boundaries for a single walk-forward fold."""

    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        if self.train_end > self.test_start:
            raise ValueError(
                f"train_end ({self.train_end}) must be <= test_start ({self.test_start})"
            )
        if self.test_end <= self.test_start:
            raise ValueError(
                f"test_end ({self.test_end}) must be > test_start ({self.test_start})"
            )


@dataclass(frozen=True, slots=True)
class FoldResult:
    """Per-fold walk-forward output."""

    fold: FoldSpec
    best_params: dict[str, Any]
    train_score: float
    train_result: BacktestResult | None
    test_result: BacktestResult | None


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Aggregate walk-forward output."""

    folds: list[FoldResult]
    mode: WalkForwardMode


class WalkForwardFolds:
    """Fold-generation utilities."""

    @staticmethod
    def generate(
        *,
        total_start: datetime,
        total_end: datetime,
        train_window: timedelta,
        test_window: timedelta,
        step: timedelta,
        mode: WalkForwardMode,
    ) -> list[FoldSpec]:
        """Generate non-overlapping test-window folds.

        Raises:
            ValueError: ``mode`` not in {"anchored", "rolling"} or the
                total range is shorter than ``train_window + test_window``.
        """
        if mode not in ("anchored", "rolling"):
            raise ValueError(f"Unknown mode: {mode!r}")
        if total_end - total_start < train_window + test_window:
            raise ValueError(
                "total range is shorter than train_window + test_window"
            )
        if step <= timedelta(0):
            raise ValueError("step must be positive")

        folds: list[FoldSpec] = []
        train_start = total_start
        # For anchored: train_end grows with step; for rolling: whole window slides
        train_end = total_start + train_window
        while train_end + test_window <= total_end:
            test_start = train_end
            test_end = test_start + test_window
            folds.append(
                FoldSpec(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            train_end = train_end + step
            if mode == "rolling":
                train_start = train_start + step
        if not folds:
            raise ValueError("No folds generated — widen the range or narrow the windows")
        return folds


@dataclass
class WalkForward:
    """Drive per-fold optimization + out-of-sample evaluation."""

    job: BacktestJobConfig
    folds: Sequence[FoldSpec]
    param_grid: dict[str, Sequence[Any]]
    search: Literal["grid", "random"] = "grid"
    n_iter: int | None = None
    seed: int = 42
    objective_fn: Callable[[BacktestResult], float] = _default_objective
    early_stop: EarlyStopConfig | None = None
    mode: WalkForwardMode = "anchored"
    _cached_folds: list[FoldSpec] = field(init=False)

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("At least one fold is required")
        self._cached_folds = list(self.folds)

    def run(self, *, max_workers: int = 1) -> WalkForwardResult:
        fold_results: list[FoldResult] = []
        for idx, fold in enumerate(self._cached_folds):
            fold_results.append(
                self._run_fold(fold, fold_idx=idx, max_workers=max_workers)
            )
        return WalkForwardResult(folds=fold_results, mode=self.mode)

    def _run_fold(
        self, fold: FoldSpec, *, fold_idx: int, max_workers: int
    ) -> FoldResult:
        train_job = self.job.with_window(
            start=fold.train_start, end=fold.train_end
        )
        # Derive a distinct seed per fold so random-search sweeps draw
        # different combos on each fold (same base seed would bias
        # selection identically everywhere).
        sweep = ParameterSweep(
            job=train_job,
            param_grid=self.param_grid,
            search=self.search,
            n_iter=self.n_iter,
            seed=self.seed + fold_idx,
            objective_fn=self.objective_fn,
            early_stop=self.early_stop,
        )
        sweep_result = sweep.run(max_workers=max_workers)
        try:
            best = sweep_result.best()
        except ValueError:
            logger.warning(
                "Fold %s produced no successful combos; skipping OOS eval",
                fold,
            )
            return FoldResult(
                fold=fold,
                best_params={},
                train_score=float("-inf"),
                train_result=None,
                test_result=None,
            )

        test_job = self.job.with_window(
            start=fold.test_start, end=fold.test_end
        )
        test_result = run_backtest(
            test_job, strategy_overrides=best.params
        )
        return FoldResult(
            fold=fold,
            best_params=best.params,
            train_score=best.score,
            train_result=best.result,
            test_result=test_result,
        )
