"""Unit tests for data_cache module (cache key + path generation)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backtesting.data_cache import (
    ContentHashFingerprint,
    build_cache_key,
    build_cache_path,
)


pytestmark = pytest.mark.unit


class TestContentHashFingerprint:
    def test_equal_fingerprints_hash_same(self) -> None:
        fp1 = ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=1000
        )
        fp2 = ContentHashFingerprint(
            min_ts=1_000_000_000, max_ts=2_000_000_000, row_count=1000
        )
        assert fp1.sha256() == fp2.sha256()

    def test_different_row_count_differs(self) -> None:
        fp1 = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        fp2 = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=101)
        assert fp1.sha256() != fp2.sha256()

    def test_different_max_ts_differs(self) -> None:
        fp1 = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        fp2 = ContentHashFingerprint(min_ts=1, max_ts=3, row_count=100)
        assert fp1.sha256() != fp2.sha256()

    def test_hash_is_deterministic_16_hex(self) -> None:
        """SHA256 hex — we take first 16 chars for short cache keys."""
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        h = fp.sha256()
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)


class TestBuildCacheKey:
    def _range(self) -> tuple[datetime, datetime]:
        return (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 4, 1, tzinfo=UTC),
        )

    def test_same_inputs_same_key(self) -> None:
        start, end = self._range()
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        k1 = build_cache_key("XAUUSD", "1m", start, end, fp)
        k2 = build_cache_key("XAUUSD", "1m", start, end, fp)
        assert k1 == k2

    def test_symbol_changes_key(self) -> None:
        start, end = self._range()
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        assert (
            build_cache_key("XAUUSD", "1m", start, end, fp)
            != build_cache_key("EURUSD", "1m", start, end, fp)
        )

    def test_timeframe_changes_key(self) -> None:
        start, end = self._range()
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        assert (
            build_cache_key("XAUUSD", "1m", start, end, fp)
            != build_cache_key("XAUUSD", "5m", start, end, fp)
        )

    def test_range_changes_key(self) -> None:
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end1 = datetime(2026, 4, 1, tzinfo=UTC)
        end2 = datetime(2026, 5, 1, tzinfo=UTC)
        assert (
            build_cache_key("XAUUSD", "1m", start, end1, fp)
            != build_cache_key("XAUUSD", "1m", start, end2, fp)
        )

    def test_content_hash_changes_key(self) -> None:
        start, end = self._range()
        fp1 = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        fp2 = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=101)
        assert (
            build_cache_key("XAUUSD", "1m", start, end, fp1)
            != build_cache_key("XAUUSD", "1m", start, end, fp2)
        )


class TestBuildCachePath:
    def test_path_structure(self, tmp_path) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 4, 1, tzinfo=UTC)
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        path = build_cache_path(
            cache_dir=tmp_path,
            symbol="XAUUSD",
            timeframe="1m",
            start=start,
            end=end,
            fingerprint=fp,
        )
        # Structure: {cache_dir}/{symbol}/{timeframe}/{start}_{end}_{hash}.parquet
        assert path.parent.parent.name == "XAUUSD"
        assert path.parent.name == "1m"
        assert path.suffix == ".parquet"
        assert "20260101" in path.stem
        assert "20260401" in path.stem

    def test_path_includes_hash(self, tmp_path) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 4, 1, tzinfo=UTC)
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        path = build_cache_path(
            cache_dir=tmp_path,
            symbol="XAUUSD",
            timeframe="1m",
            start=start,
            end=end,
            fingerprint=fp,
        )
        assert fp.sha256() in path.stem

    def test_cross_symbol_paths_disjoint(self, tmp_path) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 4, 1, tzinfo=UTC)
        fp = ContentHashFingerprint(min_ts=1, max_ts=2, row_count=100)
        p1 = build_cache_path(tmp_path, "XAUUSD", "1m", start, end, fp)
        p2 = build_cache_path(tmp_path, "EURUSD", "1m", start, end, fp)
        assert p1.parent != p2.parent


class TestPathTraversalHardening:
    """Regression: symbol/timeframe must be rejected if they could escape."""

    def _args(self, tmp_path) -> dict:
        return dict(
            cache_dir=tmp_path,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 4, 1, tzinfo=UTC),
            fingerprint=ContentHashFingerprint(min_ts=1, max_ts=2, row_count=1),
        )

    def test_rejects_parent_traversal_symbol(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="symbol"):
            build_cache_path(symbol="../../etc", timeframe="1m", **self._args(tmp_path))

    def test_rejects_parent_traversal_timeframe(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="timeframe"):
            build_cache_path(symbol="XAUUSD", timeframe="../x", **self._args(tmp_path))

    def test_rejects_absolute_path_symbol(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="symbol"):
            build_cache_path(symbol="/etc/passwd", timeframe="1m", **self._args(tmp_path))

    def test_rejects_empty_symbol(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="symbol"):
            build_cache_path(symbol="", timeframe="1m", **self._args(tmp_path))

    def test_rejects_null_byte(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="symbol"):
            build_cache_path(symbol="XAU\x00", timeframe="1m", **self._args(tmp_path))

    def test_rejects_space(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="symbol"):
            build_cache_path(symbol="XAU USD", timeframe="1m", **self._args(tmp_path))

    def test_accepts_safe_symbol(self, tmp_path) -> None:
        path = build_cache_path(
            symbol="XAUUSD", timeframe="1m", **self._args(tmp_path)
        )
        assert path.parent.parent.name == "XAUUSD"
