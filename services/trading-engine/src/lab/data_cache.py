"""Cache-key computation for the Parquet layer of the backtest data loader.

Cache invalidation is tricky for historical bars: TimescaleDB can receive
late-arriving bar corrections, so a stale Parquet shard would serve
silently wrong data. We build a **content hash** from a cheap metadata
query (min timestamp, max timestamp, row count) and fold it into the
cache key. Any insert/update/delete within the queried range changes at
least one of those three values, invalidating the cache automatically.

The resulting path layout is

    {cache_dir}/{symbol}/{timeframe}/{start}_{end}_{hash16}.parquet

so listing by symbol + timeframe is fast, and multiple range slices of
the same series coexist without colliding.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# Strict allowlist for path components — rejects traversal sequences
# (``../``, absolute paths, NULs) and any non-ASCII-identifier-safe glyph.
_SAFE_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_path_component(name: str, value: str) -> None:
    """Reject any string that could escape the cache directory."""
    if not value or not _SAFE_PATH_COMPONENT.match(value):
        raise ValueError(
            f"Unsafe {name} for cache path: {value!r}. Only [A-Za-z0-9._-] allowed."
        )


@dataclass(frozen=True)
class ContentHashFingerprint:
    """Cheap metadata summary used to detect bar-data changes.

    Attributes:
        min_ts: Nanosecond timestamp of the earliest bar in the range.
        max_ts: Nanosecond timestamp of the latest bar in the range.
        row_count: Number of bars in the range.
    """

    min_ts: int
    max_ts: int
    row_count: int

    def sha256(self) -> str:
        """16-char SHA256 hex fingerprint — compact but collision-safe."""
        payload = f"{self.min_ts}|{self.max_ts}|{self.row_count}".encode()
        return hashlib.sha256(payload).hexdigest()[:16]


def build_cache_key(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    fingerprint: ContentHashFingerprint,
) -> str:
    """Deterministic string key combining all cache dimensions."""
    return (
        f"{symbol}|{timeframe}|"
        f"{start.isoformat()}|{end.isoformat()}|"
        f"{fingerprint.sha256()}"
    )


def build_cache_path(
    cache_dir: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    fingerprint: ContentHashFingerprint,
) -> Path:
    """Resolve the on-disk Parquet path for a (symbol, timeframe, range).

    ``symbol`` and ``timeframe`` are validated against a strict allowlist
    to block directory-traversal attacks: any value outside
    ``[A-Za-z0-9._-]`` raises ``ValueError``. See Epic 8 security audit
    for the attack scenario (crafted YAML escaping ``cache_dir``).
    """
    _validate_path_component("symbol", symbol)
    _validate_path_component("timeframe", timeframe)
    start_stamp = start.strftime("%Y%m%dT%H%M%S")
    end_stamp = end.strftime("%Y%m%dT%H%M%S")
    filename = f"{start_stamp}_{end_stamp}_{fingerprint.sha256()}.parquet"
    return Path(cache_dir) / symbol / timeframe / filename
