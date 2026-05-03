"""In-sample baseline harness — Epic 12 Story 12.2.

Wraps :func:`src.backtesting.runner_facade.run_backtest` so the
validation campaign can run N strategies against a single dataset
window with **identical venue, fee, and seed**. Each strategy gets a
:class:`BacktestJobConfig` whose ``data`` field points at the Parquet
shard recorded in :class:`DatasetManifest`, ensuring every backtest in
the campaign reads the same bytes.

The returned :class:`BacktestResult` instances carry a populated
``config_snapshot`` (Decision §7 in ``docs/epic-12-context.md``):
dataset fingerprint, strategy params, venue settings, and the baseline
flag ``regime_classifier_enabled: False`` (Decision §5). 12.3 consumes
the snapshot when rendering the comparison report.

Sequential runner — parallelism is the job of 12.6/12.7.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

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


logger = logging.getLogger(__name__)


# Mapping MetaTrader-style timeframe → Nautilus bar-type suffix.
# Last-trade external bars match the live data feed (Redis ``bars:*``
# channels republish broker last-trade ticks aggregated into bars).
_TIMEFRAME_BAR_SUFFIX: dict[str, str] = {
    "M1": "1-MINUTE-LAST-EXTERNAL",
    "M5": "5-MINUTE-LAST-EXTERNAL",
    "M15": "15-MINUTE-LAST-EXTERNAL",
    "M30": "30-MINUTE-LAST-EXTERNAL",
    "H1": "1-HOUR-LAST-EXTERNAL",
    "H4": "4-HOUR-LAST-EXTERNAL",
    "D1": "1-DAY-LAST-EXTERNAL",
}


_JSON_PRIMITIVE_TYPES: tuple[type, ...] = (int, float, str, bool, type(None))


def _check_json_primitive_params(
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that every param value is JSON-primitive; return a fresh dict.

    The comparison report writer (12.3) dumps the snapshot via
    ``json.dumps``. A ``Decimal`` / ``Path`` / ``datetime`` here would
    blow up there with a confusing ``TypeError``; failing fast at spec
    construction lets the caller see the offending key immediately.
    """
    out: dict[str, Any] = {}
    for key, value in params.items():
        if not isinstance(value, _JSON_PRIMITIVE_TYPES):
            raise TypeError(
                f"StrategySpec.params[{key!r}] value of type "
                f"{type(value).__name__} is not JSON-primitive. "
                "Use int/float/str/bool/None — Decimal/Path/datetime "
                "must be stringified by the caller."
            )
        out[key] = value
    return out


def timeframe_to_bar_suffix(timeframe: str) -> str:
    """Translate a timeframe code to the Nautilus bar-type suffix.

    Raises ``ValueError`` for anything outside the explicit allowlist —
    a guess here would silently mismatch the dataset shard with the
    strategy's bar subscription.
    """
    try:
        return _TIMEFRAME_BAR_SUFFIX[timeframe]
    except KeyError as exc:
        known = ", ".join(sorted(_TIMEFRAME_BAR_SUFFIX))
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}. Known: {known}"
        ) from exc


class UnknownDatasetEntryError(KeyError):
    """No manifest entry matches the requested (window, timeframe)."""


# Type alias — mirrors :func:`run_backtest`'s positional+kwarg signature.
RunnerCallable = Callable[..., BacktestResult]


@dataclass(frozen=True, slots=True)
class StrategySpec:
    """One strategy invocation in a baseline run.

    ``params`` is normalised in :meth:`__post_init__` into a read-only
    view (``types.MappingProxyType``) over a fresh copy, so a caller
    that holds the original dict can no longer mutate it through the
    spec. Param values must be JSON-primitive — :func:`run_baseline`
    serialises them into ``BacktestResult.config_snapshot`` and the
    comparison report writer (12.3) dumps that to JSON.

    Attributes:
        name: Backtest registry key (must resolve via
            :func:`resolve_strategy`).
        timeframe: MetaTrader-style timeframe (``"M5"``, ``"M15"`` …)
            used both to select the Parquet shard and to build the
            Nautilus bar-type suffix.
        bar_type_suffix: Nautilus bar-type suffix; pass via
            :func:`timeframe_to_bar_suffix` unless overriding for
            BID/ASK variants.
        params: Strategy params (read-only after construction). Values
            must be JSON-primitive (``int``/``float``/``str``/``bool``/
            ``None``) or stringifiable; non-primitive values raise.
        label: Optional display label that 12.3 + 12.7 use as a row
            key. Defaults to ``name`` when omitted; must be unique
            within a :class:`BaselineConfig`.
    """

    name: str
    timeframe: str
    bar_type_suffix: str
    params: Mapping[str, Any] = field(default_factory=dict)
    label: str | None = None

    def __post_init__(self) -> None:
        normalised = _check_json_primitive_params(self.params)
        # frozen=True blocks plain assignment; ``object.__setattr__`` is
        # the documented escape-hatch for ``__post_init__`` normalisation.
        object.__setattr__(
            self, "params", MappingProxyType(normalised)
        )

    @property
    def display_label(self) -> str:
        return self.label or self.name


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """Single in-sample baseline run."""

    run_label: str
    manifest: DatasetManifest
    window_name: str
    venue: VenueSpec
    strategies: tuple[StrategySpec, ...]
    prop_firm: PropFirmSpec | None = None

    def __post_init__(self) -> None:
        labels = [s.display_label for s in self.strategies]
        if len(set(labels)) != len(labels):
            raise ValueError(
                f"duplicate strategy labels in baseline config: {labels}"
            )


def run_baseline(
    config: BaselineConfig,
    *,
    runner: RunnerCallable | None = None,
) -> list[BacktestResult]:
    """Dispatch one backtest per strategy spec; stamp ``config_snapshot``.

    Sequential execution. Any exception from ``runner`` aborts the run
    and propagates to the caller — the partially-collected list is
    discarded, so a returned list is always exactly ``len(config.strategies)``
    entries long. Parallelism + per-strategy error isolation are the
    responsibility of 12.6/12.7.

    Args:
        config: Immutable baseline-run description.
        runner: Override for :func:`run_backtest` — primarily for tests
            that want to capture jobs without spinning up Nautilus.

    Returns:
        Results in the same order as ``config.strategies``. The
        ``config_snapshot`` field on each is populated with dataset +
        strategy + venue metadata for the comparison report.
    """
    dispatch: RunnerCallable = runner or run_backtest

    entry_index = _index_manifest(config.manifest)
    results: list[BacktestResult] = []
    for spec in config.strategies:
        entry = _lookup_entry(
            entry_index,
            window_name=config.window_name,
            timeframe=spec.timeframe,
        )
        job = _build_job(spec=spec, entry=entry, config=config)
        logger.info(
            "baseline.dispatch run_label=%s strategy=%s timeframe=%s "
            "window=%s parquet=%s",
            config.run_label,
            spec.name,
            spec.timeframe,
            config.window_name,
            entry.parquet_path,
        )
        result = dispatch(job)
        snapshot = _build_config_snapshot(
            spec=spec, entry=entry, config=config
        )
        results.append(dataclasses.replace(result, config_snapshot=snapshot))
    return results


# --- Internals --------------------------------------------------------


def _index_manifest(
    manifest: DatasetManifest,
) -> dict[tuple[str, str], DatasetEntry]:
    """Index entries by ``(window_name, timeframe)`` for O(1) lookup."""
    return {(e.window_name, e.timeframe): e for e in manifest.entries}


def _lookup_entry(
    index: dict[tuple[str, str], DatasetEntry],
    *,
    window_name: str,
    timeframe: str,
) -> DatasetEntry:
    try:
        return index[(window_name, timeframe)]
    except KeyError as exc:
        available = sorted(f"{w}/{tf}" for (w, tf) in index)
        raise UnknownDatasetEntryError(
            f"Manifest has no entry for window={window_name!r} "
            f"timeframe={timeframe!r}. Available: {available}"
        ) from exc


def _build_job(
    *,
    spec: StrategySpec,
    entry: DatasetEntry,
    config: BaselineConfig,
) -> BacktestJobConfig:
    # Resolve eagerly so an unknown strategy fails before we try to
    # read the Parquet — the BacktestJobConfig validator does this too,
    # but raising here gives the clearer call-site message.
    resolve_strategy(spec.name)
    return BacktestJobConfig(
        strategy=spec.name,
        strategy_params=dict(spec.params),
        venue=config.venue,
        instrument_symbol=config.manifest.symbol,
        bar_type_suffix=spec.bar_type_suffix,
        data=ParquetDataSpec(path=entry.parquet_path),
        prop_firm=config.prop_firm,
        start=entry.start,
        end=entry.end,
    )


def _build_config_snapshot(
    *,
    spec: StrategySpec,
    entry: DatasetEntry,
    config: BaselineConfig,
) -> dict[str, Any]:
    """Reproducibility metadata stamped into ``BacktestResult.config_snapshot``.

    Decimal values are stringified so the snapshot is JSON-serialisable
    end-to-end (the comparison report writer dumps it directly).
    """
    return {
        "run_label": config.run_label,
        "dataset": {
            "spec_name": config.manifest.spec_name,
            "dataset_version": config.manifest.dataset_version,
            "symbol": config.manifest.symbol,
            "timeframe": entry.timeframe,
            "window_name": entry.window_name,
            "window_kind": entry.window_kind.value,
            "fingerprint": {
                "min_ts": entry.fingerprint.min_ts,
                "max_ts": entry.fingerprint.max_ts,
                "row_count": entry.fingerprint.row_count,
                "sha256_short": entry.fingerprint.sha256(),
            },
            "row_count": entry.row_count,
        },
        "strategy": {
            "name": spec.name,
            "label": spec.display_label,
            "timeframe": spec.timeframe,
            "bar_type_suffix": spec.bar_type_suffix,
            "params": dict(spec.params),
        },
        "venue": {
            "name": config.venue.name,
            "starting_balance": str(config.venue.starting_balance),
            "currency": config.venue.currency,
            "commission_per_lot_usd": str(config.venue.commission_per_lot_usd),
        },
        "prop_firm": (
            None
            if config.prop_firm is None
            else {
                "preset_path": str(config.prop_firm.preset_path),
                "account_id": config.prop_firm.account_id,
            }
        ),
        "regime_classifier_enabled": False,
    }
