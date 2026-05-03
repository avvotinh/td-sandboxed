"""Walk-forward harness — Epic 12 Story 12.5.

Layers manifest-driven fold generation, fixed-params per-fold dispatch,
OOS aggregation, and the Decision §4 ratio threshold check on top of
the existing :mod:`src.backtesting.walk_forward` primitives.

12.5's responsibilities:
1. Produce :class:`FoldSpec` lists from a :class:`DatasetManifest`
   window — train 6m / test 1m / step 1m default (Decision §4).
2. Drive per-fold OOS evaluation with **fixed strategy params** so a
   strategy's robustness across regimes can be checked before
   investing parameter-sweep budget. 12.6/12.7 swap this driver for
   the train+sweep+test version.
3. Aggregate OOS metrics across folds — :class:`OOSAggregate` with
   mean / std OOS sharpe + supporting stats; isolated fold failures
   don't crash the aggregate.
4. Apply the OOS acceptance threshold from Decision §4
   (``mean(OOS sharpe) ≥ 0.7 × IS sharpe`` AND
   ``std/mean ≤ 0.5``) and render a markdown section the
   validation report can paste into ``epic-12-validation-report.md``.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from src.backtesting.dataset.baseline_harness import StrategySpec
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    PropFirmSpec,
    VenueSpec,
)
from src.backtesting.result import BacktestResult
from src.backtesting.runner_facade import run_backtest
from src.backtesting.strategy_registry import resolve_strategy
from src.backtesting.walk_forward import (
    FoldSpec,
    WalkForwardFolds,
    WalkForwardMode,
)


logger = logging.getLogger(__name__)


_VALID_MODES: frozenset[str] = frozenset({"anchored", "rolling"})


@dataclass(frozen=True, slots=True)
class FoldGenerationConfig:
    """Walk-forward window sizing — Decision §4 defaults.

    The defaults intentionally use 30-day approximations so a 2-year
    in-sample window yields ~18 non-overlapping test slices. Callers
    that need calendar-month precision can override the timedeltas.
    """

    train_window: timedelta = timedelta(days=6 * 30)
    test_window: timedelta = timedelta(days=30)
    step: timedelta = timedelta(days=30)
    mode: WalkForwardMode = "rolling"

    def __post_init__(self) -> None:
        if self.train_window <= timedelta(0):
            raise ValueError(
                f"train_window must be positive, got {self.train_window}"
            )
        if self.test_window <= timedelta(0):
            raise ValueError(
                f"test_window must be positive, got {self.test_window}"
            )
        if self.step <= timedelta(0):
            raise ValueError(f"step must be positive, got {self.step}")
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_VALID_MODES)}, got {self.mode!r}"
            )


def generate_folds_from_manifest(
    manifest: DatasetManifest,
    *,
    window_name: str,
    config: FoldGenerationConfig | None = None,
) -> tuple[FoldSpec, ...]:
    """Build the fold list from a named window in ``manifest``.

    All entries for a given window share boundaries (``start`` /
    ``end`` come from the dataset spec, not the timeframe), so picking
    the first matching entry is sufficient.

    Raises:
        KeyError: ``window_name`` does not appear in the manifest.
    """
    cfg = config or FoldGenerationConfig()
    entry = _first_entry_for_window(manifest, window_name)
    return tuple(
        WalkForwardFolds.generate(
            total_start=entry.start,
            total_end=entry.end,
            train_window=cfg.train_window,
            test_window=cfg.test_window,
            step=cfg.step,
            mode=cfg.mode,
        )
    )


@dataclass(frozen=True, slots=True)
class FoldOutcome:
    """Per-fold OOS run result.

    ``oos_result`` is ``None`` and ``error`` carries a short message
    when the runner raised; the harness isolates so a single bad fold
    cannot abort the campaign.
    """

    fold: FoldSpec
    fold_index: int
    oos_result: BacktestResult | None
    error: str | None


@dataclass(frozen=True, slots=True)
class WalkForwardOutcome:
    """Aggregate per-strategy walk-forward output."""

    label: str
    fold_outcomes: tuple[FoldOutcome, ...]


class RunnerCallable(Protocol):
    """Structural type matching :func:`run_backtest`.

    Tighter than ``Callable[..., BacktestResult]`` so a fake runner
    that takes the wrong arg type is caught by static analysis.
    """

    def __call__(
        self,
        job: BacktestJobConfig,
        *,
        strategy_overrides: dict | None = None,
    ) -> BacktestResult:
        ...


def run_walk_forward_fixed_params(
    *,
    spec: StrategySpec,
    manifest: DatasetManifest,
    window_name: str,
    venue: VenueSpec,
    fold_config: FoldGenerationConfig | None = None,
    prop_firm: PropFirmSpec | None = None,
    runner: RunnerCallable | None = None,
) -> WalkForwardOutcome:
    """Run ``spec`` with FIXED params on every fold's test slice.

    The train slice is intentionally ignored here — 12.5 answers
    "do the default params hold up out-of-sample?", whereas
    12.6/12.7's sweep variant tunes per fold and tests the tuned
    params. Each fold's OOS run is wrapped in a try/except so an
    isolated crash records a :class:`FoldOutcome` with ``error`` set
    instead of aborting the run.
    """
    cfg = fold_config or FoldGenerationConfig()
    folds = generate_folds_from_manifest(
        manifest, window_name=window_name, config=cfg
    )
    entry = _first_entry_for_window(manifest, window_name)
    # Resolve eagerly — clearer error than the Pydantic validator.
    resolve_strategy(spec.name)

    dispatch: RunnerCallable = runner or run_backtest
    outcomes: list[FoldOutcome] = []
    for idx, fold in enumerate(folds):
        outcomes.append(
            _run_fold(
                idx=idx,
                fold=fold,
                spec=spec,
                manifest=manifest,
                entry=entry,
                venue=venue,
                prop_firm=prop_firm,
                dispatch=dispatch,
            )
        )
    return WalkForwardOutcome(
        label=spec.display_label,
        fold_outcomes=tuple(outcomes),
    )


# --- Aggregation ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OOSAggregate:
    """Aggregated OOS metrics across folds for one strategy.

    All ``mean_*`` fields use ``float("nan")`` as the "no data" sentinel
    when ``n_folds_with_metrics == 0``; consumers must check
    ``math.isnan`` (or ``n_folds_with_metrics``) before plotting/reporting.
    """

    label: str
    n_folds: int
    n_folds_with_metrics: int
    mean_oos_sharpe: float
    std_oos_sharpe: float
    mean_oos_max_dd_pct: float
    # ``float`` (not ``int``) so the NaN sentinel can mark "no data" —
    # an int 0 would silently look like a degenerate strategy that ran.
    mean_oos_trades: float
    total_oos_trades: int
    mean_oos_profit_factor: float
    mean_oos_win_rate: float


def aggregate_oos(outcome: WalkForwardOutcome) -> OOSAggregate:
    """Collapse fold outcomes into mean/std OOS stats."""
    n_folds = len(outcome.fold_outcomes)

    sharpes: list[float] = []
    max_dds: list[float] = []
    trades: list[int] = []
    pfs: list[float] = []
    wins: list[float] = []

    for fc in outcome.fold_outcomes:
        if fc.oos_result is None or fc.oos_result.metrics is None:
            continue
        m = fc.oos_result.metrics
        sharpes.append(m.risk.sharpe_ratio)
        max_dds.append(m.drawdown.max_overall_dd_pct)
        trades.append(m.trades.total_trades)
        pfs.append(m.pnl.profit_factor)
        wins.append(m.trades.win_rate)

    n_with = len(sharpes)
    return OOSAggregate(
        label=outcome.label,
        n_folds=n_folds,
        n_folds_with_metrics=n_with,
        mean_oos_sharpe=_mean_or_nan(sharpes),
        # Population stdev — folds are exhaustive, not a sample.
        std_oos_sharpe=_pstdev_or_nan(sharpes),
        mean_oos_max_dd_pct=_mean_or_nan(max_dds),
        mean_oos_trades=_mean_or_nan(trades),
        total_oos_trades=sum(trades),
        mean_oos_profit_factor=_mean_or_nan(pfs),
        mean_oos_win_rate=_mean_or_nan(wins),
    )


# --- OOS acceptance --------------------------------------------------


_MIN_FOLDS_FOR_STABILITY = 3


@dataclass(frozen=True, slots=True)
class OOSAcceptance:
    """Decision §4 OOS acceptance thresholds.

    ``oos_to_is_sharpe_ratio_min``: minimum ``mean(OOS sharpe) /
    IS sharpe`` ratio. ``oos_sharpe_cv_max``: maximum
    ``std(OOS sharpe) / mean(OOS sharpe)`` (coefficient of variation).
    ``min_folds_for_stability``: minimum fold count for the CV check
    to be meaningful (with one fold ``pstdev`` is 0 by definition,
    silently passing).
    """

    oos_to_is_sharpe_ratio_min: float = 0.7
    oos_sharpe_cv_max: float = 0.5
    min_folds_for_stability: int = _MIN_FOLDS_FOR_STABILITY

    def __post_init__(self) -> None:
        if not math.isfinite(self.oos_to_is_sharpe_ratio_min) or (
            self.oos_to_is_sharpe_ratio_min <= 0
        ):
            raise ValueError(
                "oos_to_is_sharpe_ratio_min must be a positive finite number, "
                f"got {self.oos_to_is_sharpe_ratio_min}"
            )
        if not math.isfinite(self.oos_sharpe_cv_max) or self.oos_sharpe_cv_max <= 0:
            raise ValueError(
                "oos_sharpe_cv_max must be a positive finite number, "
                f"got {self.oos_sharpe_cv_max}"
            )
        if self.min_folds_for_stability < 1:
            raise ValueError(
                "min_folds_for_stability must be >= 1, "
                f"got {self.min_folds_for_stability}"
            )


@dataclass(frozen=True, slots=True)
class OOSVerdict:
    """Outcome of applying :class:`OOSAcceptance` to one aggregate."""

    passed: bool
    reasons: tuple[str, ...] = ()


def evaluate_oos(
    aggregate: OOSAggregate,
    *,
    is_sharpe: float,
    acceptance: OOSAcceptance | None = None,
) -> OOSVerdict:
    """Apply the Decision §4 acceptance check.

    Failing reasons accumulate so callers can render every gate that
    tripped, not just the first.
    """
    a = acceptance or OOSAcceptance()
    reasons: list[str] = []

    if aggregate.n_folds_with_metrics == 0:
        return OOSVerdict(
            passed=False,
            reasons=("no folds produced metrics — strategy did not run",),
        )

    if aggregate.n_folds_with_metrics < a.min_folds_for_stability:
        reasons.append(
            f"only {aggregate.n_folds_with_metrics} fold(s) produced "
            f"metrics; need ≥ {a.min_folds_for_stability} for a "
            "meaningful stability check"
        )

    mean_oos = aggregate.mean_oos_sharpe
    if not math.isfinite(mean_oos):
        return OOSVerdict(
            passed=False, reasons=("mean OOS sharpe is not finite",)
        )

    if not math.isfinite(is_sharpe) or is_sharpe <= 0:
        return OOSVerdict(
            passed=False,
            reasons=(
                f"IS sharpe must be positive finite, got {is_sharpe}; "
                "ratio undefined",
            ),
        )

    ratio = mean_oos / is_sharpe
    if ratio < a.oos_to_is_sharpe_ratio_min:
        reasons.append(
            f"OOS/IS ratio {ratio:.2f} < {a.oos_to_is_sharpe_ratio_min:.2f}"
        )

    # CV check is meaningful only with positive mean OOS sharpe; a
    # negative mean already makes ratio fail above.
    if mean_oos > 0:
        cv = aggregate.std_oos_sharpe / mean_oos
        if cv > a.oos_sharpe_cv_max:
            reasons.append(
                f"OOS sharpe CV {cv:.2f} > {a.oos_sharpe_cv_max:.2f} "
                "(stability)"
            )
    else:
        reasons.append(
            f"mean OOS sharpe {mean_oos:.2f} ≤ 0 — strategy lost OOS"
        )

    return OOSVerdict(passed=not reasons, reasons=tuple(reasons))


# --- Render -----------------------------------------------------------


def render_walk_forward_section(
    rows: Sequence[tuple[OOSAggregate, float]],
    *,
    acceptance: OOSAcceptance | None = None,
) -> str:
    """Render a markdown sub-section.

    ``rows`` is ``[(aggregate, is_sharpe), ...]`` so each strategy
    keeps its own IS reference for the ratio check.
    """
    a = acceptance or OOSAcceptance()
    if not rows:
        return (
            "## Walk-forward (OOS) summary\n\n"
            "_no walk-forward results — empty input._\n"
        )

    columns = (
        "Strategy",
        "Folds",
        "OOS Sharpe",
        "Std",
        "OOS/IS",
        "CV",
        "Max DD",
        "Trades",
        "Verdict",
    )
    lines = [
        "## Walk-forward (OOS) summary",
        "",
        (
            f"_Acceptance: OOS/IS ≥ {a.oos_to_is_sharpe_ratio_min:.2f}, "
            f"CV ≤ {a.oos_sharpe_cv_max:.2f}._"
        ),
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for agg, is_sharpe in rows:
        verdict = evaluate_oos(agg, is_sharpe=is_sharpe, acceptance=a)
        lines.append(_render_row(agg, is_sharpe, verdict))
    lines.append("")
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


def _run_fold(
    *,
    idx: int,
    fold: FoldSpec,
    spec: StrategySpec,
    manifest: DatasetManifest,
    entry: DatasetEntry,
    venue: VenueSpec,
    prop_firm: PropFirmSpec | None,
    dispatch: RunnerCallable,
) -> FoldOutcome:
    job = BacktestJobConfig(
        strategy=spec.name,
        strategy_params=dict(spec.params),
        venue=venue,
        instrument_symbol=manifest.symbol,
        bar_type_suffix=spec.bar_type_suffix,
        data=ParquetDataSpec(path=entry.parquet_path),
        prop_firm=prop_firm,
        start=fold.test_start,
        end=fold.test_end,
    )
    try:
        result = dispatch(job)
    except MemoryError:
        # OOM in one fold means the next fold will OOM too; cascading
        # logged failures hide the real problem. Let the runner abort
        # so the caller sees the real cause.
        raise
    except Exception as exc:  # noqa: BLE001 — fold isolation is the point
        logger.warning(
            "walk-forward fold %d crashed: %s", idx, exc, exc_info=True
        )
        return FoldOutcome(
            fold=fold, fold_index=idx, oos_result=None, error=str(exc)
        )
    return FoldOutcome(
        fold=fold, fold_index=idx, oos_result=result, error=None
    )


def _mean_or_nan(values: Sequence[float | int]) -> float:
    if not values:
        return float("nan")
    return statistics.fmean(values)


def _pstdev_or_nan(values: Sequence[float]) -> float:
    if len(values) < 2:
        return float("nan") if not values else 0.0
    return statistics.pstdev(values)


def _render_row(
    aggregate: OOSAggregate,
    is_sharpe: float,
    verdict: OOSVerdict,
) -> str:
    label = _sanitise_cell(aggregate.label)
    if aggregate.n_folds_with_metrics == 0:
        verdict_cell = "FAIL — no folds produced metrics"
        cells = (
            label,
            f"0/{aggregate.n_folds}",
            "—", "—", "—", "—", "—", "0",
            verdict_cell,
        )
        return "| " + " | ".join(cells) + " |"

    ratio = (
        aggregate.mean_oos_sharpe / is_sharpe
        if math.isfinite(is_sharpe) and is_sharpe > 0
        else float("nan")
    )
    cv = (
        aggregate.std_oos_sharpe / aggregate.mean_oos_sharpe
        if aggregate.mean_oos_sharpe > 0
        else float("nan")
    )
    verdict_cell = (
        "PASS" if verdict.passed
        else "FAIL — "
        + ", ".join(_sanitise_cell(r) for r in verdict.reasons)
    )
    cells = (
        label,
        f"{aggregate.n_folds_with_metrics}/{aggregate.n_folds}",
        _fmt(aggregate.mean_oos_sharpe),
        _fmt(aggregate.std_oos_sharpe),
        _fmt(ratio),
        _fmt(cv),
        f"{aggregate.mean_oos_max_dd_pct:.2f}%",
        f"{aggregate.total_oos_trades}",
        verdict_cell,
    )
    return "| " + " | ".join(cells) + " |"


def _fmt(value: float) -> str:
    return "—" if not math.isfinite(value) else f"{value:.2f}"


def _sanitise_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", "").replace("\n", " ")
