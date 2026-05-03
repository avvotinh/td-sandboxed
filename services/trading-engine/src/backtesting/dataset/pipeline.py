"""Materialise a :class:`DatasetSpec` to Parquet + manifest.

The pipeline walks every (timeframe, window) combination declared by
the spec and ensures a Parquet shard exists for it under the
:class:`ParquetBarLoader` cache. For each combination it asks the bar
source for a fingerprint (cheap metadata query); if the local shard
already matches the fingerprint, the pipeline reuses it. Otherwise it
downloads the bars and writes a fresh shard. The fingerprint is stamped
into the resulting :class:`DatasetEntry` so callers can later assert
they are reading the same bytes that were validated.

Gap detection runs once per shard. A "gap" is a stretch between two
consecutive bars whose duration exceeds ``max_gap_hours``. Shorter
holes (single-bar drops, FX session breaks within the threshold) are
intentionally ignored — flagging them would drown the report in noise.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

import pandas as pd

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.data_loader import ParquetBarLoader
from src.backtesting.dataset.manifest import (
    BarGap,
    DatasetEntry,
    DatasetManifest,
)
from src.backtesting.dataset.spec import DatasetSpec, WindowSpec


logger = logging.getLogger(__name__)


_TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


def timeframe_to_seconds(timeframe: str) -> int:
    """Translate a MetaTrader-style timeframe to seconds.

    Raises ``ValueError`` on anything outside the explicit allowlist —
    we'd rather refuse than guess (a wrong interval here silently
    distorts gap detection).
    """
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        known = ", ".join(sorted(_TIMEFRAME_SECONDS))
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}. Known: {known}"
        ) from exc


class BarSourceProtocol(Protocol):
    """Async fingerprint + load surface — satisfied by ``TimescaleBarLoader``."""

    async def afingerprint(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> ContentHashFingerprint:
        ...

    async def aload(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        ...


def detect_gaps(
    df: pd.DataFrame,
    *,
    timeframe: str,
    window_name: str,
    max_gap_hours: float,
) -> tuple[BarGap, ...]:
    """Return every consecutive-bar gap exceeding ``max_gap_hours``.

    The function is order-sensitive but tolerant of unsorted indexes —
    we sort defensively before diffing so a caller passing a
    pre-concatenated DataFrame (segmented gaps) still gets the right
    answer.
    """
    if len(df) < 2:
        return ()

    threshold_seconds = max_gap_hours * 3600.0
    sorted_idx = df.index.sort_values()
    # tz-naive timestamps would silently call ``astimezone`` against the
    # local clock when serialised, corrupting the manifest. Refuse rather
    # than guess.
    if getattr(sorted_idx, "tz", None) is None:
        raise ValueError(
            "detect_gaps requires a tz-aware DatetimeIndex; got tz=None"
        )
    gaps: list[BarGap] = []
    for prev, nxt in zip(sorted_idx[:-1], sorted_idx[1:], strict=True):
        delta = (nxt - prev).total_seconds()
        if delta > threshold_seconds:
            gaps.append(
                BarGap(
                    timeframe=timeframe,
                    window_name=window_name,
                    before=prev.to_pydatetime(),
                    after=nxt.to_pydatetime(),
                )
            )
    return tuple(gaps)


class DatasetPipeline:
    """Orchestrate fingerprint → cache-or-fetch → manifest."""

    def __init__(
        self,
        *,
        parquet: ParquetBarLoader,
        source: BarSourceProtocol,
    ) -> None:
        self._parquet = parquet
        self._source = source

    async def materialize_async(self, spec: DatasetSpec) -> DatasetManifest:
        """Materialise every (timeframe, window) entry in ``spec``."""
        entries: list[DatasetEntry] = []
        for timeframe, window in spec.iter_entries():
            entry = await self._materialize_one(
                spec=spec, timeframe=timeframe, window=window
            )
            entries.append(entry)

        return DatasetManifest(
            spec_name=spec.name,
            dataset_version=spec.dataset_version,
            symbol=spec.symbol,
            generated_at=datetime.now(UTC),
            max_gap_hours=spec.max_gap_hours,
            entries=tuple(entries),
        )

    async def _materialize_one(
        self,
        *,
        spec: DatasetSpec,
        timeframe: str,
        window: WindowSpec,
    ) -> DatasetEntry:
        fingerprint = await self._source.afingerprint(
            spec.symbol, timeframe, window.start, window.end
        )
        cached = self._parquet.load(
            spec.symbol, timeframe, window.start, window.end, fingerprint
        )
        if cached is not None:
            df = cached
            logger.debug(
                "dataset cache hit symbol=%s tf=%s window=%s rows=%d",
                spec.symbol,
                timeframe,
                window.name,
                len(df),
            )
        else:
            df = await self._source.aload(
                spec.symbol, timeframe, window.start, window.end
            )
            self._parquet.write(
                spec.symbol, timeframe, window.start, window.end, fingerprint, df
            )
            logger.info(
                "dataset cache miss — wrote shard symbol=%s tf=%s window=%s rows=%d",
                spec.symbol,
                timeframe,
                window.name,
                len(df),
            )

        if len(df) != fingerprint.row_count:
            # afingerprint() and aload() ran as separate DB round-trips;
            # late-arriving bar inserts can shift the count. Don't fail
            # — the validation report still uses the materialised count
            # — but make the divergence loud enough to investigate.
            logger.warning(
                "row count diverged from fingerprint: fingerprint=%d "
                "loaded=%d symbol=%s tf=%s window=%s",
                fingerprint.row_count,
                len(df),
                spec.symbol,
                timeframe,
                window.name,
            )

        gaps = detect_gaps(
            df,
            timeframe=timeframe,
            window_name=window.name,
            max_gap_hours=spec.max_gap_hours,
        )
        path = self._parquet.path_for(
            spec.symbol, timeframe, window.start, window.end, fingerprint
        )
        return DatasetEntry(
            timeframe=timeframe,
            window_name=window.name,
            window_kind=window.kind,
            start=window.start,
            end=window.end,
            parquet_path=path,
            fingerprint=fingerprint,
            row_count=len(df),
            gaps=gaps,
        )
