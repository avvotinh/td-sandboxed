"""Materialisation receipt for a dataset spec.

The :class:`DatasetManifest` is what the pipeline writes after
materialising every (timeframe, window) combination. It is purely
factual — symbol, fingerprints, parquet paths, gaps detected — and is
the artefact stamped into ``BacktestResult.config_snapshot`` so
validation reports cite a fingerprint anyone can re-verify.

JSON is the on-disk format: machine-generated, easy to diff in code
review, and trivial to round-trip through ``json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.spec import WindowKind


_MANIFEST_SCHEMA_VERSION = "1"


def _isoformat(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"datetime must be tz-aware, got {value!r}")
    return parsed.astimezone(UTC)


def _safe_parquet_path(raw: Any) -> Path:
    """Reject deserialised parquet paths that try to escape via ``..``.

    The manifest is machine-generated so a clean re-load should always
    produce a normal path; ``..`` segments only appear if the JSON has
    been hand-edited or copied between machines with different cache
    roots. Refusing here forces the caller to re-derive the path via
    :meth:`ParquetBarLoader.path_for` rather than trusting the value.
    """
    candidate = Path(str(raw))
    if any(part == ".." for part in candidate.parts):
        raise ValueError(
            f"Refusing parquet_path containing '..' traversal: {raw!r}"
        )
    return candidate


@dataclass(frozen=True, slots=True)
class BarGap:
    """A run of consecutive timestamps where the next bar is missing.

    ``before`` is the last present timestamp; ``after`` is the next
    present timestamp. ``duration_hours`` is ``after - before`` in
    hours, including the expected bar interval (so a single missing
    M5 bar reports ~0.083h, not 0).
    """

    timeframe: str
    window_name: str
    before: datetime
    after: datetime

    @property
    def duration_hours(self) -> float:
        return (self.after - self.before).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "window_name": self.window_name,
            "before": _isoformat(self.before),
            "after": _isoformat(self.after),
            "duration_hours": self.duration_hours,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BarGap:
        return cls(
            timeframe=str(raw["timeframe"]),
            window_name=str(raw["window_name"]),
            before=_parse_iso(raw["before"]),
            after=_parse_iso(raw["after"]),
        )


@dataclass(frozen=True, slots=True)
class DatasetEntry:
    """One materialised Parquet shard."""

    timeframe: str
    window_name: str
    window_kind: WindowKind
    start: datetime
    end: datetime
    parquet_path: Path
    fingerprint: ContentHashFingerprint
    row_count: int
    gaps: tuple[BarGap, ...] = field(default_factory=tuple)

    @property
    def fingerprint_short(self) -> str:
        return self.fingerprint.sha256()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "window_name": self.window_name,
            "window_kind": self.window_kind.value,
            "start": _isoformat(self.start),
            "end": _isoformat(self.end),
            "parquet_path": str(self.parquet_path),
            "fingerprint": {
                "min_ts": self.fingerprint.min_ts,
                "max_ts": self.fingerprint.max_ts,
                "row_count": self.fingerprint.row_count,
                "sha256_short": self.fingerprint.sha256(),
            },
            "row_count": self.row_count,
            "gaps": [g.to_dict() for g in self.gaps],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DatasetEntry:
        fp_raw = raw["fingerprint"]
        return cls(
            timeframe=str(raw["timeframe"]),
            window_name=str(raw["window_name"]),
            window_kind=WindowKind(raw["window_kind"]),
            start=_parse_iso(raw["start"]),
            end=_parse_iso(raw["end"]),
            parquet_path=_safe_parquet_path(raw["parquet_path"]),
            fingerprint=ContentHashFingerprint(
                min_ts=int(fp_raw["min_ts"]),
                max_ts=int(fp_raw["max_ts"]),
                row_count=int(fp_raw["row_count"]),
            ),
            row_count=int(raw["row_count"]),
            gaps=tuple(BarGap.from_dict(g) for g in raw.get("gaps", [])),
        )


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    """Materialisation result — one record of every shard the pipeline wrote."""

    spec_name: str
    dataset_version: str
    symbol: str
    generated_at: datetime
    max_gap_hours: float
    entries: tuple[DatasetEntry, ...]

    @property
    def total_rows(self) -> int:
        return sum(e.row_count for e in self.entries)

    @property
    def gap_count(self) -> int:
        return sum(len(e.gaps) for e in self.entries)

    def entries_for_window(self, window_name: str) -> tuple[DatasetEntry, ...]:
        return tuple(e for e in self.entries if e.window_name == window_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "spec_name": self.spec_name,
            "dataset_version": self.dataset_version,
            "symbol": self.symbol,
            "generated_at": _isoformat(self.generated_at),
            "max_gap_hours": self.max_gap_hours,
            "entries": [e.to_dict() for e in self.entries],
        }

    def save_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))
        return target

    @classmethod
    def load_json(cls, path: str | Path) -> DatasetManifest:
        raw = json.loads(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(
                f"Manifest JSON must contain a mapping, got {type(raw).__name__}"
            )
        schema = raw.get("schema_version")
        if schema != _MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported manifest schema_version {schema!r}; "
                f"expected {_MANIFEST_SCHEMA_VERSION!r}"
            )
        return cls(
            spec_name=str(raw["spec_name"]),
            dataset_version=str(raw["dataset_version"]),
            symbol=str(raw["symbol"]),
            generated_at=_parse_iso(raw["generated_at"]),
            max_gap_hours=float(raw["max_gap_hours"]),
            entries=tuple(DatasetEntry.from_dict(e) for e in raw["entries"]),
        )
