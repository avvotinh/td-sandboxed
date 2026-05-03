"""Dataset pipeline for Epic 12 backtest validation.

Pins canonical (symbol, timeframe, window) combinations to Parquet
shards under :mod:`src.backtesting.data_loader` cache and produces a
:class:`DatasetManifest` carrying fingerprints + gap report. Downstream
stories (12.2 baseline harness, 12.7 parameter sweep) consume the
manifest to ensure every backtest in the validation campaign sees an
identical dataset.
"""

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
    "DatasetEntry",
    "DatasetManifest",
    "DatasetPipeline",
    "DatasetSpec",
    "WindowKind",
    "WindowSpec",
    "detect_gaps",
    "timeframe_to_seconds",
]
