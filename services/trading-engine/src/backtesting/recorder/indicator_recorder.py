"""IndicatorRecorder — record indicator series DURING the backtest run.

Plain Python, no Nautilus dependency (gap G6): strategies register their
series once (lazily, on first export) and append one point per bar from
``BaseStrategy._export_indicators``. The chart viewer then renders
exactly what the strategy saw — no offline recomputation, no risk of
recompute drift.

Recording semantics:

* ``record`` with ``value=None`` is silently skipped — warmup gaps and
  trend-flip splits render as broken lines (missing timestamps).
* Two records at the same ``ts`` for one key collapse to the LAST write
  (same dedupe rule as the old sl_path builder) — line series need
  strictly ascending unique times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.backtesting.result import IndicatorSeries


def ns_to_utc(ns: int) -> datetime:
    """Nautilus ns timestamp → tz-aware UTC datetime (second resolution)."""
    return datetime.fromtimestamp(ns // 1_000_000_000, tz=UTC)


@dataclass
class _SeriesBuffer:
    """Mutable accumulation state for one registered series."""

    title: str
    pane: str
    color: str
    levels: tuple[float, ...]
    # Keyed by ts so a same-ts double write collapses to the last value.
    points: dict[datetime, float] = field(default_factory=dict)


class IndicatorRecorder:
    """Accumulates named indicator series as ``(ts, value)`` points."""

    def __init__(self) -> None:
        self._series: dict[str, _SeriesBuffer] = {}

    def is_registered(self, key: str) -> bool:
        """True when ``key`` has been registered."""
        return key in self._series

    def register(
        self,
        key: str,
        *,
        title: str,
        pane: str,
        color: str,
        levels: tuple[float, ...] = (),
    ) -> None:
        """Declare a series. Re-registering an existing key is a no-op.

        ``pane`` is ``"overlay"`` for price-chart overlays or a named
        lower pane (e.g. ``"rsi"``). Idempotent so strategies can call
        it lazily from within their per-bar export hook.
        """
        if key in self._series:
            return
        self._series[key] = _SeriesBuffer(
            title=title, pane=pane, color=color, levels=tuple(levels)
        )

    def record(self, key: str, ts: datetime, value: float | None) -> None:
        """Append one point; ``None`` values are silently skipped.

        Raises:
            KeyError: ``key`` was never registered — a wiring bug, so
                fail fast rather than silently dropping the series.
        """
        if value is None:
            return
        try:
            buffer = self._series[key]
        except KeyError:
            raise KeyError(
                f"Indicator series {key!r} not registered — call "
                "register() before record()"
            ) from None
        buffer.points[ts] = float(value)

    def to_series(self) -> tuple[IndicatorSeries, ...]:
        """Snapshot all series (registration order, points chronological)."""
        return tuple(
            IndicatorSeries(
                key=key,
                title=buffer.title,
                pane=buffer.pane,
                color=buffer.color,
                points=tuple(sorted(buffer.points.items())),
                levels=buffer.levels,
            )
            for key, buffer in self._series.items()
        )
