"""Unit tests for ParquetBarLoader (read/write local Parquet shards)."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.data_loader import ParquetBarLoader


pytestmark = pytest.mark.unit


def _sample_df(rows: int = 10) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01T00:00:00Z", periods=rows, freq="1min", tz="UTC")
    return pd.DataFrame(
        {
            "open": [2400.0 + i for i in range(rows)],
            "high": [2405.0 + i for i in range(rows)],
            "low": [2395.0 + i for i in range(rows)],
            "close": [2400.5 + i for i in range(rows)],
            "volume": [100.0 + i for i in range(rows)],
        },
        index=ts,
    )


def _sample_fp() -> ContentHashFingerprint:
    return ContentHashFingerprint(min_ts=1, max_ts=2, row_count=10)


def _range() -> tuple[datetime, datetime]:
    return (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )


class TestWriteAndLoad:
    def test_write_creates_file(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path)
        df = _sample_df()
        start, end = _range()
        path = loader.write("XAUUSD", "1m", start, end, _sample_fp(), df)
        assert path.exists()
        assert path.suffix == ".parquet"

    def test_roundtrip_preserves_rows(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path)
        df = _sample_df(rows=20)
        start, end = _range()
        fp = _sample_fp()
        loader.write("XAUUSD", "1m", start, end, fp, df)
        loaded = loader.load("XAUUSD", "1m", start, end, fp)
        assert loaded is not None
        assert len(loaded) == 20
        assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]

    def test_roundtrip_preserves_values(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path)
        df = _sample_df(rows=5)
        start, end = _range()
        fp = _sample_fp()
        loader.write("XAUUSD", "1m", start, end, fp, df)
        loaded = loader.load("XAUUSD", "1m", start, end, fp)
        assert loaded is not None
        pd.testing.assert_frame_equal(loaded, df, check_freq=False)


class TestMiss:
    def test_load_missing_returns_none(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        result = loader.load("NOPE", "1m", start, end, _sample_fp())
        assert result is None

    def test_load_with_different_hash_misses(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        fp_write = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=10)
        fp_read = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=11)
        loader.write("XAUUSD", "1m", start, end, fp_write, _sample_df())
        assert loader.load("XAUUSD", "1m", start, end, fp_read) is None


class TestCreatesDirectory:
    def test_parent_directory_created_on_write(self, tmp_path) -> None:
        loader = ParquetBarLoader(cache_dir=tmp_path / "deep" / "nested")
        start, end = _range()
        path = loader.write("XAUUSD", "1m", start, end, _sample_fp(), _sample_df())
        assert path.parent.exists()
