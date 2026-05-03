"""Parameter sweep harness — Epic 12 Story 12.6.

Composes a manifest-driven parameter sweep with the Decision §3 cap
(≤ 200 trials/strategy) and the Risk R3 default early-stop on
``max_overall_dd_pct > 10%`` (skip-record, never aborts the sweep).

Two samplers ship: ``"random"`` (deterministic with seed=42) and
``"grid"`` (full Cartesian, refuses to run when the product exceeds
the budget — explicit truncation only via ``"random"``). A third
``"optuna"`` slot is wired but lazily imported; until ``optuna`` is
added to the trading-engine deps the call raises a helpful
``RuntimeError`` pointing the caller at the random fallback.

The harness reuses the existing :mod:`src.backtesting.parameter_sweep`
primitives (``expand_grid`` / ``sample_random`` / ``EarlyStopConfig`` /
``CombinationResult`` / ``SweepResult``) and adds:

* :class:`ParamSpace` — YAML-loadable per-strategy explicit value lists.
* :class:`SweepBudget` — cap envelope.
* :func:`default_max_dd_early_stop` — Risk R3 helper.
* :func:`run_parameter_sweep` — manifest-driven dispatch via injectable
  runner so unit tests don't spin up Nautilus.
* :func:`render_sweep_section` — markdown sub-section for the
  validation report.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml

from src.backtesting.dataset.baseline_harness import StrategySpec
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    PropFirmSpec,
    VenueSpec,
)
from src.backtesting.parameter_sweep import (
    CombinationResult,
    EarlyStopConfig,
    SweepResult,
    expand_grid,
    sample_random,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest
from src.backtesting.strategy_registry import resolve_strategy


logger = logging.getLogger(__name__)


Sampler = Literal["grid", "random", "optuna"]


# --- ParamSpace -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParamSpace:
    """Per-strategy explicit value lists.

    YAML format::

        name: ma_crossover
        values:
          fast_period: [3, 5, 7, 10, 14]
          slow_period: [20, 30, 40, 50, 60]

    Lists are explicit (no continuous bounds) so the same spec drives
    grid, random, and Optuna samplers without surprise mismatches.
    """

    name: str
    values: dict[str, list[Any]]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ParamSpace.name must be non-empty")
        for key, vals in self.values.items():
            if not isinstance(vals, list):
                raise ValueError(
                    f"ParamSpace.values[{key!r}] must be a list, "
                    f"got {type(vals).__name__}"
                )
            if not vals:
                raise ValueError(
                    f"ParamSpace.values[{key!r}] is empty — at least "
                    "one candidate value is required"
                )

    def cartesian_size(self) -> int:
        size = 1
        for vals in self.values.values():
            size *= len(vals)
        return size

    @classmethod
    def from_yaml(cls, path: str | Path) -> ParamSpace:
        """Parse a YAML param-space file.

        Raises :class:`ValueError` for both YAML parse errors and shape
        violations so the caller has one exception type to handle.
        """
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(
                f"ParamSpace YAML at {path!s} is malformed: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise ValueError(
                f"ParamSpace YAML must contain a mapping, got "
                f"{type(raw).__name__}"
            )
        return cls(
            name=str(raw.get("name", "")),
            values=dict(raw.get("values", {})),
        )


# --- Budget ----------------------------------------------------------


_DEFAULT_TRIAL_CAP = 200
_DEFAULT_MAX_DD_THRESHOLD = 10.0


@dataclass(frozen=True, slots=True)
class SweepBudget:
    """Trial budget envelope — Decision §3 cap.

    ``max_trials`` is the hard ceiling. Random search samples up to
    this many combos; grid search refuses to run when the Cartesian
    product exceeds it (the alternative — silent truncation — would
    bias the search toward whichever combos happen to come first).
    """

    max_trials: int = _DEFAULT_TRIAL_CAP

    def __post_init__(self) -> None:
        if self.max_trials < 1:
            raise ValueError(
                f"SweepBudget.max_trials must be >= 1, got {self.max_trials}"
            )


class SweepCapExceededError(ValueError):
    """Grid search would exceed :attr:`SweepBudget.max_trials`."""


# --- Early-stop helper ------------------------------------------------


def _max_dd_metric(res: BacktestResult) -> float:
    """Read ``max_overall_dd_pct`` from a result; ``+inf`` when absent.

    A combo that produced no metrics either failed silently or never
    traded; promoting it as a "low DD" survivor would be misleading.
    Returning ``+inf`` makes ``> threshold`` always trip, so the combo
    is skip-recorded (status ``"early_stop"``) and stays visible in
    the report rather than ranked as a candidate.
    """
    if res.metrics is None:
        return float("inf")
    return float(res.metrics.drawdown.max_overall_dd_pct)


def _default_objective(res: BacktestResult) -> float:
    """Net PnL — local copy of ``parameter_sweep._default_objective``.

    Cross-module import of the underscore-prefixed original couples
    this harness to a private symbol. Inlining keeps the dependency
    surface explicit; the implementation is one line and unlikely to
    drift.
    """
    return float(res.final_balance - res.initial_balance)


def default_max_dd_early_stop(
    threshold_pct: float = _DEFAULT_MAX_DD_THRESHOLD,
) -> EarlyStopConfig:
    """Risk R3: skip-record any combo whose max DD exceeds ``threshold_pct``."""
    return EarlyStopConfig(
        metric_fn=_max_dd_metric,
        threshold=threshold_pct,
        mode="gt",
    )


# --- Runner protocol -------------------------------------------------


class RunnerCallable(Protocol):
    def __call__(
        self,
        job: BacktestJobConfig,
        *,
        strategy_overrides: dict | None = None,
    ) -> BacktestResult:
        ...


# --- Public API -------------------------------------------------------


def run_parameter_sweep(
    *,
    spec: StrategySpec,
    manifest: DatasetManifest,
    window_name: str,
    venue: VenueSpec,
    param_space: ParamSpace,
    budget: SweepBudget | None = None,
    sampler: Sampler = "random",
    seed: int = 42,
    prop_firm: PropFirmSpec | None = None,
    runner: RunnerCallable | None = None,
    early_stop: EarlyStopConfig | None = None,
) -> SweepResult:
    """Dispatch one backtest per param combo against ``window_name``.

    ``sampler`` selects combo generation:

    * ``"grid"`` — full Cartesian; raises :class:`SweepCapExceededError`
      when the product exceeds ``budget.max_trials``.
    * ``"random"`` — :func:`sample_random` with the configured seed,
      capped at ``min(cartesian_size, budget.max_trials)``.
    * ``"optuna"`` — TPE sampler (lazy-imported); raises
      :class:`RuntimeError` when ``optuna`` is unavailable, with a
      message pointing at the random fallback.

    Each combo dispatches via ``runner`` (defaults to
    :func:`run_backtest`). Early-stop defaults to
    :func:`default_max_dd_early_stop` (Risk R3) — pass
    ``early_stop`` explicitly to override or ``EarlyStopConfig(...)``
    pre-built.

    .. note::
        The harness is sequential. 12.7 will reuse the existing
        :class:`ParameterSweep`'s ``ProcessPoolExecutor`` path; at
        that point a custom ``early_stop.metric_fn`` MUST be a
        module-level function (lambdas and closures are not
        picklable across worker processes).
    """
    bgt = budget or SweepBudget()
    es = early_stop if early_stop is not None else default_max_dd_early_stop()
    dispatch: RunnerCallable = runner or run_backtest

    resolve_strategy(spec.name)
    entry = _first_entry_for_window(manifest, window_name)
    base_job = _build_base_job(
        spec=spec,
        manifest=manifest,
        entry=entry,
        venue=venue,
        prop_firm=prop_firm,
    )

    combos = _generate_combos(
        sampler=sampler,
        param_space=param_space,
        budget=bgt,
        seed=seed,
    )
    logger.info(
        "sweep dispatch strategy=%s sampler=%s combos=%d cap=%d",
        spec.name, sampler, len(combos), bgt.max_trials,
    )

    results = [
        _run_one(
            params=params,
            base_job=base_job,
            dispatch=dispatch,
            early_stop=es,
        )
        for params in combos
    ]
    return SweepResult(combos=results, ranked_by="score")


# --- Render ----------------------------------------------------------


def render_sweep_section(
    strategy_label: str,
    sweep: SweepResult,
    *,
    top_n: int = 5,
) -> str:
    """Markdown section: top-N OK combos + status counts footer."""
    label = _sanitise_cell(strategy_label)
    if not sweep.combos:
        return (
            f"## Parameter sweep — `{label}`\n\n"
            "_no combos in sweep result._\n"
        )

    ok = [c for c in sweep.combos if c.status == "ok"]
    early = [c for c in sweep.combos if c.status == "early_stop"]
    failed = [c for c in sweep.combos if c.status == "failed"]

    ranked = sweep.ranked()[:top_n]

    lines = [f"## Parameter sweep — `{label}`", ""]
    if ranked:
        lines.append("| Rank | Score | Params |")
        lines.append("|---|---|---|")
        for idx, combo in enumerate(ranked, start=1):
            lines.append(
                f"| {idx} | {combo.score:.2f} | "
                f"{_sanitise_cell(str(combo.params))} |"
            )
    else:
        lines.append("_no successful combos in this sweep._")

    lines.append("")
    lines.append(
        f"_Status: ok={len(ok)}, early_stop (skip-record)={len(early)}, "
        f"failed={len(failed)} (total {len(sweep.combos)})._"
    )
    return "\n".join(lines)


# --- Internals --------------------------------------------------------


def _first_entry_for_window(
    manifest: DatasetManifest, window_name: str
) -> DatasetEntry:
    for entry in manifest.entries:
        if entry.window_name == window_name:
            return entry
    available = sorted({e.window_name for e in manifest.entries})
    raise KeyError(
        f"manifest has no entries for window={window_name!r}. "
        f"Available: {available}"
    )


def _build_base_job(
    *,
    spec: StrategySpec,
    manifest: DatasetManifest,
    entry: DatasetEntry,
    venue: VenueSpec,
    prop_firm: PropFirmSpec | None,
) -> BacktestJobConfig:
    """Construct the job once; combos vary via ``strategy_overrides``."""
    return BacktestJobConfig(
        strategy=spec.name,
        strategy_params=dict(spec.params),
        venue=venue,
        instrument_symbol=manifest.symbol,
        bar_type_suffix=spec.bar_type_suffix,
        data=ParquetDataSpec(path=entry.parquet_path),
        prop_firm=prop_firm,
        start=entry.start,
        end=entry.end,
    )


def _generate_combos(
    *,
    sampler: Sampler,
    param_space: ParamSpace,
    budget: SweepBudget,
    seed: int,
) -> list[dict[str, Any]]:
    if sampler == "grid":
        size = param_space.cartesian_size()
        if size > budget.max_trials:
            raise SweepCapExceededError(
                f"grid Cartesian size {size} exceeds budget "
                f"{budget.max_trials}; switch sampler to 'random' "
                "to sample within the cap, or shrink param_space"
            )
        return expand_grid(param_space.values)
    if sampler == "random":
        n = min(param_space.cartesian_size(), budget.max_trials)
        return sample_random(param_space.values, n_iter=n, seed=seed)
    if sampler == "optuna":
        return _optuna_combos(
            param_space=param_space, budget=budget, seed=seed
        )
    raise ValueError(
        f"Unknown sampler {sampler!r}; choose 'grid' / 'random' / 'optuna'"
    )


def _optuna_combos(
    *,
    param_space: ParamSpace,
    budget: SweepBudget,
    seed: int,
) -> list[dict[str, Any]]:
    """Return ``budget.max_trials`` combos sampled by Optuna's TPE.

    Lazy import: Optuna is not in the trading-engine deps yet. When
    missing we raise a clear :class:`RuntimeError` pointing to the
    random fallback so the caller doesn't need to know about the
    optional dep.
    """
    try:
        import optuna  # noqa: PLC0415 — lazy
    except ImportError as exc:
        raise RuntimeError(
            "Optuna sampler requested but the 'optuna' package is not "
            "installed. Install with `uv add optuna` or use sampler='random' "
            "(see Decision §3 in docs/epic-12-context.md)."
        ) from exc

    sampler_obj = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler_obj)

    combos: list[dict[str, Any]] = []
    keys = list(param_space.values.keys())

    def objective(trial: Any) -> float:
        params = {
            key: trial.suggest_categorical(key, param_space.values[key])
            for key in keys
        }
        combos.append(params)
        # Scoring is deferred to ``_run_one``; the constant 0.0 means
        # TPE has no observations to fit, so it falls back to its
        # random-exploration prior for the full ``n_trials``. That is
        # acceptable here because we only need ``n`` distinct combos
        # — any signal from the actual backtest scores would require
        # iterating optimize+_run_one inline, which 12.6 explicitly
        # defers to 12.7's nested-walk-forward composition.
        return 0.0

    n = min(param_space.cartesian_size(), budget.max_trials)
    study.optimize(objective, n_trials=n, show_progress_bar=False)
    return combos


def _run_one(
    *,
    params: dict[str, Any],
    base_job: BacktestJobConfig,
    dispatch: RunnerCallable,
    early_stop: EarlyStopConfig,
) -> CombinationResult:
    try:
        result = dispatch(base_job, strategy_overrides=params)
    except MemoryError:
        # Cascading OOM in subsequent combos hides the real cause.
        raise
    except Exception as exc:  # noqa: BLE001 — combo isolation
        logger.warning(
            "sweep combo %s failed: %s", params, exc, exc_info=True
        )
        return CombinationResult(
            params=params,
            status="failed",
            result=None,
            score=float("-inf"),
            error=str(exc),
        )

    if early_stop.should_stop(result):
        return CombinationResult(
            params=params,
            status="early_stop",
            result=result,
            score=float("-inf"),
        )
    score = float(_default_objective(result))
    if not math.isfinite(score):
        # NaN/inf score would corrupt the ranking — record as failed.
        return CombinationResult(
            params=params,
            status="failed",
            result=result,
            score=float("-inf"),
            error=f"objective returned non-finite score {score}",
        )
    return CombinationResult(
        params=params,
        status="ok",
        result=result,
        score=score,
    )


def _sanitise_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", "").replace("\n", " ")
