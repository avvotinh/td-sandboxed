"""Backtest bar-data loaders.

Three layers, all sharing :class:`BarLoaderProtocol`:

1. :class:`TimescaleBarLoader` — source-of-truth async query against the
   ``candles`` hypertable. Used when the Parquet cache misses.
2. :class:`ParquetBarLoader` — local on-disk cache. Reads/writes one
   Parquet shard per (symbol, timeframe, range, content-hash) tuple.
3. :class:`CachedBarLoader` — cache-aside composite. Checks Parquet
   first, falls back to TimescaleDB, and writes the result back as a
   new shard on miss.

All loaders return a pandas ``DataFrame`` indexed by a UTC-aware
``DatetimeIndex`` with columns ``open``, ``high``, ``low``, ``close``,
``volume`` so downstream code (BacktestEngine + BarDataWrangler) can
consume any layer identically.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from src.backtesting.data_cache import (
    ContentHashFingerprint,
    build_cache_path,
)


logger = logging.getLogger(__name__)


class BarLoaderProtocol(Protocol):
    """Common loader interface — returns an OHLCV DataFrame or ``None``."""

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,
    ) -> pd.DataFrame | None:
        """Return bars for the range, or ``None`` on miss."""
        ...


# --- Parquet layer -----------------------------------------------------


class ParquetBarLoader:
    """On-disk Parquet shards rooted at ``cache_dir``."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = Path(cache_dir)

    def path_for(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,
    ) -> Path:
        return build_cache_path(
            cache_dir=self._cache_dir,
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            fingerprint=fingerprint,
        )

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,
    ) -> pd.DataFrame | None:
        path = self.path_for(symbol, timeframe, start, end, fingerprint)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def write(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,
        df: pd.DataFrame,
    ) -> Path:
        """Persist ``df`` to Parquet at the computed path. Returns the path."""
        path = self.path_for(symbol, timeframe, start, end, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
        return path


# --- TimescaleDB layer -------------------------------------------------


class TimescaleBarLoader:
    """Async asyncpg-backed loader for the ``candles`` hypertable.

    Parameters:
        pool: An ``asyncpg.Pool`` already connected to the trading
            database. We accept the pool rather than constructing it so
            tests can inject a mock without touching the network.
        table: Override for the candles table name if needed.

    .. note::
        This class is **async-native**: :meth:`aload` is the primary
        interface. The synchronous :meth:`load` shim runs the coroutine
        on ``asyncio.new_event_loop()`` and is provided so
        :class:`CachedBarLoader` can stay synchronous. For long pipelines
        prefer calling ``aload`` directly from an async context.
    """

    def __init__(self, pool, table: str = "candles") -> None:
        self._pool = pool
        self._table = table

    async def afingerprint(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> ContentHashFingerprint:
        """Cheap metadata query producing a :class:`ContentHashFingerprint`."""
        query = (
            f"SELECT MIN(time)::timestamptz AS min_ts, "
            f"MAX(time)::timestamptz AS max_ts, "
            f"COUNT(*)::bigint AS cnt FROM {self._table} "
            "WHERE symbol = $1 AND timeframe = $2 "
            "AND time >= $3 AND time < $4"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, symbol, timeframe, start, end)

        min_ts = _dt_to_ns(row["min_ts"]) if row and row["min_ts"] else 0
        max_ts = _dt_to_ns(row["max_ts"]) if row and row["max_ts"] else 0
        row_count = int(row["cnt"]) if row else 0
        return ContentHashFingerprint(
            min_ts=min_ts, max_ts=max_ts, row_count=row_count
        )

    async def aload(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Async full-range bar fetch."""
        query = (
            f"SELECT time, open, high, low, close, volume FROM {self._table} "
            "WHERE symbol = $1 AND timeframe = $2 "
            "AND time >= $3 AND time < $4 "
            "ORDER BY time ASC"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, symbol, timeframe, start, end)

        if not rows:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"],
                index=pd.DatetimeIndex([], tz="UTC", name="time"),
            )

        df = pd.DataFrame(
            {
                "time": [r["time"] for r in rows],
                "open": [float(r["open"]) for r in rows],
                "high": [float(r["high"]) for r in rows],
                "low": [float(r["low"]) for r in rows],
                "close": [float(r["close"]) for r in rows],
                "volume": [float(r["volume"] or 0) for r in rows],
            }
        )
        df = df.set_index(pd.DatetimeIndex(df["time"], tz="UTC", name="time")).drop(
            columns=["time"]
        )
        return df

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,  # ignored — Timescale is source
    ) -> pd.DataFrame:
        """Sync wrapper — runs the async fetch on a private event loop."""
        import asyncio

        return asyncio.run(self.aload(symbol, timeframe, start, end))


def _dt_to_ns(dt: datetime) -> int:
    """Convert a tz-aware datetime to nanoseconds since Unix epoch."""
    return int(dt.timestamp() * 1_000_000_000)


# --- Composite cached layer -------------------------------------------


class CachedBarLoader:
    """Cache-aside composition: Parquet first, TimescaleDB fallback.

    When a parquet shard matching the request content-hash exists it is
    returned directly. On miss we query the fingerprint + bars from
    TimescaleDB, write a fresh Parquet shard, and return the DataFrame.

    Callers must supply the expected fingerprint (typically via
    :meth:`TimescaleBarLoader.afingerprint`); that's how we know whether
    the cached shard is still valid. Passing ``no_cache=True`` on
    :meth:`load` skips the Parquet check and forces a TimescaleDB fetch.
    """

    def __init__(
        self,
        *,
        parquet: ParquetBarLoader,
        timescale: TimescaleBarLoader,
    ) -> None:
        self._parquet = parquet
        self._timescale = timescale

    def load(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        fingerprint: ContentHashFingerprint,
        *,
        no_cache: bool = False,
    ) -> pd.DataFrame:
        if not no_cache:
            cached = self._parquet.load(symbol, timeframe, start, end, fingerprint)
            if cached is not None:
                logger.debug(
                    "Parquet cache hit: %s %s %s..%s", symbol, timeframe, start, end
                )
                return cached

        df = self._timescale.load(symbol, timeframe, start, end, fingerprint)
        self._parquet.write(symbol, timeframe, start, end, fingerprint, df)
        logger.debug(
            "Parquet cache miss — wrote shard: %s %s rows=%d",
            symbol,
            timeframe,
            len(df),
        )
        return df
