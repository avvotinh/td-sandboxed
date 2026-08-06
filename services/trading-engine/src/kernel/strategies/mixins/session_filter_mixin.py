"""Trading-session time filter with DST-safe timezone handling.

Uses ``zoneinfo`` from the standard library (Py3.9+) so DST transitions
are resolved against the system tz database without an external dep.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


class SessionFilterMixin:
    """Mixin providing trading-session window predicates.

    All methods are static and reject naive timestamps to prevent silent
    timezone assumption bugs.
    """

    @staticmethod
    def in_session(
        ts: datetime,
        session_start: time,
        session_end: time,
        tz: str = "UTC",
    ) -> bool:
        """Return True iff ``ts`` (in ``tz``) is within [start, end] inclusive.

        Overnight sessions are supported: when ``session_start > session_end``,
        the window wraps midnight (e.g. 22:00 → 06:00).
        """
        local_time = SessionFilterMixin._to_local_time(ts, tz)
        if session_start <= session_end:
            return session_start <= local_time <= session_end
        # Overnight wrap.
        return local_time >= session_start or local_time <= session_end

    @staticmethod
    def session_id(ts: datetime, tz: str = "UTC") -> str:
        """Return a YYYY-MM-DD identifier for grouping bars by trading day."""
        if ts.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware")
        return ts.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")

    @staticmethod
    def _to_local_time(ts: datetime, tz: str) -> time:
        if ts.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware")
        return ts.astimezone(ZoneInfo(tz)).time()
