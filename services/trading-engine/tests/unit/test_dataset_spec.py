"""Unit tests for ``src.backtesting.dataset.spec``.

Covers the YAML-loadable :class:`DatasetSpec` that pins the validation
dataset (Epic 12.1): symbol whitelist, timeframe whitelist, tz-aware
window timestamps, IS/OOS classification, and round-trip via YAML.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.backtesting.dataset.spec import (
    DatasetSpec,
    WindowKind,
    WindowSpec,
)


pytestmark = pytest.mark.unit


def _is_window() -> dict:
    return {
        "name": "in_sample",
        "kind": "in_sample",
        "start": "2024-01-01T00:00:00Z",
        "end": "2026-01-01T00:00:00Z",
    }


def _oos_window() -> dict:
    return {
        "name": "oos_reserve",
        "kind": "oos_reserve",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-05-01T00:00:00Z",
    }


def _spec_dict() -> dict:
    return {
        "name": "xauusd-validation",
        "description": "Pinned XAUUSD M5+M15 validation dataset",
        "dataset_version": "1.0.0",
        "symbol": "XAUUSD",
        "timeframes": ["M5", "M15"],
        "max_gap_hours": 48.0,
        "windows": [_is_window(), _oos_window()],
    }


class TestWindowSpec:
    def test_accepts_in_sample(self) -> None:
        ws = WindowSpec(**_is_window())
        assert ws.kind is WindowKind.IN_SAMPLE
        assert ws.start.tzinfo is not None
        assert ws.end > ws.start

    def test_accepts_oos_reserve(self) -> None:
        ws = WindowSpec(**_oos_window())
        assert ws.kind is WindowKind.OOS_RESERVE

    def test_rejects_unknown_kind(self) -> None:
        bad = _is_window() | {"kind": "training"}
        with pytest.raises(ValidationError):
            WindowSpec(**bad)

    def test_rejects_naive_datetime(self) -> None:
        bad = _is_window() | {"start": datetime(2024, 1, 1)}
        with pytest.raises(ValidationError, match="timezone-aware"):
            WindowSpec(**bad)

    def test_rejects_end_before_start(self) -> None:
        bad = _is_window() | {
            "start": "2026-01-01T00:00:00Z",
            "end": "2024-01-01T00:00:00Z",
        }
        with pytest.raises(ValidationError, match="end must be"):
            WindowSpec(**bad)

    def test_rejects_end_equal_start(self) -> None:
        same = "2026-01-01T00:00:00Z"
        bad = _is_window() | {"start": same, "end": same}
        with pytest.raises(ValidationError, match="end must be"):
            WindowSpec(**bad)

    def test_rejects_empty_name(self) -> None:
        bad = _is_window() | {"name": ""}
        with pytest.raises(ValidationError):
            WindowSpec(**bad)

    def test_normalises_to_utc(self) -> None:
        # Caller passes a non-UTC tz; spec stores the same instant in UTC
        ws = WindowSpec(
            name="in_sample",
            kind="in_sample",
            start=datetime(2024, 1, 1, 7, tzinfo=timezone.max),
            end=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert ws.start.tzinfo == UTC

    def test_is_frozen(self) -> None:
        ws = WindowSpec(**_is_window())
        with pytest.raises(ValidationError):
            ws.name = "other"  # type: ignore[misc]


class TestDatasetSpec:
    def test_loads_from_dict(self) -> None:
        spec = DatasetSpec.model_validate(_spec_dict())
        assert spec.symbol == "XAUUSD"
        assert spec.timeframes == ("M5", "M15")
        assert spec.max_gap_hours == 48.0
        assert {w.kind for w in spec.windows} == {
            WindowKind.IN_SAMPLE,
            WindowKind.OOS_RESERVE,
        }

    def test_round_trip_via_yaml(self, tmp_path) -> None:
        path = tmp_path / "ds.yaml"
        path.write_text(yaml.safe_dump(_spec_dict()))
        spec = DatasetSpec.from_yaml(path)
        assert spec.name == "xauusd-validation"
        assert len(spec.windows) == 2

    def test_rejects_unknown_symbol(self) -> None:
        bad = _spec_dict() | {"symbol": "BTCUSD"}
        with pytest.raises(ValidationError, match="Unsupported"):
            DatasetSpec.model_validate(bad)

    def test_rejects_empty_timeframes(self) -> None:
        bad = _spec_dict() | {"timeframes": []}
        with pytest.raises(ValidationError):
            DatasetSpec.model_validate(bad)

    def test_rejects_unsafe_timeframe(self) -> None:
        # build_cache_path validates symbol/timeframe; the spec must reject
        # anything that would later blow up the on-disk shard path.
        bad = _spec_dict() | {"timeframes": ["M5", "../escape"]}
        with pytest.raises(ValidationError, match="timeframe"):
            DatasetSpec.model_validate(bad)

    def test_rejects_duplicate_timeframes(self) -> None:
        bad = _spec_dict() | {"timeframes": ["M5", "M5"]}
        with pytest.raises(ValidationError, match="duplicate"):
            DatasetSpec.model_validate(bad)

    def test_rejects_duplicate_window_names(self) -> None:
        bad = _spec_dict() | {"windows": [_is_window(), _is_window()]}
        with pytest.raises(ValidationError, match="duplicate"):
            DatasetSpec.model_validate(bad)

    def test_rejects_no_windows(self) -> None:
        bad = _spec_dict() | {"windows": []}
        with pytest.raises(ValidationError):
            DatasetSpec.model_validate(bad)

    def test_rejects_negative_gap_threshold(self) -> None:
        bad = _spec_dict() | {"max_gap_hours": -1.0}
        with pytest.raises(ValidationError):
            DatasetSpec.model_validate(bad)

    def test_iter_entries_is_cartesian_product(self) -> None:
        spec = DatasetSpec.model_validate(_spec_dict())
        entries = list(spec.iter_entries())
        # 2 timeframes × 2 windows = 4 combinations
        assert len(entries) == 4
        kinds_per_tf = {tf: [] for tf in spec.timeframes}
        for tf, window in entries:
            kinds_per_tf[tf].append(window.kind)
        assert all(
            set(v) == {WindowKind.IN_SAMPLE, WindowKind.OOS_RESERVE}
            for v in kinds_per_tf.values()
        )

    def test_rejects_yaml_top_level_not_mapping(self, tmp_path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(ValueError, match="mapping"):
            DatasetSpec.from_yaml(path)


class TestCanonicalYaml:
    """Pin the canonical Epic 12 dataset YAML to specific values.

    The validation campaign (12.2 onwards) cites this spec by path; if
    a downstream story silently reshapes it the comparison report
    becomes irreproducible. This test fails loudly on accidental edits
    so any change has to be intentional + reviewed.
    """

    def _path(self) -> Path:
        repo_root = Path(__file__).resolve().parents[4]
        return repo_root / "configs" / "datasets" / "xauusd-validation.yaml"

    def test_canonical_xauusd_spec_loads(self) -> None:
        spec = DatasetSpec.from_yaml(self._path())
        assert spec.symbol == "XAUUSD"
        assert spec.timeframes == ("M5", "M15")
        assert spec.max_gap_hours == 48.0

        windows = {w.name: w for w in spec.windows}
        assert set(windows) == {"in_sample", "oos_reserve"}

        is_window = windows["in_sample"]
        assert is_window.kind is WindowKind.IN_SAMPLE
        assert is_window.start == datetime(2024, 1, 1, tzinfo=UTC)
        assert is_window.end == datetime(2026, 1, 1, tzinfo=UTC)

        oos = windows["oos_reserve"]
        assert oos.kind is WindowKind.OOS_RESERVE
        assert oos.start == datetime(2026, 1, 1, tzinfo=UTC)
        assert oos.end == datetime(2026, 5, 1, tzinfo=UTC)
