"""Session-aware clock helpers (Epic 9 Phase 0, task P0.5).

Computes daily-reset boundaries in UTC for a :class:`SessionConfig`,
correctly handling DST transitions. The reset time is anchored to the
LOCAL wall clock of the firm session, so the gap between two consecutive
resets can be 23h, 24h, or 25h on DST days.

Used by:
- ``DailySnapshotService`` to schedule snapshot collection
- ``DailyPnLRecalculator`` to bound the trading-day query window
- Anywhere code previously assumed "midnight UTC" but should follow
  the firm's local trading day instead
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .firm_profile import SessionConfig


def _require_tz_aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware (got naive datetime)")


def _parse_reset_time(reset_time: str) -> tuple[int, int]:
    hour_str, minute_str = reset_time.split(":")
    return int(hour_str), int(minute_str)


def next_reset_at(session: SessionConfig, now: datetime | None = None) -> datetime:
    """Return UTC datetime of the next daily reset strictly after ``now``.

    Anchored to the LOCAL wall clock of ``session.timezone`` — DST is
    absorbed into the gap between consecutive resets (23h or 25h on
    transition days).

    Args:
        now: Aware UTC (or any tz-aware) datetime. Defaults to current UTC.

    Returns:
        UTC ``datetime`` whose local representation in ``session.timezone``
        equals ``session.reset_time`` and is strictly greater than ``now``.

    Raises:
        ValueError: If ``now`` is naive (lacks tzinfo).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    _require_tz_aware(now)

    tz = ZoneInfo(session.timezone)
    hour, minute = _parse_reset_time(session.reset_time)
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def previous_reset_at(session: SessionConfig, now: datetime | None = None) -> datetime:
    """Return UTC datetime of the most recent reset at or before ``now``.

    Inclusive: when ``now`` falls exactly on a reset boundary, that
    boundary is returned (it is the start of the current trading day).

    Args:
        now: Aware UTC (or any tz-aware) datetime. Defaults to current UTC.

    Returns:
        UTC ``datetime`` whose local representation in ``session.timezone``
        equals ``session.reset_time`` and is less than or equal to ``now``.

    Raises:
        ValueError: If ``now`` is naive (lacks tzinfo).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    _require_tz_aware(now)

    tz = ZoneInfo(session.timezone)
    hour, minute = _parse_reset_time(session.reset_time)
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate > local_now:
        candidate = candidate - timedelta(days=1)
    return candidate.astimezone(timezone.utc)
