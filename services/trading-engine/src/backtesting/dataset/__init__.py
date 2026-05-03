"""Dataset pipeline for Epic 12 backtest validation.

Pins canonical (symbol, timeframe, window) combinations to Parquet
shards under :mod:`src.backtesting.data_loader` cache and produces a
:class:`DatasetManifest` carrying fingerprints + gap report. Downstream
stories (12.2 baseline harness, 12.7 parameter sweep) consume the
manifest to ensure every backtest in the validation campaign sees an
identical dataset.
"""

from src.backtesting.dataset.baseline_harness import (
    BaselineConfig,
    StrategySpec,
    UnknownDatasetEntryError,
    run_baseline,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.comparison_report import (
    BaselineFilter,
    FilterVerdict,
    FingerprintMismatchError,
    evaluate_filter,
    render_comparison_report,
)
from src.backtesting.dataset.compliance import (
    BreachSummary,
    ComplianceBreachError,
    ComplianceProfile,
    assert_no_breaches,
    build_compliance_rule_engine,
    summarize_breaches,
)
from src.backtesting.dataset.manifest import (
    BarGap,
    DatasetEntry,
    DatasetManifest,
)
from src.backtesting.dataset.pipeline import (
    BarSourceProtocol,
    DatasetPipeline,
    detect_gaps,
    timeframe_to_seconds,
)
from src.backtesting.dataset.spec import (
    DatasetSpec,
    WindowKind,
    WindowSpec,
)


__all__ = [
    "BarGap",
    "BarSourceProtocol",
    "BaselineConfig",
    "BaselineFilter",
    "BreachSummary",
    "ComplianceBreachError",
    "ComplianceProfile",
    "DatasetEntry",
    "DatasetManifest",
    "DatasetPipeline",
    "DatasetSpec",
    "FilterVerdict",
    "FingerprintMismatchError",
    "StrategySpec",
    "UnknownDatasetEntryError",
    "WindowKind",
    "WindowSpec",
    "assert_no_breaches",
    "build_compliance_rule_engine",
    "detect_gaps",
    "evaluate_filter",
    "render_comparison_report",
    "run_baseline",
    "summarize_breaches",
    "timeframe_to_bar_suffix",
    "timeframe_to_seconds",
]
