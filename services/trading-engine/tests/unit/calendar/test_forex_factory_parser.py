"""Tests for the ForexFactory weekly XML parser (story 10.8)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.calendar.forex_factory_parser import parse_forex_factory_xml


UTC = timezone.utc


def _xml(events: str) -> str:
    return f"<weeklyevents>{events}</weeklyevents>"


def _event_xml(
    *,
    title: str = "Non-Farm Employment Change",
    country: str = "USD",
    date: str = "10-31-2025",
    time: str = "8:30am",
    impact: str = "High",
) -> str:
    return (
        "<event>"
        f"<title>{title}</title>"
        f"<country>{country}</country>"
        f"<date>{date}</date>"
        f"<time>{time}</time>"
        f"<impact>{impact}</impact>"
        "</event>"
    )


# -------------------------------------------------------------------------
# Happy path
# -------------------------------------------------------------------------


class TestHappyPath:
    def test_single_event(self) -> None:
        events = parse_forex_factory_xml(_xml(_event_xml()))
        assert len(events) == 1
        ev = events[0]
        assert ev.title == "Non-Farm Employment Change"
        assert ev.country == "USD"
        assert ev.impact == "high"
        assert ev.start == datetime(2025, 10, 31, 8, 30, tzinfo=UTC)

    def test_multiple_events(self) -> None:
        body = (
            _event_xml(title="NFP", date="10-31-2025", time="8:30am")
            + _event_xml(title="CPI", date="11-13-2025", time="2:00pm")
        )
        events = parse_forex_factory_xml(_xml(body))
        assert [e.title for e in events] == ["NFP", "CPI"]

    def test_iso_date_format_accepted(self) -> None:
        events = parse_forex_factory_xml(
            _xml(_event_xml(date="2025-10-31"))
        )
        assert len(events) == 1
        assert events[0].start.date().isoformat() == "2025-10-31"

    def test_24h_time_format_accepted(self) -> None:
        events = parse_forex_factory_xml(
            _xml(_event_xml(time="14:00"))
        )
        assert len(events) == 1
        assert events[0].start.hour == 14

    def test_pm_time_parsed(self) -> None:
        events = parse_forex_factory_xml(
            _xml(_event_xml(time="2:00pm"))
        )
        assert events[0].start.hour == 14

    def test_bytes_input(self) -> None:
        body = _xml(_event_xml()).encode("utf-8")
        events = parse_forex_factory_xml(body)
        assert len(events) == 1


# -------------------------------------------------------------------------
# Tolerant parsing
# -------------------------------------------------------------------------


class TestTolerance:
    def test_malformed_xml_returns_empty_not_raises(self) -> None:
        events = parse_forex_factory_xml("<not-xml")
        assert events == []

    def test_missing_core_fields_skipped(self) -> None:
        body = (
            "<event><title>Has only title</title></event>"
            + _event_xml(title="OK")
        )
        events = parse_forex_factory_xml(_xml(body))
        assert [e.title for e in events] == ["OK"]

    def test_all_day_event_skipped(self) -> None:
        body = _event_xml(title="Bank Holiday", time="All Day")
        events = parse_forex_factory_xml(_xml(body))
        assert events == []

    def test_tentative_time_skipped(self) -> None:
        body = _event_xml(title="OPEC Meeting", time="Tentative")
        events = parse_forex_factory_xml(_xml(body))
        assert events == []

    def test_unknown_date_format_skipped(self) -> None:
        body = _event_xml(date="31 Oct 2025")
        events = parse_forex_factory_xml(_xml(body))
        assert events == []

    def test_one_bad_event_does_not_kill_rest(self) -> None:
        body = (
            _event_xml(title="OK1")
            + _event_xml(title="Bad", date="not-a-date")
            + _event_xml(title="OK2")
        )
        events = parse_forex_factory_xml(_xml(body))
        assert [e.title for e in events] == ["OK1", "OK2"]

    def test_empty_feed(self) -> None:
        events = parse_forex_factory_xml(_xml(""))
        assert events == []

    def test_missing_impact_defaults_to_low(self) -> None:
        body = (
            "<event>"
            "<title>NoImpact</title>"
            "<country>USD</country>"
            "<date>10-31-2025</date>"
            "<time>8:30am</time>"
            "</event>"
        )
        events = parse_forex_factory_xml(_xml(body))
        assert len(events) == 1
        assert events[0].impact == "low"


# -------------------------------------------------------------------------
# Root flexibility
# -------------------------------------------------------------------------


class TestRootFlexibility:
    def test_calendar_root_also_works(self) -> None:
        body = f"<calendar>{_event_xml()}</calendar>"
        events = parse_forex_factory_xml(body)
        assert len(events) == 1

    def test_root_is_event_itself(self) -> None:
        events = parse_forex_factory_xml(_event_xml())
        assert len(events) == 1
