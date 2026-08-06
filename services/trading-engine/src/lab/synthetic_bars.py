"""Deterministic synthetic OHLCV bar generator for backtest tests.

Produces ``list[Bar]`` of length ``count`` following one of three regimes:

- ``trending``       — monotone upward drift + small noise
- ``mean_reverting`` — OU-like pullback to ``start_price`` with symmetric noise
- ``flat``           — very low-volatility sideways with near-zero drift

Same ``seed`` + ``pattern`` + ``count`` always yields identical bars, so
tests are reproducible. All bars are on the default XAUUSD 1-minute
bar_type unless overridden.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity


_DEFAULT_BAR_TYPE = BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL")
_NS_PER_MINUTE = 60 * 1_000_000_000

_VALID_PATTERNS: Sequence[str] = ("trending", "mean_reverting", "flat")


def generate_bars(
    *,
    pattern: str,
    count: int,
    start_price: float,
    seed: int = 42,
    start_ts: int = 0,
    bar_type: BarType = _DEFAULT_BAR_TYPE,
    volume: float = 100.0,
    price_precision: int = 2,
    volume_precision: int = 2,
    noise_scale: float = 1.0,
    drift_scale: float = 1.0,
) -> list[Bar]:
    """Generate a deterministic sequence of synthetic bars.

    Args:
        pattern: One of ``"trending"``, ``"mean_reverting"``, ``"flat"``.
        count: Number of bars to produce.
        start_price: First bar's open.
        seed: RNG seed for reproducibility.
        start_ts: First bar's ``ts_init`` in nanoseconds.
        bar_type: Nautilus ``BarType``.
        volume: Constant volume per bar.
    """
    if pattern not in _VALID_PATTERNS:
        raise ValueError(
            f"pattern must be one of {_VALID_PATTERNS}, got {pattern!r}"
        )
    if count < 0:
        raise ValueError(f"count must be >= 0, got {count}")

    rng = random.Random(seed)
    bars: list[Bar] = []
    price = start_price

    fmt = f"{{:.{price_precision}f}}"
    vol_fmt = f"{{:.{volume_precision}f}}"
    for i in range(count):
        if pattern == "trending":
            drift = 0.5 * drift_scale
            noise = rng.uniform(-0.3, 0.3) * noise_scale
        elif pattern == "mean_reverting":
            # Pull back towards start_price with OU-style force.
            deviation = price - start_price
            drift = -0.05 * deviation
            noise = rng.uniform(-0.8, 0.8) * noise_scale
        else:  # flat
            drift = 0.0
            noise = rng.uniform(-0.05, 0.05) * noise_scale

        new_price = price + drift + noise
        # Construct realistic OHLC with noise contained inside [low, high].
        open_p = price
        close_p = new_price
        wick = abs(rng.uniform(0, 0.2)) * noise_scale
        high_p = max(open_p, close_p) + wick
        low_p = min(open_p, close_p) - wick
        ts = start_ts + i * _NS_PER_MINUTE

        bars.append(
            Bar(
                bar_type=bar_type,
                open=Price.from_str(fmt.format(open_p)),
                high=Price.from_str(fmt.format(high_p)),
                low=Price.from_str(fmt.format(low_p)),
                close=Price.from_str(fmt.format(close_p)),
                volume=Quantity.from_str(vol_fmt.format(volume)),
                ts_event=ts,
                ts_init=ts,
            )
        )
        price = new_price

    return bars
