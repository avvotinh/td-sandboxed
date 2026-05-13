"""Unit tests for ``src.backtesting.dataset.pipeline``.

The pipeline's job is to walk every (timeframe, window) entry in the
spec, ensure a Parquet shard exists with the right fingerprint, and
emit a :class:`DatasetManifest`. Tests use a fake bar source so we
neither hit TimescaleDB nor an event loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.data_loader import ParquetBarLoader
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.dataset.pipeline import (
    DatasetPipeline,
    detect_gaps,
    timeframe_to_seconds,
)
from src.backtesting.dataset.spec import DatasetSpec


pytestmark = pytest.mark.unit


def _spec(**overrides) -> DatasetSpec:
    base = {
        "name": "xauusd-validation",
        "dataset_version": "1.0.0",
        "symbol": "XAUUSD",
        "timeframes": ("M5",),
        "windows": (
            {
                "name": "in_sample",
                "kind": "in_sample",
                "start": datetime(2024, 1, 1, tzinfo=UTC),
                "end": datetime(2024, 1, 8, tzinfo=UTC),
            },
        ),
        "max_gap_hours": 48.0,
    }
    return DatasetSpec.model_validate(base | overrides)


def _bars_df(start: datetime, *, count: int, freq_seconds: int) -> pd.DataFrame:
    """Build a synthetic OHLCV frame indexed by tz-aware DatetimeIndex."""
    idx = pd.date_range(start, periods=count, freq=f"{freq_seconds}s", tz="UTC")
    return pd.DataFrame(
        {
            "open": [1.0] * count,
            "high": [1.0] * count,
            "low": [1.0] * count,
            "close": [1.0] * count,
            "volume": [1.0] * count,
        },
        index=idx,
    )


class _FakeBarSource:
    """Fake :class:`BarSourceProtocol` driven by canned DataFrames."""

    def __init__(self) -> None:
        self.frames: dict[tuple[str, str, datetime, datetime], pd.DataFrame] = {}
        self.afingerprint_calls: list[tuple] = []
        self.aload_calls: list[tuple] = []

    def install(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        df: pd.DataFrame,
    ) -> None:
        self.frames[(symbol, timeframe, start, end)] = df

    async def afingerprint(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> ContentHashFingerprint:
        self.afingerprint_calls.append((symbol, timeframe, start, end))
        df = self.frames[(symbol, timeframe, start, end)]
        if len(df) == 0:
            return ContentHashFingerprint(min_ts=0, max_ts=0, row_count=0)
        min_ts = int(df.index[0].value)
        max_ts = int(df.index[-1].value)
        return ContentHashFingerprint(
            min_ts=min_ts, max_ts=max_ts, row_count=len(df)
        )

    async def aload(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        self.aload_calls.append((symbol, timeframe, start, end))
        return self.frames[(symbol, timeframe, start, end)]


class TestTimeframeToSeconds:
    @pytest.mark.parametrize(
        ("tf", "expected"),
        [
            ("M1", 60),
            ("M5", 300),
            ("M15", 900),
            ("M30", 1800),
            ("H1", 3600),
            ("H4", 14400),
            ("D1", 86400),
        ],
    )
    def test_known_timeframes(self, tf: str, expected: int) -> None:
        assert timeframe_to_seconds(tf) == expected

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            timeframe_to_seconds("W1")


class TestDetectGaps:
    def test_no_gap_when_evenly_spaced(self) -> None:
        df = _bars_df(datetime(2024, 1, 1, tzinfo=UTC), count=10, freq_seconds=300)
        assert detect_gaps(
            df,
            timeframe="M5",
            window_name="in_sample",
            max_gap_hours=48.0,
        ) == ()

    def test_flags_gap_above_threshold(self) -> None:
        # Two segments separated by a 50h gap (longer than 48h weekend).
        seg_a = _bars_df(datetime(2024, 1, 5, 21, tzinfo=UTC), count=2, freq_seconds=300)
        seg_b = _bars_df(datetime(2024, 1, 7, 23, tzinfo=UTC), count=2, freq_seconds=300)
        df = pd.concat([seg_a, seg_b])
        gaps = detect_gaps(
            df,
            timeframe="M5",
            window_name="in_sample",
            max_gap_hours=48.0,
        )
        assert len(gaps) == 1
        assert gaps[0].duration_hours > 48.0

    def test_gap_below_threshold_not_flagged(self) -> None:
        # 10-minute gap (00:20 last bar of seg_a → 00:30 first of seg_b)
        # is well below the 1h threshold, so nothing is flagged.
        seg_a = _bars_df(datetime(2024, 1, 1, tzinfo=UTC), count=5, freq_seconds=300)
        seg_b = _bars_df(
            datetime(2024, 1, 1, 0, 30, tzinfo=UTC), count=5, freq_seconds=300
        )
        df = pd.concat([seg_a, seg_b])
        assert detect_gaps(
            df,
            timeframe="M5",
            window_name="in_sample",
            max_gap_hours=1.0,
        ) == ()

    def test_rejects_tz_naive_index(self) -> None:
        # Naive index would corrupt the manifest if serialised as UTC.
        idx = pd.date_range("2024-01-01", periods=3, freq="5min")  # tz=None
        df = pd.DataFrame(
            {"open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3,
             "close": [1.0] * 3, "volume": [1.0] * 3},
            index=idx,
        )
        with pytest.raises(ValueError, match="tz-aware"):
            detect_gaps(
                df,
                timeframe="M5",
                window_name="in_sample",
                max_gap_hours=48.0,
            )

    def test_no_gaps_for_empty(self) -> None:
        df = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        assert detect_gaps(
            df,
            timeframe="M5",
            window_name="in_sample",
            max_gap_hours=48.0,
        ) == ()

    def test_no_gaps_for_single_bar(self) -> None:
        df = _bars_df(datetime(2024, 1, 1, tzinfo=UTC), count=1, freq_seconds=300)
        assert detect_gaps(
            df,
            timeframe="M5",
            window_name="in_sample",
            max_gap_hours=48.0,
        ) == ()


class TestDatasetPipelineMaterialize:
    def _run(self, pipeline: DatasetPipeline, spec: DatasetSpec) -> DatasetManifest:
        return asyncio.run(pipeline.materialize_async(spec))

    def test_writes_one_parquet_per_combination(self, tmp_path) -> None:
        spec = _spec(timeframes=("M5", "M15"))
        source = _FakeBarSource()
        for tf, freq in (("M5", 300), ("M15", 900)):
            for window in spec.windows:
                source.install(
                    symbol="XAUUSD",
                    timeframe=tf,
                    start=window.start,
                    end=window.end,
                    df=_bars_df(window.start, count=24, freq_seconds=freq),
                )
        pipeline = DatasetPipeline(
            parquet=ParquetBarLoader(cache_dir=tmp_path),
            source=source,
        )

        manifest = self._run(pipeline, spec)

        assert len(manifest.entries) == 2  # 2 timeframes × 1 window
        for entry in manifest.entries:
            assert entry.parquet_path.exists()
            assert entry.row_count == 24

    def test_manifest_includes_dataset_metadata(self, tmp_path) -> None:
        spec = _spec()
        source = _FakeBarSource()
        window = spec.windows[0]
        source.install(
            symbol="XAUUSD",
            timeframe="M5",
            start=window.start,
            end=window.end,
            df=_bars_df(window.start, count=10, freq_seconds=300),
        )
        pipeline = DatasetPipeline(
            parquet=ParquetBarLoader(cache_dir=tmp_path),
            source=source,
        )

        manifest = self._run(pipeline, spec)
        assert manifest.spec_name == "xauusd-validation"
        assert manifest.dataset_version == "1.0.0"
        assert manifest.symbol == "XAUUSD"
        assert manifest.max_gap_hours == 48.0

    def test_cache_hit_skips_aload(self, tmp_path) -> None:
        spec = _spec()
        source = _FakeBarSource()
        window = spec.windows[0]
        source.install(
            symbol="XAUUSD",
            timeframe="M5",
            start=window.start,
            end=window.end,
            df=_bars_df(window.start, count=10, freq_seconds=300),
        )
        pipeline = DatasetPipeline(
            parquet=ParquetBarLoader(cache_dir=tmp_path),
            source=source,
        )

        # First run: cache miss → aload.
        self._run(pipeline, spec)
        assert len(source.aload_calls) == 1

        # Second run: same fingerprint → cache hit, no extra aload.
        self._run(pipeline, spec)
        assert len(source.aload_calls) == 1

    def test_records_gaps_per_entry(self, tmp_path) -> None:
        spec = _spec(max_gap_hours=10.0)
        source = _FakeBarSource()
        window = spec.windows[0]
        # Two-segment frame separated by a 24h gap (> 10h threshold).
        seg_a = _bars_df(window.start, count=4, freq_seconds=300)
        seg_b = _bars_df(window.start + timedelta(hours=24), count=4, freq_seconds=300)
        source.install(
            symbol="XAUUSD",
            timeframe="M5",
            start=window.start,
            end=window.end,
            df=pd.concat([seg_a, seg_b]),
        )
        pipeline = DatasetPipeline(
            parquet=ParquetBarLoader(cache_dir=tmp_path),
            source=source,
        )

        manifest = self._run(pipeline, spec)
        assert manifest.gap_count == 1
        gap = manifest.entries[0].gaps[0]
        assert gap.timeframe == "M5"
        assert gap.window_name == "in_sample"
        assert gap.duration_hours > 10.0

    def test_empty_dataset_yields_zero_rows_no_crash(self, tmp_path) -> None:
        spec = _spec()
        source = _FakeBarSource()
        window = spec.windows[0]
        empty = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC"),
        )
        source.install(
            symbol="XAUUSD",
            timeframe="M5",
            start=window.start,
            end=window.end,
            df=empty,
        )
        pipeline = DatasetPipeline(
            parquet=ParquetBarLoader(cache_dir=tmp_path),
            source=source,
        )

        manifest = self._run(pipeline, spec)
        assert manifest.total_rows == 0
        assert manifest.entries[0].row_count == 0


class TestDatasetEntryParquetPath:
    """Manifest's parquet_path must match what ParquetBarLoader produces."""

    def test_path_matches_loader(self, tmp_path) -> None:
        spec = _spec()
        source = _FakeBarSource()
        window = spec.windows[0]
        source.install(
            symbol="XAUUSD",
            timeframe="M5",
            start=window.start,
            end=window.end,
            df=_bars_df(window.start, count=10, freq_seconds=300),
        )
        parquet = ParquetBarLoader(cache_dir=tmp_path)
        pipeline = DatasetPipeline(parquet=parquet, source=source)

        manifest = asyncio.run(pipeline.materialize_async(spec))

        entry: DatasetEntry = manifest.entries[0]
        expected = parquet.path_for(
            "XAUUSD", "M5", window.start, window.end, entry.fingerprint
        )
        assert entry.parquet_path == expected
