"""Shared pytest fixtures for unit tests.

Keeps helpers opt-in via fixture injection — fixtures declared here are
available to every test under ``tests/unit`` but do not run unless a test
requests them by name, so existing test files are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity


_DEFAULT_BAR_TYPE = BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL")


def _build_bar(
    *,
    o: float,
    h: float,
    lo: float,
    c: float,
    v: float,
    ts: int,
    bar_type: BarType,
) -> Bar:
    return Bar(
        bar_type=bar_type,
        open=Price.from_str(f"{o:.2f}"),
        high=Price.from_str(f"{h:.2f}"),
        low=Price.from_str(f"{lo:.2f}"),
        close=Price.from_str(f"{c:.2f}"),
        volume=Quantity.from_str(f"{v:.2f}"),
        ts_event=ts,
        ts_init=ts,
    )


@pytest.fixture
def make_bar() -> Callable[..., Bar]:
    """Factory producing synthetic ``Bar`` objects for indicator tests.

    All parameters are keyword-only. Defaults produce a flat XAUUSD bar at
    2400.00 with volume 100. ``high``/``low`` default to max/min of open and
    close so callers can omit them for simple bars. ``ts`` is nanoseconds.
    """

    def _factory(
        *,
        open: float | None = None,
        high: float | None = None,
        low: float | None = None,
        close: float = 2400.0,
        volume: float = 100.0,
        ts: int = 0,
        bar_type: BarType = _DEFAULT_BAR_TYPE,
    ) -> Bar:
        # Default open to close so simple calls (make_bar(close=X)) produce a
        # valid OHLC where low ≤ open ≤ high regardless of how X varies.
        o = open if open is not None else close
        h = high if high is not None else max(o, close)
        low_val = low if low is not None else min(o, close)
        # Expand to accommodate open/close if caller passed narrow high/low.
        h = max(h, o, close)
        low_val = min(low_val, o, close)
        return _build_bar(
            o=o, h=h, lo=low_val, c=close, v=volume, ts=ts, bar_type=bar_type
        )

    return _factory


@pytest.fixture
def bar_series(make_bar: Callable[..., Bar]) -> Callable[..., list[Bar]]:
    """Factory for building sequences of bars from parallel OHLCV lists.

    Example::

        bars = bar_series(
            open=[100, 101, 102],
            high=[101, 102, 103],
            low=[99, 100, 101],
            close=[101, 102, 103],
            volume=[10, 20, 30],
        )
    """
    ns_per_minute = 60 * 1_000_000_000

    def _factory(
        *,
        open: list[float],
        high: list[float],
        low: list[float],
        close: list[float],
        volume: list[float] | None = None,
        start_ts: int = 0,
    ) -> list[Bar]:
        n = len(close)
        if not (len(open) == len(high) == len(low) == n):
            raise ValueError("OHLC lists must share the same length")
        vols = volume if volume is not None else [100.0] * n
        if len(vols) != n:
            raise ValueError("volume length must match OHLC length")
        bars: list[Bar] = []
        for i in range(n):
            bars.append(
                make_bar(
                    open=open[i],
                    high=high[i],
                    low=low[i],
                    close=close[i],
                    volume=vols[i],
                    ts=start_ts + i * ns_per_minute,
                )
            )
        return bars

    return _factory
