"""Tests for the independent parquet candle loader."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from chart_viewer.candles import load_candles


def _write_parquet_indexed(path: Path, n: int) -> None:
    """tz-aware DatetimeIndex named 'time' + OHLCV (CachedBarLoader shape)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC", name="time")
    df = pd.DataFrame(
        {
            "open": range(n),
            "high": [i + 1 for i in range(n)],
            "low": [i - 1 for i in range(n)],
            "close": [i + 0.5 for i in range(n)],
            "volume": [10.0] * n,
        },
        index=idx,
    )
    df.to_parquet(path)


def _write_parquet_col(path: Path, n: int) -> None:
    """int64 ms 'time' column + OHLCV (stitch_chunks shape)."""
    base = pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000  # ms
    df = pd.DataFrame(
        {
            "time": [base + i * 300_000 for i in range(n)],  # 5min in ms
            "open": range(n),
            "high": [i + 1 for i in range(n)],
            "low": [i - 1 for i in range(n)],
            "close": [i + 0.5 for i in range(n)],
            "volume": [10.0] * n,
        }
    )
    df.to_parquet(path, index=False)


def test_synthetic_returns_note() -> None:
    result = load_candles({"manifest": "synthetic:trending:count=3:seed=1"}, {})
    assert result.candles == []
    assert "synthetic" in result.note


def test_missing_manifest_returns_note() -> None:
    result = load_candles({}, {})
    assert result.candles == []
    assert result.note


def test_missing_parquet_returns_note(tmp_path: Path) -> None:
    result = load_candles({"manifest": "data/nope.parquet"}, {}, root=tmp_path)
    assert result.candles == []
    assert "not found" in result.note


def test_loads_indexed_shape(tmp_path: Path) -> None:
    _write_parquet_indexed(tmp_path / "bars.parquet", 10)
    result = load_candles({"manifest": "bars.parquet"}, {}, root=tmp_path)
    assert len(result.candles) == 10
    c0 = result.candles[0]
    assert set(c0) == {"time", "open", "high", "low", "close", "volume"}
    assert c0["time"] == int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())


def test_loads_column_shape(tmp_path: Path) -> None:
    _write_parquet_col(tmp_path / "bars.parquet", 10)
    result = load_candles({"manifest": "bars.parquet"}, {}, root=tmp_path)
    assert len(result.candles) == 10
    assert result.candles[0]["time"] == int(pd.Timestamp("2024-01-01", tz="UTC").timestamp())


def test_window_slices(tmp_path: Path) -> None:
    _write_parquet_indexed(tmp_path / "bars.parquet", 20)
    window = {
        "start": "2024-01-01T00:05:00+00:00",  # skip the first bar
        "end": "2024-01-01T00:20:00+00:00",  # bars at 5,10,15,20 min → 4 bars
    }
    result = load_candles({"manifest": "bars.parquet"}, window, root=tmp_path)
    times = [c["time"] for c in result.candles]
    assert times[0] == int(pd.Timestamp("2024-01-01T00:05:00", tz="UTC").timestamp())
    assert times[-1] == int(pd.Timestamp("2024-01-01T00:20:00", tz="UTC").timestamp())
    assert len(times) == 4


def test_resample_caps_candles(tmp_path: Path) -> None:
    _write_parquet_indexed(tmp_path / "bars.parquet", 100)
    result = load_candles({"manifest": "bars.parquet"}, {}, root=tmp_path, max_candles=10)
    assert result.resampled_factor > 1
    assert len(result.candles) <= 10
    # Aggregated candle preserves high=max/low=min over its bucket.
    assert result.candles[0]["high"] >= result.candles[0]["open"]
    assert "downsampled" in result.note


def test_foreign_parquet_raises(tmp_path: Path) -> None:
    pd.DataFrame({"foo": [1, 2]}).to_parquet(tmp_path / "bad.parquet", index=False)
    with pytest.raises(ValueError):
        load_candles({"manifest": "bad.parquet"}, {}, root=tmp_path)


def test_traversal_manifest_returns_note_not_raise(tmp_path: Path) -> None:
    # A hand-edited data_ref escaping the repo root must degrade to a
    # note (the guard), never read the outside file or raise.
    result = load_candles({"manifest": "../../etc/passwd"}, {}, root=tmp_path)
    assert result.candles == []
    assert "escapes the repo root" in result.note


def test_non_finite_ohlc_rows_dropped(tmp_path: Path) -> None:
    idx = pd.date_range("2024-01-01", periods=3, freq="5min", tz="UTC", name="time")
    df = pd.DataFrame(
        {
            "open": [1.0, float("nan"), 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [10.0, 10.0, 10.0],
        },
        index=idx,
    )
    df.to_parquet(tmp_path / "bars.parquet")
    result = load_candles({"manifest": "bars.parquet"}, {}, root=tmp_path)
    # The middle bar (NaN open) is dropped; the other two survive.
    assert len(result.candles) == 2
    assert all(r["open"] == r["open"] for r in result.candles)  # no NaN
