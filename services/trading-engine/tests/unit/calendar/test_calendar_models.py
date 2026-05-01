"""Tests for :class:`CalendarEvent` + :class:`EventIndex` (story 10.8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.calendar.calendar_models import (
    HIGH_IMPACT,
    CalendarEvent,
    EventIndex,
)


UTC = timezone.utc


def _event(
    *,
    title: str = "NFP",
    country: str = "USD",
    start: datetime | None = None,
    impact: str = "high",
    symbols: tuple[str, ...] = (),
) -> CalendarEvent:
    return CalendarEvent(
        title=title,
        country=country,
        start=start or datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
        impact=impact,
        symbols=symbols,
    )


# -------------------------------------------------------------------------
# CalendarEvent
# -------------------------------------------------------------------------


class TestCalendarEvent:
    def test_naive_start_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            CalendarEvent(
                title="X",
                country="USD",
                start=datetime(2026, 5, 1, 12, 30),  # naive
                impact="high",
            )

    def test_impact_lowercased(self) -> None:
        ev = _event(impact="HIGH")
        assert ev.impact == "high"

    def test_symbols_uppercased(self) -> None:
        ev = _event(symbols=("xauusd", "eurusd"))
        assert ev.symbols == ("XAUUSD", "EURUSD")

    def test_blank_symbols_dropped(self) -> None:
        ev = _event(symbols=("", "  ", "XAUUSD"))
        assert ev.symbols == ("XAUUSD",)

    def test_affects_symbol_explicit_set(self) -> None:
        ev = _event(symbols=("XAUUSD", "EURUSD"))
        assert ev.affects_symbol("xauusd")
        assert ev.affects_symbol("EURUSD")
        assert not ev.affects_symbol("GBPJPY")

    def test_affects_symbol_country_fallback(self) -> None:
        ev = _event(country="USD")
        assert ev.affects_symbol("EURUSD")
        assert ev.affects_symbol("XAUUSD")
        assert not ev.affects_symbol("GBPJPY")

    def test_affects_symbol_empty_input(self) -> None:
        ev = _event()
        assert not ev.affects_symbol("")


# -------------------------------------------------------------------------
# EventIndex.active_events_at — happy paths
# -------------------------------------------------------------------------


class TestActiveAt:
    @pytest.fixture
    def index(self) -> EventIndex:
        # NFP at 12:30 + CPI at 14:00 + minor at 16:00
        return EventIndex(
            [
                _event(title="NFP", start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC), impact="high"),
                _event(
                    title="CPI",
                    country="USD",
                    start=datetime(2026, 5, 1, 14, 0, tzinfo=UTC),
                    impact="high",
                ),
                _event(
                    title="Minor",
                    country="EUR",
                    start=datetime(2026, 5, 1, 16, 0, tzinfo=UTC),
                    impact="low",
                ),
            ]
        )

    def test_inside_window_before(self, index: EventIndex) -> None:
        # 12:27 — 3 minutes before NFP at 12:30, default 5-min before window
        now = datetime(2026, 5, 1, 12, 27, tzinfo=UTC)
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        titles = [e.title for e in active]
        assert "NFP" in titles
        assert "CPI" not in titles  # 1.5h away

    def test_inside_window_after(self, index: EventIndex) -> None:
        # 12:33 — 3 minutes after NFP at 12:30
        now = datetime(2026, 5, 1, 12, 33, tzinfo=UTC)
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        assert any(e.title == "NFP" for e in active)

    def test_outside_window(self, index: EventIndex) -> None:
        now = datetime(2026, 5, 1, 13, 0, tzinfo=UTC)  # 30min after NFP
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        assert active == []

    def test_window_boundaries_inclusive(self, index: EventIndex) -> None:
        # Exactly at start − before
        now = datetime(2026, 5, 1, 12, 25, tzinfo=UTC)
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        assert any(e.title == "NFP" for e in active)
        # Exactly at start + after
        now = datetime(2026, 5, 1, 12, 35, tzinfo=UTC)
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        assert any(e.title == "NFP" for e in active)


class TestImpactFilter:
    def test_high_impact_only(self) -> None:
        index = EventIndex(
            [
                _event(title="NFP", start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC), impact="high"),
                _event(title="Minor", start=datetime(2026, 5, 1, 12, 32, tzinfo=UTC), impact="low"),
            ]
        )
        now = datetime(2026, 5, 1, 12, 31, tzinfo=UTC)
        active = index.active_events_at(
            now,
            minutes_before=5,
            minutes_after=5,
            impact_levels=HIGH_IMPACT,
        )
        titles = [e.title for e in active]
        assert "NFP" in titles
        assert "Minor" not in titles


class TestSymbolFilter:
    def test_only_returns_events_affecting_the_symbol(self) -> None:
        index = EventIndex(
            [
                _event(
                    title="NFP",
                    country="USD",
                    start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
                ),
                _event(
                    title="ECB",
                    country="EUR",
                    start=datetime(2026, 5, 1, 12, 31, tzinfo=UTC),
                ),
            ]
        )
        now = datetime(2026, 5, 1, 12, 32, tzinfo=UTC)
        usd_active = index.active_events_at(
            now, minutes_before=5, minutes_after=5, symbol="XAUUSD"
        )
        eur_active = index.active_events_at(
            now, minutes_before=5, minutes_after=5, symbol="EURJPY"
        )
        assert [e.title for e in usd_active] == ["NFP"]
        assert [e.title for e in eur_active] == ["ECB"]


# -------------------------------------------------------------------------
# EventIndex.next_event_after
# -------------------------------------------------------------------------


class TestNextEventAfter:
    def test_returns_chronologically_first(self) -> None:
        index = EventIndex(
            [
                _event(title="NFP", start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC)),
                _event(title="CPI", start=datetime(2026, 5, 1, 14, 0, tzinfo=UTC)),
            ]
        )
        nxt = index.next_event_after(
            datetime(2026, 5, 1, 13, 0, tzinfo=UTC)
        )
        assert nxt is not None and nxt.title == "CPI"

    def test_returns_none_when_no_more_events(self) -> None:
        index = EventIndex(
            [_event(start=datetime(2026, 5, 1, 12, 30, tzinfo=UTC))]
        )
        nxt = index.next_event_after(
            datetime(2026, 5, 1, 13, 0, tzinfo=UTC)
        )
        assert nxt is None

    def test_filters_by_impact(self) -> None:
        index = EventIndex(
            [
                _event(title="Minor", start=datetime(2026, 5, 1, 13, 0, tzinfo=UTC), impact="low"),
                _event(title="CPI", start=datetime(2026, 5, 1, 14, 0, tzinfo=UTC), impact="high"),
            ]
        )
        nxt = index.next_event_after(
            datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
            impact_levels=HIGH_IMPACT,
        )
        assert nxt is not None and nxt.title == "CPI"


# -------------------------------------------------------------------------
# Argument validation
# -------------------------------------------------------------------------


class TestValidation:
    def test_naive_now_rejected(self) -> None:
        index = EventIndex([_event()])
        with pytest.raises(ValueError, match="timezone-aware"):
            index.active_events_at(
                datetime(2026, 5, 1, 12, 30),  # naive
                minutes_before=5,
                minutes_after=5,
            )

    def test_negative_minutes_rejected(self) -> None:
        index = EventIndex([_event()])
        now = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
        with pytest.raises(ValueError, match="non-negative"):
            index.active_events_at(now, minutes_before=-1, minutes_after=5)
        with pytest.raises(ValueError, match="non-negative"):
            index.active_events_at(now, minutes_before=5, minutes_after=-1)


class TestEmptyIndex:
    def test_empty_index_returns_no_active_events(self) -> None:
        index = EventIndex([])
        active = index.active_events_at(
            datetime(2026, 5, 1, 12, 30, tzinfo=UTC),
            minutes_before=5,
            minutes_after=5,
        )
        assert active == []

    def test_empty_index_next_event_returns_none(self) -> None:
        index = EventIndex([])
        nxt = index.next_event_after(
            datetime(2026, 5, 1, 12, 30, tzinfo=UTC)
        )
        assert nxt is None


class TestScale:
    """Sanity check: O(log N) bisect handles 10k events without timing out."""

    def test_lookup_in_large_index(self) -> None:
        base = datetime(2026, 1, 1, tzinfo=UTC)
        events = [
            _event(
                title=f"E{i}",
                start=base + timedelta(minutes=i),
                impact="high",
            )
            for i in range(10_000)
        ]
        index = EventIndex(events)
        # Look up a moment near the middle
        now = base + timedelta(minutes=5_000)
        active = index.active_events_at(
            now, minutes_before=5, minutes_after=5
        )
        # 11 events overlap the [now-5, now+5] window
        assert 5 <= len(active) <= 15
