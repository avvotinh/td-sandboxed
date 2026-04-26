"""Unit tests for session_clock helpers (Epic 9 Phase 0, task P0.5).

Covers ``next_reset_at`` and ``previous_reset_at`` for a ``SessionConfig``,
including DST spring-forward / fall-back transitions in CET and
America/New_York.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.config.firm_profile import SessionConfig
from src.config.session_clock import next_reset_at, previous_reset_at


# ---------------------------------------------------------------------------
# next_reset_at — basic non-DST behaviour
# ---------------------------------------------------------------------------


class TestNextResetAtBasic:
    """Behaviour outside DST transitions."""

    def test_returns_utc_datetime(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        result = next_reset_at(session, now=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
        assert result.tzinfo == timezone.utc

    def test_utc_midnight_before_reset_returns_today_midnight(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        # At 23:00 UTC, next midnight is +1h
        now = datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)

    def test_utc_midnight_after_reset_returns_tomorrow(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        # At 00:01 UTC, next reset is +24h - 1min
        now = datetime(2026, 1, 15, 0, 1, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)

    def test_cet_midnight_in_winter_is_2300_utc(self):
        # CET in winter (CET = UTC+1) → local midnight = 23:00 UTC previous day
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        # At 14:00 UTC on a winter day, next local midnight is 23:00 UTC same day
        now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)

    def test_cet_midnight_in_summer_is_2200_utc(self):
        # CEST in summer (CEST = UTC+2) → local midnight = 22:00 UTC previous day
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)

    def test_returns_strict_future(self):
        # Equality case: now == next reset → must return the FOLLOWING reset
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        now = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 1, 16, 0, 0, tzinfo=timezone.utc)

    def test_non_midnight_reset_time(self):
        # Futures-style 17:00 New York reset
        session = SessionConfig(
            timezone="America/New_York",
            reset_time="17:00",
        )
        # At 15:00 ET (= 20:00 UTC in winter), next reset is 17:00 ET (= 22:00 UTC) same day
        now = datetime(2026, 1, 15, 20, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)

    def test_now_defaults_to_current_utc(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        result = next_reset_at(session)
        assert result.tzinfo == timezone.utc
        # Sanity: result is in the future (within 24h)
        delta = (result - datetime.now(timezone.utc)).total_seconds()
        assert 0 < delta <= 24 * 3600

    def test_naive_now_rejected(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        with pytest.raises(ValueError, match="timezone-aware"):
            next_reset_at(session, now=datetime(2026, 1, 15, 12, 0))


# ---------------------------------------------------------------------------
# next_reset_at — DST transitions
# ---------------------------------------------------------------------------


class TestNextResetAtDST:
    """Reset time stays anchored to LOCAL wall clock across DST transitions."""

    def test_cet_spring_forward_just_before_dst(self):
        # 2026 EU DST starts on Sun 29 Mar 2026 at 02:00 CET → jumps to 03:00 CEST.
        # If we're at 23:00 UTC on 28 Mar (= 00:00 CET 29 Mar), next reset
        # for daily-midnight session is +24h LOCAL = 23:00 UTC + 23h (DST eats 1h)
        # = 22:00 UTC on 29 Mar (which is 00:00 CEST 30 Mar).
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        # Just past midnight Berlin local on 29 Mar (DST day)
        now = datetime(2026, 3, 28, 23, 1, tzinfo=timezone.utc)  # = 00:01 CET 29 Mar
        result = next_reset_at(session, now=now)
        # Next local midnight = 30 Mar 00:00 CEST = 29 Mar 22:00 UTC
        assert result == datetime(2026, 3, 29, 22, 0, tzinfo=timezone.utc)

    def test_cet_fall_back_just_before_dst(self):
        # 2026 EU DST ends on Sun 25 Oct 2026 at 03:00 CEST → falls back to 02:00 CET.
        # At 23:01 UTC on 24 Oct (= 01:01 CEST 25 Oct), next local midnight is
        # 26 Oct 00:00 CET = 25 Oct 23:00 UTC (25h gap because DST adds an hour).
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        now = datetime(2026, 10, 24, 23, 1, tzinfo=timezone.utc)  # = 01:01 CEST 25 Oct
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)

    def test_ny_spring_forward(self):
        # US DST 2026 starts Sun 8 Mar 2026 at 02:00 EST → jumps to 03:00 EDT.
        # At 03:00 UTC on 8 Mar (= 22:00 EST 7 Mar), next local midnight is
        # 8 Mar 00:00 EST = 8 Mar 05:00 UTC.
        session = SessionConfig(timezone="America/New_York", reset_time="00:00")
        now = datetime(2026, 3, 8, 3, 0, tzinfo=timezone.utc)
        result = next_reset_at(session, now=now)
        assert result == datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# previous_reset_at
# ---------------------------------------------------------------------------


class TestPreviousResetAt:
    """previous_reset_at returns the most recent past reset boundary."""

    def test_returns_utc_datetime(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        result = previous_reset_at(session, now=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc))
        assert result.tzinfo == timezone.utc

    def test_strictly_before_now(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        result = previous_reset_at(session, now=now)
        assert result < now

    def test_utc_midnight_basic(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        now = datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = previous_reset_at(session, now=now)
        assert result == datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)

    def test_cet_midnight_winter(self):
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        # 14:00 UTC on 15 Jan = 15:00 CET → previous reset = 15 Jan 00:00 CET = 14 Jan 23:00 UTC
        now = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
        result = previous_reset_at(session, now=now)
        assert result == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)

    def test_cet_midnight_summer(self):
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        # 14:00 UTC on 15 Jul = 16:00 CEST → previous reset = 15 Jul 00:00 CEST = 14 Jul 22:00 UTC
        now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        result = previous_reset_at(session, now=now)
        assert result == datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)

    def test_now_at_reset_returns_that_reset(self):
        # By convention, when now == reset boundary, the boundary is "the most
        # recent past reset" inclusive — the new trading day has just begun.
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        now = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
        result = previous_reset_at(session, now=now)
        assert result == datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)

    def test_naive_now_rejected(self):
        session = SessionConfig(timezone="UTC", reset_time="00:00")
        with pytest.raises(ValueError, match="timezone-aware"):
            previous_reset_at(session, now=datetime(2026, 1, 15, 12, 0))


# ---------------------------------------------------------------------------
# Round-trip invariants
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Invariants that should hold across both helpers."""

    @pytest.mark.parametrize(
        "tz,reset_time,now",
        [
            ("UTC", "00:00", datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)),
            ("Europe/Berlin", "00:00", datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)),
            ("Europe/Berlin", "00:00", datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)),
            ("America/New_York", "17:00", datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)),
            ("Asia/Tokyo", "00:00", datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)),
        ],
    )
    def test_previous_strictly_le_now_lt_next(self, tz, reset_time, now):
        session = SessionConfig(timezone=tz, reset_time=reset_time)
        prev = previous_reset_at(session, now=now)
        nxt = next_reset_at(session, now=now)
        assert prev <= now < nxt
        # Gap between consecutive resets is 23h, 24h, or 25h (DST handling)
        gap_hours = (nxt - prev).total_seconds() / 3600
        assert gap_hours in (23.0, 24.0, 25.0)

    def test_next_after_previous_skips_a_full_day(self):
        # Outside DST transitions: next - previous == 24h
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        now = datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc)
        prev = previous_reset_at(session, now=now)
        nxt = next_reset_at(session, now=now)
        assert nxt - prev == timedelta(hours=24)

    def test_local_wall_clock_at_reset_is_constant(self):
        # The local wall clock at every reset boundary equals reset_time
        session = SessionConfig(timezone="Europe/Berlin", reset_time="00:00")
        tz = ZoneInfo("Europe/Berlin")
        for now in [
            datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 14, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 28, 23, 1, tzinfo=timezone.utc),  # near spring DST
            datetime(2026, 10, 24, 23, 1, tzinfo=timezone.utc),  # near fall DST
        ]:
            nxt = next_reset_at(session, now=now)
            local = nxt.astimezone(tz)
            assert (local.hour, local.minute) == (0, 0)
