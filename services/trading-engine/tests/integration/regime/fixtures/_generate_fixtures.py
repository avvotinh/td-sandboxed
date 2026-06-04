"""Deterministic generator for the story 15.9 regime ablation fixtures.

NOT a test (leading underscore → pytest does not collect it). Run it to
(re)materialise the four OHLCV CSV fixtures consumed by
``test_regime_actor_ablation_csv.py``::

    uv run python tests/integration/regime/fixtures/_generate_fixtures.py

Each fixture is a synthetic XAUUSD M5 bar stream (price_precision=3,
size_precision=2) engineered so the **real** ``FeatureExtractor`` +
``RuleBasedRegimeClassifier`` + ``HysteresisFilter`` pipeline confirms a
single target regime across the post-warmup tail — the segment in which
the allowed strategy trades. The recipes below were tuned empirically
against the production thresholds in ``_thresholds()`` (see the test);
moving a threshold may require re-tuning a stream so its tail stays a
clean single regime.

Why these shapes (vs the old single-row feature-vector fixtures that
injected pre-computed ``RegimeFeatures``): story 15.9 ports the ablation
harness onto a real ``BacktestRunner``, so the fixtures must now drive the
real indicators bar-by-bar rather than hand-set their outputs.

Confirmed-tail (last 80 post-warmup bars, confirmation_bars=2) per stream:

* ``trending_up``      — 80/80 TRENDING_UP   (strong + drift, narrow bands)
* ``trending_down``    — TRENDING_DOWN dominant + a few HIGH_VOLATILITY
  (the downward drift inflates the mean-normalised band width; HIGH_VOL
  blips keep both strategies gated, so they do not weaken the ablation —
  no TRENDING_UP / RANGING blip ever opens a blocked gate)
* ``ranging``          — 80/80 RANGING       (anti-persistent mean reversion
  → DM cancels → ADX < trend floor; compressing amplitude → low BB-width
  percentile)
* ``high_volatility``  — HIGH_VOLATILITY/UNKNOWN throughout (large constant
  amplitude → realized_vol >> threshold from the first emitted feature, so
  the kill-switch confirms before any trend can)
"""
from __future__ import annotations

import csv
import random
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.objects import Price, Quantity

from src.backtesting.synthetic_bars import generate_bars

FIXTURES = Path(__file__).parent
# Only used to construct transient Bar objects during generation — the bar
# type is NOT serialised to the CSV (only ts_init + OHLCV are), so the test
# attaches its own bar type on load. The venue here mirrors
# ``runner_facade._build_xauusd_instrument`` (``Venue("SIM")``) so a curious
# reader sees the same shape, but a divergence would not affect the fixtures.
BAR_TYPE = BarType.from_str("XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL")
START_TS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
NS_PER_MIN = 60 * 1_000_000_000

COUNT = 280
START_PRICE = 2000.0
SEED = 7
PRICE_PREC = 3
VOL_PREC = 2


def _walk(
    amp_fn: Callable[[int, int], float],
    drift_fn: Callable[[float], float],
) -> list[Bar]:
    """Build a deterministic price walk with per-bar amplitude/drift callables.

    ``amp_fn(i, count)`` returns the symmetric noise half-range for bar ``i``;
    ``drift_fn(price)`` returns the deterministic step added to the current
    price. Mirrors ``synthetic_bars.generate_bars`` bar construction so the
    two fixture families serialise identically; the extra knobs (decaying /
    growing amplitude, configurable mean-reversion pull) are what
    ``generate_bars`` cannot express and the RANGING / HIGH_VOLATILITY
    regimes require.

    Determinism note: the walk is reproducible only as long as the number of
    ``rng`` draws per bar stays fixed (currently two: noise then wick). Adding
    or removing a draw shifts the whole sequence and silently re-classifies
    the committed CSVs — regenerate and re-pin if you change the loop body.
    """
    rng = random.Random(SEED)
    price = START_PRICE
    fmt = f"{{:.{PRICE_PREC}f}}"
    vol = Quantity.from_str(f"{100.0:.{VOL_PREC}f}")
    bars: list[Bar] = []
    for i in range(COUNT):
        amp = amp_fn(i, COUNT)
        drift = drift_fn(price)
        noise = rng.uniform(-amp, amp)
        new = price + drift + noise
        wick = abs(rng.uniform(0, amp * 0.3))
        open_p, close_p = price, new
        high_p = max(open_p, close_p) + wick
        low_p = min(open_p, close_p) - wick
        ts = START_TS + i * NS_PER_MIN
        bars.append(
            Bar(
                bar_type=BAR_TYPE,
                open=Price.from_str(fmt.format(open_p)),
                high=Price.from_str(fmt.format(high_p)),
                low=Price.from_str(fmt.format(low_p)),
                close=Price.from_str(fmt.format(close_p)),
                volume=vol,
                ts_event=ts,
                ts_init=ts,
            )
        )
        price = new
    return bars


def build_streams() -> dict[str, list[Bar]]:
    """Return the four regime bar streams keyed by fixture name."""
    common = dict(
        count=COUNT,
        start_price=START_PRICE,
        seed=SEED,
        start_ts=START_TS,
        bar_type=BAR_TYPE,
        price_precision=PRICE_PREC,
        volume_precision=VOL_PREC,
    )
    return {
        "trending_up": generate_bars(
            pattern="trending", drift_scale=2.0, noise_scale=0.5, **common
        ),
        "trending_down": generate_bars(
            pattern="trending", drift_scale=-1.0, noise_scale=0.5, **common
        ),
        # Anti-persistent mean reversion (strong pull → moves alternate →
        # ADX stays below the trend floor) with steadily compressing
        # amplitude (recent BB width sinks to the low percentile).
        "ranging": _walk(
            amp_fn=lambda i, n: max(0.05, 3.0 * (1.0 - i / n)),
            drift_fn=lambda p: -0.5 * (p - START_PRICE),
        ),
        # Large constant amplitude → realized volatility well above the
        # high threshold on every window, so HIGH_VOLATILITY (top priority)
        # fires from the first emitted feature and never yields to a trend.
        "high_volatility": _walk(
            amp_fn=lambda i, n: 150.0,
            drift_fn=lambda p: -0.05 * (p - START_PRICE),
        ),
    }


_RECIPES = {
    "trending_up": "generate_bars(trending, drift=+2.0, noise=0.5) -> TRENDING_UP",
    "trending_down": "generate_bars(trending, drift=-1.0, noise=0.5) -> TRENDING_DOWN(+HIGH_VOL blips)",
    "ranging": "mean-reversion pull=0.5, amplitude 3.0->0.05 -> RANGING",
    "high_volatility": "constant amplitude 150 -> HIGH_VOLATILITY (realized_vol kill-switch)",
}


def write_csv(name: str, bars: list[Bar]) -> Path:
    path = FIXTURES / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# {name} -- {_RECIPES[name]}\n")
        f.write(
            "# generated by _generate_fixtures.py (story 15.9); "
            f"XAUUSD M5, seed={SEED}, count={COUNT}\n"
        )
        writer = csv.writer(f)
        writer.writerow(["ts_init", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow(
                [
                    bar.ts_init,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                ]
            )
    return path


def main() -> None:
    for name, bars in build_streams().items():
        path = write_csv(name, bars)
        print(f"wrote {path} ({len(bars)} bars)")


if __name__ == "__main__":
    main()
