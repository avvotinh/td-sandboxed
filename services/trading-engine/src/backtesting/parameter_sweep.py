"""Parameter sweep driver for ``BacktestJobConfig``.

Given a base job and a parameter grid, expands the grid into concrete
parameter combinations, dispatches each combination through
``run_backtest`` (optionally via a ``ProcessPoolExecutor``), and returns
a ranked ``SweepResult``.

Grid search enumerates the Cartesian product. Random search samples
``n_iter`` combinations deterministically given a seed. Early-stop is a
*skip-record* (breaching combos are retained with status
``"early_stop"``) rather than *abort-sweep* so the user still sees the
full parameter map.
"""

from __future__ import annotations

import itertools
import logging
import random
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Literal

from src.backtesting.job_config import BacktestJobConfig
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest

logger = logging.getLogger(__name__)

# Default objective = net_pnl (higher = better). Kept as a module-level
# function so tests can override via the ``objective_fn`` constructor arg
# and workers can pickle it by reference.
def _default_objective(res: BacktestResult) -> float:
    return float(res.final_balance - res.initial_balance)


# Default early-stop proxy: the sweep caller provides a metric_fn; this
# stub is only used if the user wires an early_stop without a metric_fn.
def _default_metric(res: BacktestResult) -> float:
    return 0.0


# --- Combo expansion --------------------------------------------------


def expand_grid(grid: dict[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Return the Cartesian product of ``grid`` as a list of parameter dicts."""
    if not grid:
        return [{}]
    keys = list(grid.keys())
    value_lists = [list(grid[k]) for k in keys]
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*value_lists)]


def sample_random(
    grid: dict[str, Sequence[Any]],
    *,
    n_iter: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Return ``n_iter`` distinct combos sampled deterministically.

    If ``n_iter`` exceeds the full Cartesian size, the full product is
    returned (without repetition). Identical ``(grid, n_iter, seed)``
    yields identical output.
    """
    full = expand_grid(grid)
    if n_iter >= len(full):
        return full
    rng = random.Random(seed)
    return rng.sample(full, n_iter)


# --- Result dataclasses -----------------------------------------------


@dataclass(frozen=True, slots=True)
class CombinationResult:
    """Outcome of one parameter combination."""

    params: dict[str, Any]
    status: Literal["ok", "failed", "early_stop"]
    result: BacktestResult | None
    score: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SweepResult:
    """Aggregate sweep output."""

    combos: list[CombinationResult]
    ranked_by: str = "score"

    def ranked(self) -> list[CombinationResult]:
        """Return ``ok`` combos sorted by ``score`` descending."""
        ok = [c for c in self.combos if c.status == "ok"]
        return sorted(ok, key=lambda c: c.score, reverse=True)

    def best(self) -> CombinationResult:
        """Best ``ok`` combo by score."""
        ranked = self.ranked()
        if not ranked:
            raise ValueError("No successful combos in sweep result")
        return ranked[0]


@dataclass(frozen=True, slots=True)
class EarlyStopConfig:
    """Skip-record criterion for catastrophic combos."""

    metric_fn: Callable[[BacktestResult], float]
    threshold: float
    mode: Literal["gt", "lt"] = "gt"

    def should_stop(self, res: BacktestResult) -> bool:
        value = self.metric_fn(res)
        return value > self.threshold if self.mode == "gt" else value < self.threshold


# --- Worker entry -----------------------------------------------------


def _run_combo(
    job_json: str,
    overrides: dict[str, Any],
) -> tuple[dict[str, Any], BacktestResult]:
    """Worker entry: rebuild the job inside the subprocess and run it.

    Passing the job as JSON-serializable string keeps the IPC surface
    minimal and picklable across process boundaries.
    """
    job = BacktestJobConfig.model_validate_json(job_json)
    return overrides, run_backtest(job, strategy_overrides=overrides)


# --- ParameterSweep ---------------------------------------------------


@dataclass
class ParameterSweep:
    """Grid / random parameter sweep over a ``BacktestJobConfig``."""

    job: BacktestJobConfig
    param_grid: dict[str, Sequence[Any]]
    search: Literal["grid", "random"] = "grid"
    n_iter: int | None = None
    seed: int = 42
    objective_fn: Callable[[BacktestResult], float] = _default_objective
    early_stop: EarlyStopConfig | None = None
    ranked_by: str = "score"

    _combos: list[dict[str, Any]] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._combos = self._expand()

    # --- Planning ----------------------------------------------------

    def _expand(self) -> list[dict[str, Any]]:
        if self.search == "grid":
            return expand_grid(self.param_grid)
        if self.search == "random":
            if self.n_iter is None or self.n_iter <= 0:
                raise ValueError("random search requires n_iter > 0")
            return sample_random(self.param_grid, n_iter=self.n_iter, seed=self.seed)
        raise ValueError(f"Unknown search: {self.search!r}")

    @property
    def combinations(self) -> list[dict[str, Any]]:
        return list(self._combos)

    # --- Execution ---------------------------------------------------

    def run(self, *, max_workers: int = 1) -> SweepResult:
        """Execute every combination and return a ranked ``SweepResult``.

        ``max_workers`` must be ``>= 1``. ``1`` runs sequentially;
        higher values dispatch combos to a ``ProcessPoolExecutor``.
        """
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1, got {max_workers}")
        if max_workers == 1 or len(self._combos) <= 1:
            return self._run_sequential()
        return self._run_parallel(max_workers=max_workers)

    def _run_sequential(self) -> SweepResult:
        combos: list[CombinationResult] = []
        for params in self._combos:
            combos.append(self._run_one(params))
        return SweepResult(combos=combos, ranked_by=self.ranked_by)

    def _run_parallel(self, *, max_workers: int) -> SweepResult:
        job_json = self.job.model_dump_json()
        combos_by_params: dict[int, CombinationResult] = {}

        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            future_to_idx = {
                pool.submit(_run_combo, job_json, params): idx
                for idx, params in enumerate(self._combos)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                params = self._combos[idx]
                combos_by_params[idx] = self._finalize_future(future, params)

        ordered = [combos_by_params[i] for i in range(len(self._combos))]
        return SweepResult(combos=ordered, ranked_by=self.ranked_by)

    def _finalize_future(
        self, future: Any, params: dict[str, Any]
    ) -> CombinationResult:
        try:
            _, res = future.result()
        except Exception as exc:
            logger.warning("Combo %s failed: %s", params, exc)
            return CombinationResult(
                params=params,
                status="failed",
                result=None,
                score=float("-inf"),
                error=str(exc),
            )
        return self._classify(params, res)

    def _run_one(self, params: dict[str, Any]) -> CombinationResult:
        try:
            res = run_backtest(self.job, strategy_overrides=params)
        except Exception as exc:
            logger.warning("Combo %s failed: %s", params, exc)
            return CombinationResult(
                params=params,
                status="failed",
                result=None,
                score=float("-inf"),
                error=str(exc),
            )
        return self._classify(params, res)

    def _classify(
        self, params: dict[str, Any], res: BacktestResult
    ) -> CombinationResult:
        if self.early_stop is not None and self.early_stop.should_stop(res):
            return CombinationResult(
                params=params,
                status="early_stop",
                result=res,
                score=float("-inf"),
            )
        score = float(self.objective_fn(res))
        return CombinationResult(
            params=params,
            status="ok",
            result=res,
            score=score,
        )
