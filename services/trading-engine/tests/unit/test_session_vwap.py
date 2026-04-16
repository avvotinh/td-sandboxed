"""Unit tests for SessionVWAP indicator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nautilus_trader.indicators.base import Indicator

from src.indicators.session_vwap import SessionVWAP


pytestmark = pytest.mark.unit


def _ts_ns(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Build a nanosecond timestamp from a UTC wall-clock time."""
    dt = datetime(year, month, day, hour, minute, tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


class TestSessionVWAPConstruction:
    def test_is_indicator_subclass(self) -> None:
        vwap = SessionVWAP()
        assert isinstance(vwap, Indicator)

    def test_default_tz_utc(self) -> None:
        vwap = SessionVWAP()
        assert vwap.tz == "UTC"

    def test_custom_tz(self) -> None:
        vwap = SessionVWAP(tz="America/New_York")
        assert vwap.tz == "America/New_York"

    def test_invalid_tz_raises(self) -> None:
        with pytest.raises(ValueError, match="tz|timezone"):
            SessionVWAP(tz="Not/A/Zone")


class TestSessionVWAPCumulation:
    """VWAP cumulates (price*volume) within a session."""

    def test_single_bar_vwap_equals_typical_price(self, make_bar) -> None:
        vwap = SessionVWAP()
        ts = _ts_ns(2026, 4, 17, 12, 0)
        # typical = (high + low + close) / 3 = (2405 + 2395 + 2400) / 3 = 2400
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts)
        )
        assert vwap.initialized is True
        assert vwap.value == pytest.approx(2400.0)

    def test_two_bars_same_session_cumulates(self, make_bar) -> None:
        vwap = SessionVWAP()
        ts1 = _ts_ns(2026, 4, 17, 12, 0)
        ts2 = _ts_ns(2026, 4, 17, 13, 0)
        # Bar 1: typical=2400, vol=100 → pv=240000, v=100
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts1)
        )
        # Bar 2: typical=2410, vol=200 → pv=482000, v=200
        # Cumulative pv=240000+482000=722000, v=300 → vwap=722000/300=2406.67
        vwap.handle_bar(
            make_bar(open=2408, high=2415, low=2405, close=2410, volume=200, ts=ts2)
        )
        assert vwap.value == pytest.approx(2406.6667, rel=1e-3)


class TestSessionVWAPSessionBoundary:
    """VWAP resets at session boundary (local-day change in configured tz)."""

    def test_resets_at_new_utc_day(self, make_bar) -> None:
        vwap = SessionVWAP(tz="UTC")
        ts_day1 = _ts_ns(2026, 4, 17, 23, 0)
        ts_day2 = _ts_ns(2026, 4, 18, 0, 30)
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts_day1)
        )
        vwap_day1 = vwap.value
        # New session — VWAP of second bar alone (not cumulated with first)
        vwap.handle_bar(
            make_bar(open=2500, high=2505, low=2495, close=2500, volume=100, ts=ts_day2)
        )
        # Should be typical(bar2) = 2500, not a cumulated value
        assert vwap.value == pytest.approx(2500.0)
        assert vwap_day1 != vwap.value

    def test_two_sessions_independent(self, make_bar) -> None:
        """Running session 2 alone yields same value as running session 1 then session 2."""
        vwap_a = SessionVWAP(tz="UTC")
        vwap_b = SessionVWAP(tz="UTC")

        # vwap_a: session 1 then session 2
        ts_s1 = _ts_ns(2026, 4, 17, 12, 0)
        ts_s2_a = _ts_ns(2026, 4, 18, 9, 0)
        ts_s2_b = _ts_ns(2026, 4, 18, 10, 0)

        vwap_a.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=500, ts=ts_s1)
        )
        vwap_a.handle_bar(
            make_bar(open=2500, high=2505, low=2495, close=2500, volume=100, ts=ts_s2_a)
        )
        vwap_a.handle_bar(
            make_bar(open=2510, high=2515, low=2505, close=2510, volume=100, ts=ts_s2_b)
        )

        # vwap_b: only session 2
        vwap_b.handle_bar(
            make_bar(open=2500, high=2505, low=2495, close=2500, volume=100, ts=ts_s2_a)
        )
        vwap_b.handle_bar(
            make_bar(open=2510, high=2515, low=2505, close=2510, volume=100, ts=ts_s2_b)
        )

        assert vwap_a.value == pytest.approx(vwap_b.value)


class TestSessionVWAPTimezone:
    """Different tz causes different session boundaries."""

    def test_ny_session_differs_from_utc_session(self, make_bar) -> None:
        """A bar at 23:00 UTC is still in the NY-day it started in (19:00 EDT)."""
        ts = _ts_ns(2026, 4, 17, 22, 0)  # 22:00 UTC = 18:00 EDT (17 Apr)
        ts_next = _ts_ns(2026, 4, 18, 2, 0)  # 02:00 UTC = 22:00 EDT (17 Apr still)

        # In NY timezone, both bars are same session (17 Apr EDT)
        vwap_ny = SessionVWAP(tz="America/New_York")
        vwap_ny.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts)
        )
        vwap_ny.handle_bar(
            make_bar(open=2410, high=2415, low=2405, close=2410, volume=100, ts=ts_next)
        )
        # Both cumulated — value is between 2400 and 2410
        assert 2400 < vwap_ny.value < 2415

        # In UTC, the two bars cross midnight → second bar resets
        vwap_utc = SessionVWAP(tz="UTC")
        vwap_utc.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts)
        )
        vwap_utc.handle_bar(
            make_bar(open=2410, high=2415, low=2405, close=2410, volume=100, ts=ts_next)
        )
        # Only second-bar typical after reset
        assert vwap_utc.value == pytest.approx(2410.0)


class TestSessionVWAPReset:
    def test_manual_reset_clears_state(self, make_bar) -> None:
        vwap = SessionVWAP()
        ts = _ts_ns(2026, 4, 17, 12, 0)
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts)
        )
        assert vwap.initialized is True
        vwap.reset()
        assert vwap.initialized is False
        assert vwap.value is None


class TestSessionVWAPEdgeCases:
    def test_zero_volume_bar_skipped(self, make_bar) -> None:
        """Zero-volume bars must not break the VWAP (no div-by-zero)."""
        vwap = SessionVWAP()
        ts = _ts_ns(2026, 4, 17, 12, 0)
        # First bar zero volume → indicator may stay uninitialised
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=0, ts=ts)
        )
        # Follow-up bar with volume → VWAP should match typical price
        ts2 = _ts_ns(2026, 4, 17, 13, 0)
        vwap.handle_bar(
            make_bar(open=2410, high=2415, low=2405, close=2410, volume=100, ts=ts2)
        )
        assert vwap.value == pytest.approx(2410.0)

    def test_initialized_cleared_on_session_boundary_with_zero_vol(
        self, make_bar
    ) -> None:
        """Regression: after session reset, the first bar of the new session
        having zero volume must leave ``initialized=False`` (not True with
        ``value=None``) so strategies never read stale state."""
        vwap = SessionVWAP(tz="UTC")
        # Session 1: positive volume → initialised
        ts_s1 = _ts_ns(2026, 4, 17, 12, 0)
        vwap.handle_bar(
            make_bar(open=2400, high=2405, low=2395, close=2400, volume=100, ts=ts_s1)
        )
        assert vwap.initialized is True

        # Cross into session 2 with a zero-volume bar.
        ts_s2 = _ts_ns(2026, 4, 18, 0, 30)
        vwap.handle_bar(
            make_bar(open=2500, high=2505, low=2495, close=2500, volume=0, ts=ts_s2)
        )
        assert vwap.value is None
        assert vwap.initialized is False, (
            "VWAP must not report initialized with no data in the new session"
        )

    def test_sub_minute_ns_timestamp_session_assignment(self, make_bar) -> None:
        """Regression: ns-precision timestamps must use integer arithmetic so
        23:59:59.999_999_999 stays in the current UTC day, not rollover."""
        vwap = SessionVWAP(tz="UTC")
        ts_end_of_day = _ts_ns(2026, 4, 17, 23, 59) + 59_999_999_999
        # This nanosecond is still 2026-04-17 UTC.
        vwap.handle_bar(
            make_bar(
                open=2400, high=2405, low=2395, close=2400,
                volume=100, ts=ts_end_of_day,
            )
        )
        # Next bar 1 ns later — crosses into 2026-04-18, triggers reset.
        ts_next_day = _ts_ns(2026, 4, 18, 0, 0)
        vwap.handle_bar(
            make_bar(
                open=2500, high=2505, low=2495, close=2500,
                volume=100, ts=ts_next_day,
            )
        )
        # Session reset should have happened — value reflects only bar 2.
        assert vwap.value == pytest.approx(2500.0)
