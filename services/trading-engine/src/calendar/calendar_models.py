"""Economic-calendar data model + fast lookup index.

Story 10.8 — :class:`NewsBlackoutRule` consults the index to decide
whether the current moment falls inside a blackout window around a
high-impact news event (NFP, FOMC, CPI, …). The index is built once
per calendar refresh and queried on every order, so the lookup must
be cheap.

A binary search over a sorted-by-start-time list (``bisect``) gives
O(log N) on the lower bound and a constant tail-walk over the few
events whose ``[start − before, start + after]`` window can plausibly
overlap "now". For ForexFactory's typical ~50 events/week this is
overkill in absolute terms, but the algorithm is well-known and easy
to test, and it stays cheap if a calendar source ever produces
hundreds of events.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable


# ForexFactory and most economic-calendar feeds use the labels low /
# medium / high (sometimes capitalised). Normalise to lowercase
# everywhere so set membership is case-insensitive.
def _normalise_impact(impact: str) -> str:
    return impact.strip().lower()


@dataclass(frozen=True)
class CalendarEvent:
    """A single economic-calendar event (e.g. NFP release).

    Attributes:
        title: Human-readable event name (e.g. ``"Non-Farm Payrolls"``).
        country: Currency / country code (``"USD"``, ``"EUR"``, …).
        start: Event timestamp in UTC. ``datetime.tzinfo`` MUST be set
            — naive datetimes are rejected at construction so the
            blackout window is unambiguous.
        impact: Impact level — ``low`` / ``medium`` / ``high``
            (case-insensitive on input; lowercased here).
        symbols: Optional explicit symbol mapping. Falls back to
            ``country`` derivation when empty (e.g. ``USD`` → matches
            symbols containing ``USD``).
    """

    title: str
    country: str
    start: datetime
    impact: str
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError(
                f"CalendarEvent.start must be timezone-aware (got naive "
                f"datetime for event {self.title!r})"
            )
        # Normalise impact in-place via object.__setattr__ since the
        # dataclass is frozen.
        object.__setattr__(self, "impact", _normalise_impact(self.impact))
        object.__setattr__(
            self,
            "symbols",
            tuple(s.strip().upper() for s in self.symbols if s.strip()),
        )

    def affects_symbol(self, symbol: str) -> bool:
        """Does this event impact ``symbol``?

        Decision rules:
        - If ``self.symbols`` is non-empty, exact-set membership.
        - Otherwise, simple substring on the country code (NFP for USD
          should block XAUUSD, EURUSD, etc.). Forex pairs encode both
          legs; commodities priced in USD typically end with ``USD``.
        """
        if not symbol:
            return False
        upper = symbol.strip().upper()
        if self.symbols:
            return upper in self.symbols
        return self.country.strip().upper() in upper


class EventIndex:
    """Sorted, queryable view over a list of :class:`CalendarEvent`.

    Construct once after every calendar refresh; query as often as
    needed. Immutable from the caller's perspective — to update the
    index, build a new one and atomically swap.
    """

    def __init__(self, events: Iterable[CalendarEvent]) -> None:
        self._events: list[CalendarEvent] = sorted(
            events, key=lambda e: e.start
        )
        self._starts: list[datetime] = [e.start for e in self._events]

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> list[CalendarEvent]:
        return list(self._events)

    def active_events_at(
        self,
        now: datetime,
        *,
        minutes_before: int,
        minutes_after: int,
        impact_levels: frozenset[str] | None = None,
        symbol: str | None = None,
    ) -> list[CalendarEvent]:
        """Return events whose blackout window contains ``now``.

        Args:
            now: Reference time. Must be timezone-aware.
            minutes_before: Minutes before ``event.start`` the blackout
                begins.
            minutes_after: Minutes after ``event.start`` the blackout
                ends.
            impact_levels: When set, only return events whose
                (lowercased) impact is in this set.
            symbol: When set, only return events that affect the given
                trading symbol (see :meth:`CalendarEvent.affects_symbol`).
        """
        if now.tzinfo is None:
            raise ValueError("active_events_at: now must be timezone-aware")
        if minutes_before < 0 or minutes_after < 0:
            raise ValueError(
                "minutes_before / minutes_after must be non-negative"
            )

        before_delta = timedelta(minutes=minutes_before)
        after_delta = timedelta(minutes=minutes_after)

        # Window: an event at start S is active for ``now`` when
        # S - before <= now <= S + after, equivalently
        # now - after <= S <= now + before.
        lo_start = now - after_delta
        hi_start = now + before_delta

        # Bisect to the lo bound — events before this can't possibly be
        # active given they ended more than ``minutes_after`` ago.
        lo_idx = bisect.bisect_left(self._starts, lo_start)
        hi_idx = bisect.bisect_right(self._starts, hi_start)

        candidates = self._events[lo_idx:hi_idx]
        out: list[CalendarEvent] = []
        for event in candidates:
            if impact_levels and event.impact not in impact_levels:
                continue
            if symbol is not None and not event.affects_symbol(symbol):
                continue
            out.append(event)
        return out

    def next_event_after(
        self,
        ts: datetime,
        *,
        impact_levels: frozenset[str] | None = None,
    ) -> CalendarEvent | None:
        """Return the first event scheduled strictly after ``ts``.

        Useful for diagnostics — surfaces "next blackout starts at
        14:30 UTC" in the rule's WARN message.
        """
        if ts.tzinfo is None:
            raise ValueError("next_event_after: ts must be timezone-aware")
        idx = bisect.bisect_right(self._starts, ts)
        for event in self._events[idx:]:
            if impact_levels and event.impact not in impact_levels:
                continue
            return event
        return None


# Useful default — lets callers default the impact filter without
# touching frozen-set construction at the call site.
HIGH_IMPACT: frozenset[str] = frozenset({"high"})


def utc_now() -> datetime:
    """Tz-aware UTC now. Wrapped so tests can monkey-patch a fake clock."""
    return datetime.now(timezone.utc)
