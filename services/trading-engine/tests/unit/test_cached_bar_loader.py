"""Unit tests for CachedBarLoader (Parquet + Timescale composite)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.data_loader import CachedBarLoader, ParquetBarLoader


pytestmark = pytest.mark.unit


def _sample_df(rows: int = 3) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01T00:00:00Z", periods=rows, freq="1min", tz="UTC")
    return pd.DataFrame(
        {"open": [1.0] * rows, "high": [1.0] * rows, "low": [1.0] * rows,
         "close": [1.0] * rows, "volume": [100.0] * rows},
        index=ts,
    )


def _fp() -> ContentHashFingerprint:
    return ContentHashFingerprint(min_ts=1, max_ts=2, row_count=3)


def _range() -> tuple[datetime, datetime]:
    return (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 2, tzinfo=UTC),
    )


class TestCacheHit:
    def test_parquet_hit_skips_timescale(self, tmp_path) -> None:
        parquet = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        df = _sample_df()
        parquet.write("XAUUSD", "1m", start, end, _fp(), df)

        timescale = MagicMock()
        loader = CachedBarLoader(parquet=parquet, timescale=timescale)
        result = loader.load("XAUUSD", "1m", start, end, _fp())

        assert len(result) == 3
        timescale.load.assert_not_called()


class TestCacheMiss:
    def test_miss_falls_back_to_timescale_and_writes_parquet(self, tmp_path) -> None:
        parquet = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        fp = _fp()

        timescale = MagicMock()
        timescale.load = MagicMock(return_value=_sample_df(rows=5))
        loader = CachedBarLoader(parquet=parquet, timescale=timescale)

        result = loader.load("XAUUSD", "1m", start, end, fp)
        assert len(result) == 5
        timescale.load.assert_called_once()

        # Second call should now hit parquet — timescale not touched again.
        timescale.load.reset_mock()
        result2 = loader.load("XAUUSD", "1m", start, end, fp)
        assert len(result2) == 5
        timescale.load.assert_not_called()

    def test_invalidated_by_different_fingerprint(self, tmp_path) -> None:
        """New fingerprint forces Timescale re-fetch even with existing shard."""
        parquet = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        fp_old = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=3)
        fp_new = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=4)  # changed

        parquet.write("XAUUSD", "1m", start, end, fp_old, _sample_df())

        timescale = MagicMock()
        timescale.load = MagicMock(return_value=_sample_df(rows=4))
        loader = CachedBarLoader(parquet=parquet, timescale=timescale)

        result = loader.load("XAUUSD", "1m", start, end, fp_new)
        assert len(result) == 4
        timescale.load.assert_called_once()


class TestNoCacheFlag:
    def test_no_cache_forces_timescale(self, tmp_path) -> None:
        parquet = ParquetBarLoader(cache_dir=tmp_path)
        start, end = _range()
        fp = _fp()
        parquet.write("XAUUSD", "1m", start, end, fp, _sample_df())

        timescale = MagicMock()
        timescale.load = MagicMock(return_value=_sample_df(rows=7))
        loader = CachedBarLoader(parquet=parquet, timescale=timescale)

        result = loader.load(
            "XAUUSD", "1m", start, end, fp, no_cache=True
        )
        assert len(result) == 7
        timescale.load.assert_called_once()
