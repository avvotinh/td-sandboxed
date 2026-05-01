"""Economic-calendar service — daily fetch + Redis cache + snapshot.

Story 10.8 — :class:`NewsBlackoutRule` consults a snapshot of upcoming
events to decide whether to block a trade. The snapshot is rebuilt
once a day from the ForexFactory weekly XML feed, cached on Redis
(``calendar:events:{YYYY-MM-DD}`` TTL 26h so a missed refresh leaves
yesterday's snapshot live for one cycle), and falls back to a static
file when fetch fails.

Design notes:

- The fetcher is **injected** as a callable returning ``str | bytes``,
  not a hard dependency on ``aiohttp``. Production callers wrap the
  HTTP client and pass it in; tests pass a synchronous stub. Keeps
  the service unit-testable without HTTP machinery.
- The service exposes :meth:`snapshot` which returns the current
  :class:`EventIndex`. :class:`NewsBlackoutRule` is constructed with
  ``snapshot_provider=service.snapshot`` so a refresh atomically swaps
  in the new index without touching live rule instances.
- :meth:`start` / :meth:`stop` manage a background refresh loop
  (interval-driven) that also runs once eagerly so the first rule
  evaluation does not see an empty index.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .calendar_models import CalendarEvent, EventIndex
from .forex_factory_parser import parse_forex_factory_xml

logger = logging.getLogger(__name__)


# Sync or async fetcher returning the raw XML payload.
Fetcher = (
    Callable[[], str | bytes]
    | Callable[[], Awaitable[str | bytes]]
)

# Default refresh: once a day. Cache TTL is 26h so a single missed
# refresh still has yesterday's data live.
DEFAULT_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
DEFAULT_REDIS_TTL_SECONDS = 26 * 60 * 60
DEFAULT_REDIS_KEY_PREFIX = "calendar:events"


class EconomicCalendarService:
    """Daily-refresh ForexFactory calendar feed with Redis cache + fallback.

    Args:
        fetcher: Callable producing raw XML for the upcoming week. May
            be sync or async. Production wraps an HTTP GET against
            ``https://nfs.faireconomy.media/ff_calendar_thisweek.xml``;
            tests pass a stub.
        redis_manager: Optional :class:`RedisStateManager`. When set,
            parsed events are cached as JSON on
            ``calendar:events:{YYYY-MM-DD}`` so a freshly-restarted
            engine has data while the first refresh runs. ``None``
            disables caching (in-memory snapshot only).
        fallback_path: Optional path to a static JSON file holding
            events. Loaded if ``fetcher`` raises and Redis cache is
            empty / unavailable. Operations curate this file weekly.
        refresh_interval_seconds: Background-loop cadence.
        redis_ttl_seconds: Cache TTL on the Redis key.
        redis_key_prefix: Configurable for test environments.
    """

    def __init__(
        self,
        *,
        fetcher: Fetcher,
        redis_manager: object | None = None,
        fallback_path: Path | str | None = None,
        refresh_interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
        redis_ttl_seconds: int = DEFAULT_REDIS_TTL_SECONDS,
        redis_key_prefix: str = DEFAULT_REDIS_KEY_PREFIX,
    ) -> None:
        self._fetcher = fetcher
        self._redis_manager = redis_manager
        self._fallback_path = (
            Path(fallback_path) if fallback_path is not None else None
        )
        self._refresh_interval = refresh_interval_seconds
        self._redis_ttl = redis_ttl_seconds
        self._redis_key_prefix = redis_key_prefix

        self._snapshot: EventIndex = EventIndex([])
        self._snapshot_built_at: datetime | None = None
        self._refresh_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def snapshot_built_at(self) -> datetime | None:
        return self._snapshot_built_at

    def snapshot(self) -> EventIndex:
        """Return the current immutable :class:`EventIndex`."""
        return self._snapshot

    async def start(self) -> None:
        """Fire one eager refresh + spawn the periodic refresh task."""
        if self._running:
            return
        self._running = True
        # Eager refresh — rule eval right after start() should see data.
        await self.refresh_once()
        self._refresh_task = asyncio.create_task(
            self._refresh_loop(),
            name="economic_calendar_refresh",
        )

    async def stop(self) -> None:
        """Cancel the refresh task. Idempotent."""
        if not self._running:
            return
        self._running = False
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None

    async def refresh_once(self) -> EventIndex:
        """Refresh the snapshot one time. Returns the new index.

        Strategy:
        1. Try the fetcher. On success, parse + write-through the
           Redis cache.
        2. On fetcher failure, try Redis cache (today's key).
        3. On cache miss, try the static fallback file.
        4. On all-fail, leave the existing snapshot in place — better
           to evaluate against stale-but-known data than to fail open.
        """
        events = await self._fetch_and_parse()
        if events is not None:
            await self._cache_to_redis(events)
        else:
            events = await self._read_redis_cache()
        if events is None:
            events = self._read_fallback_file()
        if events is None:
            logger.warning(
                "EconomicCalendarService: refresh failed via fetcher, "
                "Redis cache, and static fallback — keeping previous "
                "snapshot of %d events",
                len(self._snapshot),
            )
            return self._snapshot

        self._snapshot = EventIndex(events)
        self._snapshot_built_at = datetime.now(timezone.utc)
        logger.info(
            "EconomicCalendarService: snapshot rebuilt with %d events",
            len(self._snapshot),
        )
        return self._snapshot

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._refresh_interval)
            except asyncio.CancelledError:
                raise
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "EconomicCalendarService: scheduled refresh raised; "
                    "next attempt in %.0fs",
                    self._refresh_interval,
                )

    async def _fetch_and_parse(self) -> list[CalendarEvent] | None:
        try:
            raw = self._fetcher()
            if asyncio.iscoroutine(raw):
                raw = await raw
        except Exception:
            logger.warning(
                "EconomicCalendarService: fetcher raised; trying cache",
                exc_info=True,
            )
            return None

        if raw is None:
            return None
        events = parse_forex_factory_xml(raw)
        if not events:
            logger.info(
                "EconomicCalendarService: fetcher returned no events"
            )
        return events

    async def _cache_to_redis(self, events: list[CalendarEvent]) -> None:
        if self._redis_manager is None:
            return
        try:
            client = self._redis_manager.client
        except Exception:
            return
        key = self._redis_key_for(date.today())
        payload = json.dumps([_event_to_dict(e) for e in events])
        try:
            await client.setex(key, self._redis_ttl, payload)
        except Exception:
            logger.warning(
                "EconomicCalendarService: Redis cache write failed",
                exc_info=True,
            )

    async def _read_redis_cache(self) -> list[CalendarEvent] | None:
        if self._redis_manager is None:
            return None
        try:
            client = self._redis_manager.client
        except Exception:
            return None
        # Try today first, then yesterday — accommodates the 26h TTL
        # window where yesterday's cache is still alive at midnight.
        for offset in (0, -1):
            d = date.fromordinal(date.today().toordinal() + offset)
            key = self._redis_key_for(d)
            try:
                raw = await client.get(key)
            except Exception:
                logger.warning(
                    "EconomicCalendarService: Redis cache read failed",
                    exc_info=True,
                )
                return None
            if not raw:
                continue
            try:
                items = json.loads(raw)
                events = [_event_from_dict(e) for e in items]
                logger.info(
                    "EconomicCalendarService: loaded %d events from "
                    "Redis cache for %s",
                    len(events),
                    d.isoformat(),
                )
                return events
            except (json.JSONDecodeError, ValueError, KeyError):
                logger.warning(
                    "EconomicCalendarService: corrupt Redis cache for %s",
                    d.isoformat(),
                    exc_info=True,
                )
                return None
        return None

    def _read_fallback_file(self) -> list[CalendarEvent] | None:
        if self._fallback_path is None:
            return None
        if not self._fallback_path.exists():
            return None
        try:
            raw = self._fallback_path.read_text(encoding="utf-8")
            items = json.loads(raw)
            events = [_event_from_dict(e) for e in items]
            logger.info(
                "EconomicCalendarService: loaded %d events from fallback %s",
                len(events),
                self._fallback_path,
            )
            return events
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            logger.warning(
                "EconomicCalendarService: fallback file unreadable: %s",
                self._fallback_path,
                exc_info=True,
            )
            return None

    def _redis_key_for(self, d: date) -> str:
        return f"{self._redis_key_prefix}:{d.isoformat()}"


# -------------------------------------------------------------------------
# (de)serialisation helpers — keep CalendarEvent ↔ Redis JSON symmetric
# -------------------------------------------------------------------------


def _event_to_dict(event: CalendarEvent) -> dict:
    return {
        "title": event.title,
        "country": event.country,
        "start": event.start.isoformat(),
        "impact": event.impact,
        "symbols": list(event.symbols),
    }


def _event_from_dict(data: dict) -> CalendarEvent:
    return CalendarEvent(
        title=data["title"],
        country=data["country"],
        start=datetime.fromisoformat(data["start"]),
        impact=data["impact"],
        symbols=tuple(data.get("symbols") or ()),
    )
