"""Tests for :class:`EconomicCalendarService` (story 10.8)."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.calendar.calendar_models import CalendarEvent
from src.calendar.economic_calendar_service import (
    DEFAULT_REDIS_KEY_PREFIX,
    EconomicCalendarService,
    _event_from_dict,
    _event_to_dict,
)


UTC = timezone.utc


def _xml_with_events(events: list[tuple[str, str, str, str]]) -> str:
    """events = list of (title, country, date_str, time_str). All high impact."""
    body = "".join(
        f"<event>"
        f"<title>{t}</title>"
        f"<country>{c}</country>"
        f"<date>{d}</date>"
        f"<time>{ts}</time>"
        f"<impact>High</impact>"
        f"</event>"
        for t, c, d, ts in events
    )
    return f"<weeklyevents>{body}</weeklyevents>"


def _redis_manager() -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    client.setex = AsyncMock()
    client.get = AsyncMock(return_value=None)
    manager = MagicMock()
    manager.client = client
    return manager, client


# -------------------------------------------------------------------------
# Snapshot lifecycle
# -------------------------------------------------------------------------


class TestRefreshOnce:
    @pytest.mark.asyncio
    async def test_fetch_parse_into_snapshot(self) -> None:
        xml = _xml_with_events([
            ("NFP", "USD", "10-31-2025", "8:30am"),
            ("CPI", "USD", "11-13-2025", "2:00pm"),
        ])

        def _fetcher() -> str:
            return xml

        svc = EconomicCalendarService(fetcher=_fetcher)
        index = await svc.refresh_once()
        assert len(index) == 2
        titles = [e.title for e in index.events]
        assert titles == ["NFP", "CPI"]
        assert svc.snapshot_built_at is not None

    @pytest.mark.asyncio
    async def test_async_fetcher_supported(self) -> None:
        xml = _xml_with_events([("NFP", "USD", "10-31-2025", "8:30am")])

        async def _fetcher() -> str:
            return xml

        svc = EconomicCalendarService(fetcher=_fetcher)
        index = await svc.refresh_once()
        assert len(index) == 1


# -------------------------------------------------------------------------
# Caching
# -------------------------------------------------------------------------


class TestRedisCache:
    @pytest.mark.asyncio
    async def test_successful_fetch_writes_redis_cache(self) -> None:
        xml = _xml_with_events([("NFP", "USD", "10-31-2025", "8:30am")])
        manager, client = _redis_manager()

        svc = EconomicCalendarService(
            fetcher=lambda: xml, redis_manager=manager
        )
        await svc.refresh_once()

        client.setex.assert_awaited_once()
        args = client.setex.call_args.args
        assert args[0].startswith(DEFAULT_REDIS_KEY_PREFIX + ":")
        assert args[1] == 26 * 60 * 60  # default TTL
        # Payload is parseable JSON of events
        payload = json.loads(args[2])
        assert payload[0]["title"] == "NFP"

    @pytest.mark.asyncio
    async def test_fetch_failure_falls_back_to_redis_cache(self) -> None:
        manager, client = _redis_manager()
        cached_event = _event_to_dict(
            CalendarEvent(
                title="CACHED-NFP",
                country="USD",
                start=datetime(2025, 10, 31, 8, 30, tzinfo=UTC),
                impact="high",
            )
        )
        client.get = AsyncMock(return_value=json.dumps([cached_event]))

        def _broken() -> str:
            raise RuntimeError("network down")

        svc = EconomicCalendarService(
            fetcher=_broken, redis_manager=manager
        )
        index = await svc.refresh_once()
        assert len(index) == 1
        assert index.events[0].title == "CACHED-NFP"

    @pytest.mark.asyncio
    async def test_cache_miss_then_yesterday_attempted(self) -> None:
        manager, client = _redis_manager()

        async def _get_yesterday(key: str) -> str | None:
            today_key = (
                f"{DEFAULT_REDIS_KEY_PREFIX}:{date.today().isoformat()}"
            )
            if key == today_key:
                return None
            # Yesterday key returns one event
            return json.dumps([
                _event_to_dict(
                    CalendarEvent(
                        title="YESTERDAY",
                        country="USD",
                        start=datetime(2025, 10, 31, 8, 30, tzinfo=UTC),
                        impact="high",
                    )
                )
            ])

        client.get = AsyncMock(side_effect=_get_yesterday)

        def _broken() -> str:
            raise RuntimeError("offline")

        svc = EconomicCalendarService(
            fetcher=_broken, redis_manager=manager
        )
        index = await svc.refresh_once()
        assert len(index) == 1
        assert index.events[0].title == "YESTERDAY"


# -------------------------------------------------------------------------
# Static fallback
# -------------------------------------------------------------------------


class TestFallbackFile:
    @pytest.mark.asyncio
    async def test_fetch_and_redis_fail_uses_fallback(
        self, tmp_path: Path
    ) -> None:
        fallback = tmp_path / "calendar.json"
        fallback.write_text(
            json.dumps(
                [
                    _event_to_dict(
                        CalendarEvent(
                            title="FALLBACK-NFP",
                            country="USD",
                            start=datetime(2025, 10, 31, 8, 30, tzinfo=UTC),
                            impact="high",
                        )
                    )
                ]
            ),
            encoding="utf-8",
        )

        def _broken() -> str:
            raise RuntimeError("offline")

        svc = EconomicCalendarService(
            fetcher=_broken, fallback_path=fallback
        )
        index = await svc.refresh_once()
        assert len(index) == 1
        assert index.events[0].title == "FALLBACK-NFP"

    @pytest.mark.asyncio
    async def test_corrupt_fallback_keeps_previous_snapshot(
        self, tmp_path: Path
    ) -> None:
        fallback = tmp_path / "broken.json"
        fallback.write_text("{not json", encoding="utf-8")

        # Seed the snapshot via a successful first fetch
        xml = _xml_with_events([("NFP", "USD", "10-31-2025", "8:30am")])
        calls = {"n": 0}

        def _fetcher() -> str:
            calls["n"] += 1
            if calls["n"] == 1:
                return xml
            raise RuntimeError("offline")

        svc = EconomicCalendarService(
            fetcher=_fetcher, fallback_path=fallback
        )
        await svc.refresh_once()  # success — snapshot has NFP

        index2 = await svc.refresh_once()  # fetch fails, fallback corrupt
        assert len(index2) == 1  # previous snapshot preserved
        assert index2.events[0].title == "NFP"


# -------------------------------------------------------------------------
# All-fail keeps previous snapshot
# -------------------------------------------------------------------------


class TestAllFail:
    @pytest.mark.asyncio
    async def test_all_paths_fail_keeps_existing(self) -> None:
        # Initial state — no snapshot
        def _broken() -> str:
            raise RuntimeError("offline")

        svc = EconomicCalendarService(fetcher=_broken)
        index = await svc.refresh_once()
        # Empty snapshot is fine — but no exception raised
        assert len(index) == 0


# -------------------------------------------------------------------------
# Background loop
# -------------------------------------------------------------------------


class TestRefreshLoop:
    @pytest.mark.asyncio
    async def test_start_eagerly_refreshes_then_loops(self) -> None:
        xml_v1 = _xml_with_events([("V1", "USD", "10-31-2025", "8:30am")])
        xml_v2 = _xml_with_events([("V2", "USD", "11-13-2025", "2:00pm")])
        calls = {"n": 0}

        def _fetcher() -> str:
            calls["n"] += 1
            return xml_v1 if calls["n"] == 1 else xml_v2

        svc = EconomicCalendarService(
            fetcher=_fetcher, refresh_interval_seconds=0.02
        )
        await svc.start()
        # First eager refresh visible
        assert svc.snapshot().events[0].title == "V1"

        # Wait for the loop to fire at least once more
        for _ in range(50):
            if svc.snapshot().events and svc.snapshot().events[0].title == "V2":
                break
            await asyncio.sleep(0.01)

        await svc.stop()
        assert svc.snapshot().events[0].title == "V2"

    @pytest.mark.asyncio
    async def test_loop_survives_a_failed_refresh(self) -> None:
        xml = _xml_with_events([("OK", "USD", "10-31-2025", "8:30am")])
        calls: list[str] = []

        def _fetcher() -> str:
            calls.append("call")
            if len(calls) == 2:
                raise RuntimeError("transient")
            return xml

        svc = EconomicCalendarService(
            fetcher=_fetcher, refresh_interval_seconds=0.01
        )
        await svc.start()
        # Wait for several ticks
        for _ in range(50):
            if len(calls) >= 3:
                break
            await asyncio.sleep(0.01)
        await svc.stop()
        assert len(calls) >= 3


# -------------------------------------------------------------------------
# Round-trip helper
# -------------------------------------------------------------------------


class TestSerialisation:
    def test_round_trip_via_dict(self) -> None:
        ev = CalendarEvent(
            title="NFP",
            country="USD",
            start=datetime(2025, 10, 31, 8, 30, tzinfo=UTC),
            impact="high",
            symbols=("XAUUSD",),
        )
        restored = _event_from_dict(_event_to_dict(ev))
        assert restored == ev
