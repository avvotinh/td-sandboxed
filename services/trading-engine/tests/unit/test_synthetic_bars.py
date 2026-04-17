"""Unit tests for synthetic bar generator."""

from __future__ import annotations

import pytest
from nautilus_trader.model.data import Bar

from src.backtesting.synthetic_bars import generate_bars


pytestmark = pytest.mark.unit


class TestGenerateBarsBasic:
    def test_returns_list_of_bars(self) -> None:
        bars = generate_bars(pattern="flat", count=50, start_price=2400.0, seed=42)
        assert len(bars) == 50
        assert all(isinstance(b, Bar) for b in bars)

    def test_zero_count_returns_empty(self) -> None:
        bars = generate_bars(pattern="flat", count=0, start_price=2400.0, seed=42)
        assert bars == []

    def test_invalid_pattern_raises(self) -> None:
        with pytest.raises(ValueError, match="pattern"):
            generate_bars(pattern="not_a_pattern", count=10, start_price=2400, seed=1)


class TestDeterminism:
    def test_same_seed_same_bars(self) -> None:
        bars_a = generate_bars(pattern="mean_reverting", count=100, start_price=2400, seed=42)
        bars_b = generate_bars(pattern="mean_reverting", count=100, start_price=2400, seed=42)
        for a, b in zip(bars_a, bars_b, strict=True):
            assert a.close.as_double() == b.close.as_double()

    def test_different_seed_different_bars(self) -> None:
        bars_a = generate_bars(pattern="trending", count=50, start_price=2400, seed=42)
        bars_b = generate_bars(pattern="trending", count=50, start_price=2400, seed=43)
        close_diffs = [
            abs(a.close.as_double() - b.close.as_double())
            for a, b in zip(bars_a, bars_b, strict=True)
        ]
        assert sum(close_diffs) > 0


class TestPatternBehavior:
    def test_trending_pattern_rises(self) -> None:
        bars = generate_bars(pattern="trending", count=200, start_price=2400, seed=42)
        first_close = bars[0].close.as_double()
        last_close = bars[-1].close.as_double()
        assert last_close > first_close, "trending pattern should drift up"

    def test_mean_reverting_pattern_stays_bounded(self) -> None:
        bars = generate_bars(
            pattern="mean_reverting", count=500, start_price=2400, seed=42
        )
        closes = [b.close.as_double() for b in bars]
        max_dev = max(abs(c - 2400) for c in closes)
        # Mean-reverting should stay within a reasonable band of start_price
        assert max_dev < 50, f"mean-reverting drift too large: {max_dev}"

    def test_flat_pattern_minimal_movement(self) -> None:
        bars = generate_bars(pattern="flat", count=100, start_price=2400, seed=42)
        closes = [b.close.as_double() for b in bars]
        std_like = max(closes) - min(closes)
        assert std_like < 5, f"flat pattern moved too much: {std_like}"


class TestOHLCConsistency:
    def test_ohlc_valid_on_all_bars(self) -> None:
        bars = generate_bars(pattern="trending", count=100, start_price=2400, seed=42)
        for b in bars:
            o = b.open.as_double()
            h = b.high.as_double()
            low = b.low.as_double()
            c = b.close.as_double()
            assert low <= o <= h, f"open {o} outside [low {low}, high {h}]"
            assert low <= c <= h, f"close {c} outside [low {low}, high {h}]"
            assert b.volume.as_double() > 0


class TestTimestamps:
    def test_monotonic_timestamps(self) -> None:
        bars = generate_bars(pattern="flat", count=30, start_price=2400, seed=42)
        ts_list = [b.ts_init for b in bars]
        assert ts_list == sorted(ts_list)
        # Default: 1-minute spacing = 60_000_000_000 ns
        assert ts_list[1] - ts_list[0] == 60_000_000_000
