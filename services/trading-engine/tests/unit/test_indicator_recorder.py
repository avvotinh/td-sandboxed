"""Unit tests for IndicatorRecorder (Contract v2 P1, gap G6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.backtesting.recorder.indicator_recorder import (
    IndicatorRecorder,
    ns_to_utc,
)
from src.backtesting.result import IndicatorSeries

pytestmark = pytest.mark.unit


T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _t(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


class TestRegister:
    def test_register_then_record_then_to_series(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register(
            "st_up", title="Supertrend (up)", pane="overlay", color="#26a69a"
        )
        recorder.record("st_up", _t(0), 2000.5)
        recorder.record("st_up", _t(5), 2001.0)

        [series] = recorder.to_series()
        assert isinstance(series, IndicatorSeries)
        assert series.key == "st_up"
        assert series.title == "Supertrend (up)"
        assert series.pane == "overlay"
        assert series.color == "#26a69a"
        assert series.points == ((_t(0), 2000.5), (_t(5), 2001.0))
        assert series.levels == ()

    def test_is_registered(self) -> None:
        recorder = IndicatorRecorder()
        assert not recorder.is_registered("rsi")
        recorder.register("rsi", title="RSI", pane="rsi", color="#ab47bc")
        assert recorder.is_registered("rsi")

    def test_reregister_is_noop_keeping_first_metadata(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register("x", title="First", pane="overlay", color="#111111")
        recorder.register("x", title="Second", pane="rsi", color="#222222")
        [series] = recorder.to_series()
        assert series.title == "First"
        assert series.pane == "overlay"

    def test_levels_are_preserved(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register(
            "rsi", title="RSI", pane="rsi", color="#ab47bc", levels=(0.3, 0.7)
        )
        [series] = recorder.to_series()
        assert series.levels == (0.3, 0.7)


class TestRecord:
    def test_none_value_is_silently_skipped(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register("x", title="X", pane="overlay", color="#000000")
        recorder.record("x", _t(0), None)
        recorder.record("x", _t(5), 1.5)
        [series] = recorder.to_series()
        assert series.points == ((_t(5), 1.5),)

    def test_same_ts_last_write_wins(self) -> None:
        """BE move + trail ratchet on one bar collapse to the last value."""
        recorder = IndicatorRecorder()
        recorder.register("x", title="X", pane="overlay", color="#000000")
        recorder.record("x", _t(0), 1.0)
        recorder.record("x", _t(0), 2.0)
        [series] = recorder.to_series()
        assert series.points == ((_t(0), 2.0),)

    def test_unregistered_key_fails_fast(self) -> None:
        recorder = IndicatorRecorder()
        with pytest.raises(KeyError, match="not registered"):
            recorder.record("ghost", _t(0), 1.0)

    def test_values_are_coerced_to_float(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register("x", title="X", pane="overlay", color="#000000")
        recorder.record("x", _t(0), 3)
        [series] = recorder.to_series()
        assert series.points == ((_t(0), 3.0),)
        assert isinstance(series.points[0][1], float)


class TestToSeriesOrdering:
    def test_series_follow_registration_order(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register("b", title="B", pane="overlay", color="#000000")
        recorder.register("a", title="A", pane="overlay", color="#000000")
        assert [s.key for s in recorder.to_series()] == ["b", "a"]

    def test_points_sorted_chronologically(self) -> None:
        recorder = IndicatorRecorder()
        recorder.register("x", title="X", pane="overlay", color="#000000")
        recorder.record("x", _t(10), 2.0)
        recorder.record("x", _t(0), 1.0)
        [series] = recorder.to_series()
        assert series.points == ((_t(0), 1.0), (_t(10), 2.0))

    def test_empty_recorder_yields_no_series(self) -> None:
        assert IndicatorRecorder().to_series() == ()


class TestNsToUtc:
    def test_converts_nautilus_ns_to_aware_utc(self) -> None:
        ts = ns_to_utc(1_700_000_000_000_000_000)
        assert ts == datetime.fromtimestamp(1_700_000_000, tz=UTC)
        assert ts.tzinfo is not None
