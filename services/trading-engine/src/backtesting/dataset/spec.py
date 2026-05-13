"""Declarative dataset spec — pins (symbol, timeframes, windows) for a campaign.

A :class:`DatasetSpec` is the single YAML-loadable description of the
validation dataset used by Epic 12. It enumerates:

* one symbol (whitelisted against the supported instruments),
* one or more timeframes (each safe to use as a Parquet path component),
* one or more windows, each tagged ``in_sample`` or ``oos_reserve``,
* the gap threshold above which a missing-bar stretch is flagged.

The spec is purely data — the ``DatasetPipeline`` materialises the
underlying Parquet shards and stamps fingerprints into a manifest. Any
change to the spec (window shift, dataset version bump) invalidates
downstream comparison reports because the manifest fingerprint changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.backtesting.data_cache import _SAFE_PATH_COMPONENT
from src.backtesting.job_config import _SUPPORTED_SYMBOLS


class WindowKind(StrEnum):
    """Classification of a dataset window.

    ``IN_SAMPLE`` windows feed Phase 12.A baseline + Phase 12.B
    walk-forward training. ``OOS_RESERVE`` windows are held out and only
    touched at the closing sanity check on picked params (see
    Decision §1 in ``docs/epic-12-context.md``).
    """

    IN_SAMPLE = "in_sample"
    OOS_RESERVE = "oos_reserve"


class _Frozen(BaseModel):
    """Shared immutability + extra=forbid config.

    Mirrors :class:`src.backtesting.job_config._Frozen` so dataset
    specs are pickle-safe across :class:`ProcessPoolExecutor` boundaries
    just like ``BacktestJobConfig``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class WindowSpec(_Frozen):
    """One contiguous time range within the dataset."""

    name: str = Field(..., min_length=1)
    kind: WindowKind
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _require_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError(
                "datetime must be timezone-aware (use UTC)"
            )
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def _check_range(self) -> WindowSpec:
        if self.end <= self.start:
            raise ValueError("end must be strictly after start")
        return self


class DatasetSpec(_Frozen):
    """Canonical dataset definition — symbol × timeframes × windows."""

    name: str = Field(..., min_length=1)
    description: str | None = None
    dataset_version: str = Field(..., min_length=1)
    symbol: str
    timeframes: tuple[str, ...] = Field(..., min_length=1)
    windows: tuple[WindowSpec, ...] = Field(..., min_length=1)
    max_gap_hours: float = Field(default=48.0, gt=0.0)

    @field_validator("symbol")
    @classmethod
    def _whitelist_symbol(cls, v: str) -> str:
        if v not in _SUPPORTED_SYMBOLS:
            known = ", ".join(sorted(_SUPPORTED_SYMBOLS))
            raise ValueError(f"Unsupported symbol {v!r}. Supported: {known}")
        return v

    @field_validator("timeframes")
    @classmethod
    def _validate_timeframes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for tf in v:
            if not tf or not _SAFE_PATH_COMPONENT.match(tf):
                raise ValueError(
                    f"Unsafe timeframe {tf!r}. "
                    f"Only [A-Za-z0-9._-] allowed."
                )
        if len(set(v)) != len(v):
            raise ValueError(f"duplicate timeframes are not allowed: {v}")
        return v

    @model_validator(mode="after")
    def _unique_window_names(self) -> DatasetSpec:
        names = [w.name for w in self.windows]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate window names: {names}")
        return self

    def iter_entries(self) -> Iterator[tuple[str, WindowSpec]]:
        """Yield every (timeframe, window) combination, in declaration order."""
        for tf in self.timeframes:
            for window in self.windows:
                yield tf, window

    @classmethod
    def from_yaml(cls, path: str | Path) -> DatasetSpec:
        """Load a spec from a YAML file.

        ``yaml.safe_load`` is used to refuse arbitrary Python tags.
        """
        raw: Any = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(
                f"Dataset YAML must contain a mapping, got {type(raw).__name__}"
            )
        return cls.model_validate(raw)
