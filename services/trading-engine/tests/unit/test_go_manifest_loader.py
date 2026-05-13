"""Unit tests for ``src.backtesting.dataset.go_manifest_loader``.

Story 12.7.0d — covers the merge logic that combines per-shard
manifests written by the tv-api Go CLI into a single canonical
:class:`DatasetManifest`. No subprocess or network calls — every
fixture is hand-crafted JSON.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.backtesting.dataset.go_manifest_loader import merge_go_manifests
from src.backtesting.dataset.manifest import DatasetManifest


pytestmark = pytest.mark.unit


def _write_sidecar(
    path: Path,
    *,
    symbol: str = "XAUUSD",
    spec_name: str = "xauusd-validation",
    dataset_version: str = "v1",
    max_gap_hours: float = 48.0,
    timeframe: str = "5",
    window_name: str = "in_sample",
    window_kind: str = "in_sample",
    parquet_path: str = "data/historical/XAUUSD/M5/in_sample.parquet",
    row_count: int = 100,
    min_ts_ns: int = 1_700_000_000_000_000_000,
    max_ts_ns: int = 1_700_000_300_000_000_000,
) -> Path:
    """Hand-craft a minimal Go-style sidecar JSON."""
    payload = {
        "schema_version": "1",
        "spec_name": spec_name,
        "dataset_version": dataset_version,
        "symbol": symbol,
        "generated_at": "2026-05-03T12:00:00+00:00",
        "max_gap_hours": max_gap_hours,
        "entries": [
            {
                "timeframe": timeframe,
                "window_name": window_name,
                "window_kind": window_kind,
                "start": "2024-01-01T00:00:00+00:00",
                "end": "2026-01-01T00:00:00+00:00",
                "parquet_path": parquet_path,
                "fingerprint": {
                    "min_ts": min_ts_ns,
                    "max_ts": max_ts_ns,
                    "row_count": row_count,
                    "sha256_short": "deadbeef00000000",
                },
                "row_count": row_count,
                "gaps": [],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def test_merge_two_consistent_sidecars(tmp_path: Path) -> None:
    """Happy path: M5 IS + M5 OOS shards merge into a 2-entry manifest."""
    is_path = _write_sidecar(
        tmp_path / "in_sample.parquet.manifest.json",
        window_name="in_sample",
        window_kind="in_sample",
        row_count=200,
    )
    oos_path = _write_sidecar(
        tmp_path / "oos_reserve.parquet.manifest.json",
        window_name="oos_reserve",
        window_kind="oos_reserve",
        parquet_path="data/historical/XAUUSD/M5/oos_reserve.parquet",
        row_count=50,
    )

    merged = merge_go_manifests([is_path, oos_path])
    assert merged.symbol == "XAUUSD"
    assert merged.spec_name == "xauusd-validation"
    assert merged.dataset_version == "v1"
    assert merged.max_gap_hours == 48.0
    assert len(merged.entries) == 2
    assert merged.total_rows == 250
    # Order preserved.
    assert merged.entries[0].window_name == "in_sample"
    assert merged.entries[1].window_name == "oos_reserve"


def test_merge_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one sidecar"):
        merge_go_manifests([])


def test_merge_rejects_disagreeing_symbol(tmp_path: Path) -> None:
    a = _write_sidecar(tmp_path / "a.json", symbol="XAUUSD")
    b = _write_sidecar(tmp_path / "b.json", symbol="EURUSD")
    with pytest.raises(ValueError, match="disagree on symbol"):
        merge_go_manifests([a, b])


def test_merge_rejects_disagreeing_max_gap(tmp_path: Path) -> None:
    a = _write_sidecar(tmp_path / "a.json", max_gap_hours=48.0)
    b = _write_sidecar(tmp_path / "b.json", max_gap_hours=24.0)
    with pytest.raises(ValueError, match="max_gap_hours"):
        merge_go_manifests([a, b])


def test_merge_rejects_disagreeing_spec_name_without_override(tmp_path: Path) -> None:
    a = _write_sidecar(tmp_path / "a.json", spec_name="alpha")
    b = _write_sidecar(tmp_path / "b.json", spec_name="beta")
    with pytest.raises(ValueError, match="spec_name"):
        merge_go_manifests([a, b])


def test_merge_rejects_disagreeing_dataset_version_without_override(tmp_path: Path) -> None:
    """Symmetric guard to the spec_name check — same code branch, same risk."""
    a = _write_sidecar(tmp_path / "a.json", dataset_version="v1")
    b = _write_sidecar(tmp_path / "b.json", dataset_version="v2")
    with pytest.raises(ValueError, match="dataset_version"):
        merge_go_manifests([a, b])


def test_merge_rejects_path_traversal(tmp_path: Path) -> None:
    """Defence-in-depth: sidecar path itself must not contain '..'."""
    real = _write_sidecar(tmp_path / "real.json")
    traversal = tmp_path / ".." / "tmp" / "real.json"
    with pytest.raises(ValueError, match=r"\.\."):
        merge_go_manifests([real, traversal])


def test_merge_accepts_explicit_spec_name_override(tmp_path: Path) -> None:
    """Operator override resolves spec-name disagreement deliberately."""
    a = _write_sidecar(tmp_path / "a.json", spec_name="alpha")
    b = _write_sidecar(tmp_path / "b.json", spec_name="beta")
    merged = merge_go_manifests([a, b], spec_name="resolved", dataset_version="v2")
    assert merged.spec_name == "resolved"
    assert merged.dataset_version == "v2"


def test_merge_round_trips_through_save_load(tmp_path: Path) -> None:
    """The merged manifest should re-serialise via DatasetManifest.save_json
    and load back as an equal object — proving cross-language fidelity."""
    a = _write_sidecar(tmp_path / "a.json", window_name="in_sample")
    b = _write_sidecar(
        tmp_path / "b.json",
        window_name="oos_reserve",
        window_kind="oos_reserve",
        parquet_path="data/historical/XAUUSD/M5/oos.parquet",
    )

    merged = merge_go_manifests([a, b])
    out = tmp_path / "merged.json"
    merged.save_json(out)

    reloaded = DatasetManifest.load_json(out)
    assert reloaded.symbol == merged.symbol
    assert reloaded.spec_name == merged.spec_name
    assert reloaded.dataset_version == merged.dataset_version
    assert reloaded.total_rows == merged.total_rows
    assert len(reloaded.entries) == len(merged.entries)


def test_merge_uses_fresh_generated_at(tmp_path: Path) -> None:
    """Merged manifest carries a recent timestamp, not the original
    sidecar's value — the merge is its own materialisation event.

    A small tolerance protects against NTP step regressions in CI.
    """
    a = _write_sidecar(tmp_path / "a.json")
    before = datetime.now(UTC) - timedelta(seconds=1)
    merged = merge_go_manifests([a])
    assert merged.generated_at >= before
