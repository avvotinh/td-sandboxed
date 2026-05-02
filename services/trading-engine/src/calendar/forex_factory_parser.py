"""ForexFactory weekly-XML parser.

Story 10.8 — :class:`EconomicCalendarService` fetches the
``ff_calendar_thisweek.xml`` feed once a day and parses it through
this module into :class:`CalendarEvent` instances. The parser is
deliberately tolerant: ForexFactory's XML schema has drifted across
years (date format changes, optional fields appearing / vanishing),
so each ``<event>`` is processed independently and a malformed entry
is logged + skipped rather than aborting the whole feed.

Reference shape (sample):

    <weeklyevents>
      <event>
        <title>Non-Farm Employment Change</title>
        <country>USD</country>
        <date>10-31-2025</date>
        <time>8:30am</time>
        <impact>High</impact>
        <forecast>180K</forecast>
        <previous>140K</previous>
      </event>
      ...
    </weeklyevents>
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, time, timezone
from typing import Iterable

from .calendar_models import CalendarEvent

logger = logging.getLogger(__name__)


_DATE_FORMATS = (
    "%m-%d-%Y",  # ForexFactory canonical
    "%Y-%m-%d",  # ISO fallback
)


def parse_forex_factory_xml(
    raw: str | bytes,
    *,
    default_tz: timezone = timezone.utc,
) -> list[CalendarEvent]:
    """Parse a ForexFactory weekly XML payload.

    Args:
        raw: XML string or bytes (response body).
        default_tz: Timezone applied to events that don't carry one.
            ForexFactory's feed is published in EST/EDT historically;
            production callers SHOULD wrap fetch + parse in a step
            that converts to UTC. Tests typically pass UTC directly.

    Returns:
        List of :class:`CalendarEvent`. Malformed entries are logged
        and skipped; an entirely-malformed feed yields ``[]`` rather
        than raising — the rule fails open with a WARN.
    """
    try:
        root = _parse_root(raw)
    except ET.ParseError as exc:
        logger.warning("ForexFactory XML parse error: %s", exc)
        return []

    events: list[CalendarEvent] = []
    for elem in _iter_events(root):
        event = _parse_event(elem, default_tz=default_tz)
        if event is not None:
            events.append(event)
    return events


def _parse_root(raw: str | bytes) -> ET.Element:
    if isinstance(raw, bytes):
        return ET.fromstring(raw)
    return ET.fromstring(raw)


def _iter_events(root: ET.Element) -> Iterable[ET.Element]:
    """Yield every ``<event>`` child regardless of root tag.

    Some feeds use ``<weeklyevents>``, some use ``<calendar>``. We
    iterate over direct children and depth-1 children to be safe.
    """
    if root.tag.lower() == "event":
        yield root
        return
    for child in root:
        if child.tag.lower() == "event":
            yield child


def _parse_event(
    elem: ET.Element, *, default_tz: timezone
) -> CalendarEvent | None:
    title = _text(elem, "title")
    country = _text(elem, "country")
    date_raw = _text(elem, "date")
    time_raw = _text(elem, "time")
    impact = _text(elem, "impact") or "low"

    if not (title and country and date_raw):
        logger.debug(
            "ForexFactory parse: skipping event with missing core "
            "fields (title=%r country=%r date=%r)",
            title,
            country,
            date_raw,
        )
        return None

    start = _parse_datetime(date_raw, time_raw, default_tz=default_tz)
    if start is None:
        logger.debug(
            "ForexFactory parse: skipping event %r — bad date/time "
            "(date=%r time=%r)",
            title,
            date_raw,
            time_raw,
        )
        return None

    try:
        return CalendarEvent(
            title=title.strip(),
            country=country.strip(),
            start=start,
            impact=impact.strip(),
        )
    except ValueError as exc:
        logger.debug("ForexFactory parse: rejecting event %r — %s", title, exc)
        return None


def _text(elem: ET.Element, tag: str) -> str | None:
    """Return the text of the first ``<tag>`` child, or ``None``."""
    child = elem.find(tag)
    if child is None:
        return None
    text = (child.text or "").strip()
    return text or None


def _parse_datetime(
    date_raw: str,
    time_raw: str | None,
    *,
    default_tz: timezone,
) -> datetime | None:
    """Combine ``<date>`` + ``<time>`` into a tz-aware datetime.

    Returns ``None`` on unrecognised formats or "All Day" / "Tentative"
    times — those events have no precise blackout window.
    """
    parsed_date = _parse_date(date_raw)
    if parsed_date is None:
        return None

    parsed_time = _parse_time(time_raw) if time_raw else None
    if parsed_time is None:
        # All-day or tentative events — no blackout window.
        return None

    return datetime.combine(parsed_date, parsed_time, tzinfo=default_tz)


def _parse_date(raw: str) -> "datetime.date | None":
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(raw: str) -> time | None:
    raw = raw.strip().lower()
    if not raw or raw in {"all day", "tentative", "n/a"}:
        return None
    # ForexFactory uses ``8:30am`` / ``2:00pm``. Try AM/PM first then 24h.
    for fmt in ("%I:%M%p", "%H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt).time()
            return parsed
        except ValueError:
            continue
    return None
