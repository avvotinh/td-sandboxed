"""Unit tests for ``src.backtesting.dataset.manifest``.

The manifest is the materialisation receipt: one row per
(timeframe, window) Parquet shard with the fingerprint that lets a
downstream backtest assert it loaded the same data. JSON is the
on-disk format (machine-generated, easy to diff in code review).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.manifest import (
    BarGap,
    DatasetEntry,
    DatasetManifest,
)
from src.backtesting.dataset.spec import WindowKind


pytestmark = pytest.mark.unit


def _entry(
    *,
    timeframe: str = "M5",
    window_name: str = "in_sample",
    kind: WindowKind = WindowKind.IN_SAMPLE,
    parquet_path: str = "/tmp/cache/XAUUSD/M5/in_sample.parquet",
    row_count: int = 1000,
) -> DatasetEntry:
    return DatasetEntry(
        timeframe=timeframe,
        window_name=window_name,
        window_kind=kind,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2026, 1, 1, tzinfo=UTC),
        parquet_path=Path(parquet_path),
        fingerprint=ContentHashFingerprint(
            min_ts=1_000_000_000,
            max_ts=2_000_000_000,
            row_count=row_count,
        ),
        row_count=row_count,
        gaps=(),
    )


class TestDatasetEntry:
    def test_fingerprint_short_is_first_16_hex(self) -> None:
        entry = _entry()
        assert entry.fingerprint_short == entry.fingerprint.sha256()

    def test_is_frozen(self) -> None:
        entry = _entry()
        with pytest.raises((AttributeError, TypeError)):
            entry.row_count = 0  # type: ignore[misc]

    def test_to_dict_has_iso_timestamps(self) -> None:
        d = _entry().to_dict()
        assert d["start"] == "2024-01-01T00:00:00+00:00"
        assert d["end"] == "2026-01-01T00:00:00+00:00"
        assert d["fingerprint"] == {
            "min_ts": 1_000_000_000,
            "max_ts": 2_000_000_000,
            "row_count": 1000,
            "sha256_short": ContentHashFingerprint(
                min_ts=1_000_000_000,
                max_ts=2_000_000_000,
                row_count=1000,
            ).sha256(),
        }
        assert d["window_kind"] == "in_sample"


class TestBarGap:
    def test_duration_hours(self) -> None:
        gap = BarGap(
            timeframe="M5",
            window_name="in_sample",
            before=datetime(2024, 1, 5, 21, tzinfo=UTC),
            after=datetime(2024, 1, 7, 22, tzinfo=UTC),
        )
        assert gap.duration_hours == pytest.approx(49.0)


class TestDatasetManifest:
    def _manifest(self) -> DatasetManifest:
        return DatasetManifest(
            spec_name="xauusd-validation",
            dataset_version="1.0.0",
            symbol="XAUUSD",
            generated_at=datetime(2026, 5, 3, 12, tzinfo=UTC),
            max_gap_hours=48.0,
            entries=(_entry(), _entry(window_name="oos_reserve",
                                      kind=WindowKind.OOS_RESERVE,
                                      row_count=200)),
        )

    def test_save_load_round_trip(self, tmp_path) -> None:
        manifest = self._manifest()
        path = tmp_path / "manifest.json"
        manifest.save_json(path)
        loaded = DatasetManifest.load_json(path)
        assert loaded == manifest

    def test_load_rejects_unknown_window_kind(self, tmp_path) -> None:
        manifest = self._manifest()
        path = tmp_path / "manifest.json"
        manifest.save_json(path)
        bad = path.read_text().replace('"in_sample"', '"made_up"', 1)
        path.write_text(bad)
        with pytest.raises(ValueError):
            DatasetManifest.load_json(path)

    def test_load_rejects_traversal_in_parquet_path(self, tmp_path) -> None:
        manifest = self._manifest()
        path = tmp_path / "manifest.json"
        manifest.save_json(path)
        tampered = path.read_text().replace(
            "/tmp/cache/XAUUSD/M5/in_sample.parquet",
            "/tmp/cache/../../etc/passwd",
            1,
        )
        path.write_text(tampered)
        with pytest.raises(ValueError, match="traversal"):
            DatasetManifest.load_json(path)

    def test_load_rejects_unknown_schema_version(self, tmp_path) -> None:
        manifest = self._manifest()
        path = tmp_path / "manifest.json"
        manifest.save_json(path)
        bad = path.read_text().replace('"schema_version": "1"',
                                       '"schema_version": "99"', 1)
        path.write_text(bad)
        with pytest.raises(ValueError, match="schema_version"):
            DatasetManifest.load_json(path)

    def test_entries_for_window_filters(self) -> None:
        manifest = self._manifest()
        is_entries = manifest.entries_for_window("in_sample")
        assert len(is_entries) == 1
        assert is_entries[0].window_kind is WindowKind.IN_SAMPLE

    def test_total_rows_aggregates(self) -> None:
        manifest = self._manifest()
        # 1000 in_sample + 200 oos_reserve = 1200
        assert manifest.total_rows == 1200

    def test_gap_count_counts_across_entries(self) -> None:
        gap = BarGap(
            timeframe="M5",
            window_name="in_sample",
            before=datetime(2024, 1, 5, 21, tzinfo=UTC),
            after=datetime(2024, 1, 7, 22, tzinfo=UTC),
        )
        manifest = DatasetManifest(
            spec_name="x",
            dataset_version="1",
            symbol="XAUUSD",
            generated_at=datetime(2026, 5, 3, tzinfo=UTC),
            max_gap_hours=48.0,
            entries=(
                dataclasses.replace(_entry(), gaps=(gap, gap)),
                dataclasses.replace(
                    _entry(
                        window_name="oos_reserve",
                        kind=WindowKind.OOS_RESERVE,
                    ),
                    gaps=(gap,),
                ),
            ),
        )
        assert manifest.gap_count == 3
