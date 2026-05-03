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
from src.backtesting.dataset.sweep_harness import (
    ParamSpace,
    SweepBudget,
    SweepCapExceededError,
    default_max_dd_early_stop,
    render_sweep_section,
    run_parameter_sweep,
)
from src.backtesting.dataset.walk_forward_harness import (
    FoldGenerationConfig,
    FoldOutcome,
    OOSAcceptance,
    OOSAggregate,
    OOSVerdict,
    WalkForwardOutcome,
    aggregate_oos,
    evaluate_oos,
    generate_folds_from_manifest,
    render_walk_forward_section,
    run_walk_forward_fixed_params,
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
    "FoldGenerationConfig",
    "FoldOutcome",
    "OOSAcceptance",
    "OOSAggregate",
    "OOSVerdict",
    "ParamSpace",
    "StrategySpec",
    "SweepBudget",
    "SweepCapExceededError",
    "UnknownDatasetEntryError",
    "WalkForwardOutcome",
    "WindowKind",
    "WindowSpec",
    "aggregate_oos",
    "assert_no_breaches",
    "build_compliance_rule_engine",
    "default_max_dd_early_stop",
    "detect_gaps",
    "evaluate_filter",
    "evaluate_oos",
    "generate_folds_from_manifest",
    "render_comparison_report",
    "render_sweep_section",
    "render_walk_forward_section",
    "run_baseline",
    "run_parameter_sweep",
    "run_walk_forward_fixed_params",
    "summarize_breaches",
    "timeframe_to_bar_suffix",
    "timeframe_to_seconds",
]
