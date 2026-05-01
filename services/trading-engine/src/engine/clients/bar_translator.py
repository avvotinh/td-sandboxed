"""Internal :class:`Bar` → Nautilus :class:`Bar` translation.

Story 10.5b — :class:`RedisDataClient` subscribes to ``bars:{symbol}:{tf}``
Redis Pub/Sub channels and emits the parsed messages into the
per-account ``LiveNode``'s data engine. The translation layer lives
here so it can be unit-tested without standing up Redis or a Nautilus
engine.

Timeframe parsing supports the suffixes used by the tv-api producer
today (``"30s"``, ``"1m"``, ``"5m"``, ``"15m"``, ``"1h"``, ``"4h"``,
``"1d"``, ``"1w"``). Unknown suffixes raise :class:`ValueError` rather
than guess; an unsupported feed should fail loudly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from nautilus_trader.model.data import Bar as NautilusBar
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.objects import Price, Quantity

if TYPE_CHECKING:
    from ...adapters.redis_models import Bar as InternalBar


# Suffix → Nautilus aggregation. Keep this map exhaustive; anything
# missing raises in :func:`parse_timeframe`.
_TIMEFRAME_SUFFIX: dict[str, BarAggregation] = {
    "s": BarAggregation.SECOND,
    "m": BarAggregation.MINUTE,
    "h": BarAggregation.HOUR,
    "d": BarAggregation.DAY,
    "w": BarAggregation.WEEK,
}


def parse_timeframe(timeframe: str) -> tuple[int, BarAggregation]:
    """Split a tv-api timeframe string into ``(step, aggregation)``.

    Args:
        timeframe: e.g. ``"1m"``, ``"5m"``, ``"1h"``, ``"4h"``, ``"1d"``.

    Raises:
        ValueError: On unsupported suffix or non-positive step.
    """
    if not timeframe:
        raise ValueError("timeframe must be non-empty")

    timeframe = timeframe.strip().lower()
    suffix = timeframe[-1]
    head = timeframe[:-1]

    aggregation = _TIMEFRAME_SUFFIX.get(suffix)
    if aggregation is None:
        raise ValueError(
            f"Unsupported timeframe suffix: {timeframe!r} — "
            f"expected one of {sorted(_TIMEFRAME_SUFFIX)}"
        )

    try:
        step = int(head)
    except ValueError as exc:
        raise ValueError(
            f"Invalid timeframe {timeframe!r}: step must be an integer"
        ) from exc

    if step <= 0:
        raise ValueError(f"Timeframe step must be positive: {timeframe!r}")

    return step, aggregation


def make_bar_type(
    symbol: str,
    timeframe: str,
    venue: Venue,
    *,
    price_type: PriceType = PriceType.LAST,
) -> BarType:
    """Construct the Nautilus :class:`BarType` for ``(symbol, timeframe)``.

    Used both by :class:`RedisDataClient` (when emitting bars) and by
    strategies that need the same identifier to subscribe.
    """
    step, aggregation = parse_timeframe(timeframe)
    instrument_id = InstrumentId(Symbol(symbol), venue)
    spec = BarSpecification(
        step=step,
        aggregation=aggregation,
        price_type=price_type,
    )
    return BarType(instrument_id=instrument_id, bar_spec=spec)


def to_nautilus_bar(
    internal_bar: "InternalBar",
    *,
    bar_type: BarType,
    price_precision: int = 5,
    size_precision: int = 2,
    ts_init_ns: int | None = None,
) -> NautilusBar:
    """Convert an internal Pydantic :class:`Bar` into a Nautilus
    :class:`~nautilus_trader.model.data.Bar`.

    Args:
        internal_bar: Parsed message from the ``bars:*`` Redis channel.
        bar_type: Pre-built :class:`BarType`. Build via
            :func:`make_bar_type` so the producer (this client) and the
            consumer (strategy + actor) agree.
        price_precision: Decimal places for OHLC. Defaults to ``5``
            which covers FX majors at MT5 (1 pip = 0.0001 → 1/10 pip
            precision).
        size_precision: Decimal places for volume. Defaults to ``2``.
        ts_init_ns: Optional ``ts_init`` override (UNIX ns). When
            omitted, defaults to the bar's event timestamp — Nautilus
            requires both timestamps but for a freshly-arrived live
            bar they are equal.
    """
    ts_event = _to_ts_ns(internal_bar.time)
    ts_init = ts_event if ts_init_ns is None else ts_init_ns
    return NautilusBar(
        bar_type=bar_type,
        open=Price(internal_bar.open, price_precision),
        high=Price(internal_bar.high, price_precision),
        low=Price(internal_bar.low, price_precision),
        close=Price(internal_bar.close, price_precision),
        volume=Quantity(internal_bar.volume, size_precision),
        ts_event=ts_event,
        ts_init=ts_init,
    )


def _to_ts_ns(dt) -> int:  # noqa: ANN001 — datetime
    """Convert a (potentially-naive) datetime to UNIX nanoseconds."""
    return int(dt.timestamp() * 1_000_000_000)
