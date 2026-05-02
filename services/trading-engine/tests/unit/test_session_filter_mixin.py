"""Unit tests for SessionFilterMixin."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from src.strategies.mixins.session_filter_mixin import SessionFilterMixin


pytestmark = pytest.mark.unit


class TestInSession:
    """Standard session-window membership."""

    def test_inside_session_utc(self) -> None:
        # 12:00 UTC inside London 08:00-17:00 in winter (no DST)
        ts = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )

    def test_outside_session_too_early(self) -> None:
        ts = datetime(2026, 1, 15, 6, 0, tzinfo=UTC)
        assert not SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )

    def test_outside_session_too_late(self) -> None:
        ts = datetime(2026, 1, 15, 18, 0, tzinfo=UTC)
        assert not SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )

    def test_inclusive_at_session_start(self) -> None:
        ts = datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )

    def test_inclusive_at_session_end(self) -> None:
        ts = datetime(2026, 1, 15, 17, 0, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(17, 0),
            tz="Europe/London",
        )


class TestDstHandling:
    """DST transitions must not silently shift session boundaries."""

    def test_london_after_dst_spring_forward(self) -> None:
        # March 29, 2026 is the UK DST start (last Sunday in March)
        # 08:30 BST = 07:30 UTC
        ts_in_session = datetime(2026, 4, 1, 7, 30, tzinfo=UTC)  # 08:30 BST
        assert SessionFilterMixin.in_session(
            ts_in_session,
            session_start=time(8, 0),
            session_end=time(16, 30),
            tz="Europe/London",
        )

    def test_london_before_dst_winter(self) -> None:
        # February — no DST. 08:30 GMT = 08:30 UTC
        ts_in_session = datetime(2026, 2, 15, 8, 30, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts_in_session,
            session_start=time(8, 0),
            session_end=time(16, 30),
            tz="Europe/London",
        )

    def test_london_07_30_utc_winter_outside_session(self) -> None:
        # 07:30 UTC in winter = 07:30 GMT — before 08:00 session start
        ts = datetime(2026, 2, 15, 7, 30, tzinfo=UTC)
        assert not SessionFilterMixin.in_session(
            ts,
            session_start=time(8, 0),
            session_end=time(16, 30),
            tz="Europe/London",
        )


class TestOvernightSession:
    """Sessions that wrap midnight (Asia/Sydney crossing UTC midnight)."""

    def test_inside_overnight_session_late_evening(self) -> None:
        # Session 22:00 → 06:00 next day, ts at 23:00 → in session
        ts = datetime(2026, 1, 15, 23, 0, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts,
            session_start=time(22, 0),
            session_end=time(6, 0),
            tz="UTC",
        )

    def test_inside_overnight_session_early_morning(self) -> None:
        # Same session, ts at 03:00 next day → in session
        ts = datetime(2026, 1, 16, 3, 0, tzinfo=UTC)
        assert SessionFilterMixin.in_session(
            ts,
            session_start=time(22, 0),
            session_end=time(6, 0),
            tz="UTC",
        )

    def test_outside_overnight_session(self) -> None:
        # 12:00 UTC midday → outside 22:00-06:00 window
        ts = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        assert not SessionFilterMixin.in_session(
            ts,
            session_start=time(22, 0),
            session_end=time(6, 0),
            tz="UTC",
        )


class TestTimezoneNaiveRejected:
    """Naive timestamps must raise — no silent assumption."""

    def test_naive_timestamp_raises(self) -> None:
        ts = datetime(2026, 1, 15, 12, 0)  # no tz
        with pytest.raises(ValueError, match="timezone-aware"):
            SessionFilterMixin.in_session(
                ts,
                session_start=time(8, 0),
                session_end=time(17, 0),
                tz="UTC",
            )


class TestSessionId:
    """Session ID grouping for ORB."""

    def test_session_id_groups_same_local_day(self) -> None:
        ts1 = datetime(2026, 4, 17, 8, 30, tzinfo=UTC)
        ts2 = datetime(2026, 4, 17, 16, 0, tzinfo=UTC)
        assert SessionFilterMixin.session_id(ts1, "Europe/London") == SessionFilterMixin.session_id(
            ts2, "Europe/London"
        )

    def test_session_id_differs_across_local_days(self) -> None:
        ts1 = datetime(2026, 4, 17, 23, 0, tzinfo=UTC)
        ts2 = datetime(2026, 4, 18, 1, 0, tzinfo=UTC)
        assert SessionFilterMixin.session_id(ts1, "UTC") != SessionFilterMixin.session_id(
            ts2, "UTC"
        )

    def test_session_id_naive_raises(self) -> None:
        ts = datetime(2026, 4, 17, 12, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            SessionFilterMixin.session_id(ts, "UTC")
