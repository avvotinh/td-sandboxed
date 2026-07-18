"""Candle loader — Result Contract v2 ``run.data_ref`` → OHLCV chart rows.

Candles are NOT stored in the result JSON (Decision D2 / architecture
§4). They live in the parquet the run was fed, referenced by
``run.data_ref.manifest``, which the writer sets to
``Path(data.path).as_posix()`` for a ``ParquetDataSpec`` (a direct
parquet path, repo-root-relative) or ``synthetic:...`` for a
``SyntheticDataSpec``.

This is an independent reader — the viewer must not import
trading-engine code (paths.py). It mirrors the two on-disk parquet
shapes ``runner_facade._normalise_parquet_index`` accepts:

* tz-aware ``DatetimeIndex`` named ``time`` + OHLCV columns, or
* ``index=False`` with an int64 ``time`` column (milliseconds since
  epoch) alongside OHLCV.

Synthetic runs have no parquet on disk (they are regenerated from a
seed by the engine), so candles are simply unavailable — the viewer
degrades to indicators + trades + equity and surfaces the reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import PathOutsideRepoError, repo_root, resolve_within_repo

# Browsers choke well before this; M5 over two years is ~150k bars.
# Above the cap we aggregate N→1 (open=first, high=max, low=min,
# close=last, volume=sum) so the shape stays truthful, unlike a stride
# sample that would drop wicks.
MAX_CANDLES = 6000

_SYNTHETIC_PREFIX = "synthetic:"
_OHLC_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class CandleResult:
    """Candles for one run + a human note explaining any shortfall."""

    candles: list[dict[str, Any]]
    note: str | None = None
    resampled_factor: int = 1


def _iso_to_epoch(ts: str | None) -> int | None:
    """ISO-8601 → epoch seconds (UTC when naive); ``None`` passes through."""
    if not ts:
        return None
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


def _rows_from_frame(df: Any) -> list[dict[str, Any]]:
    """Normalise a parquet OHLCV frame into epoch-second candle dicts.

    Accepts either on-disk shape and fails loudly if neither the
    ``time`` index/column nor the OHLC columns are present — a foreign
    parquet is a data problem to surface, not to guess around.
    """
    import pandas as pd

    def _epoch_seconds(dti: pd.DatetimeIndex) -> list[int]:
        # Parquet may persist datetimes at ns/us/ms resolution; normalise
        # to seconds unit-agnostically before reading the int64 view.
        if dti.tz is None:
            dti = dti.tz_localize("UTC")
        return dti.as_unit("s").asi8.tolist()

    frame = df
    if isinstance(frame.index, pd.DatetimeIndex):
        if frame.index.tz is None:
            raise ValueError("parquet has a naive DatetimeIndex; expected tz-aware UTC")
        times = _epoch_seconds(frame.index)
    elif "time" in frame.columns:
        col = frame["time"]
        if pd.api.types.is_datetime64_any_dtype(col):
            times = _epoch_seconds(pd.DatetimeIndex(col))
        else:
            # int64 milliseconds since epoch (stitch_chunks shape).
            times = (col.astype("int64") // 1000).tolist()
    else:
        raise ValueError("parquet has neither a DatetimeIndex nor a 'time' column")

    missing = [c for c in _OHLC_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"parquet missing OHLC columns: {missing}")

    has_volume = "volume" in frame.columns
    opens = frame["open"].tolist()
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    closes = frame["close"].tolist()
    volumes = frame["volume"].tolist() if has_volume else [0.0] * len(times)

    rows: list[dict[str, Any]] = []
    for t, o, h, low, c, v in zip(times, opens, highs, lows, closes, volumes, strict=True):
        o, h, low, c = float(o), float(h), float(low), float(c)
        # A NaN/Inf in any OHLC field (a data gap) would make
        # lightweight-charts throw at setData and blank the whole
        # chart — drop the bar so the rest still renders.
        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(low) and math.isfinite(c)):
            continue
        vol = float(v)
        rows.append(
            {
                "time": int(t),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": vol if math.isfinite(vol) else 0.0,
            }
        )
    rows.sort(key=lambda r: r["time"])
    return rows


def _slice_window(
    rows: list[dict[str, Any]], start: int | None, end: int | None
) -> list[dict[str, Any]]:
    """Keep rows within ``[start, end]`` (inclusive); open-ended when None."""
    if start is None and end is None:
        return rows
    lo = start if start is not None else -(1 << 62)
    hi = end if end is not None else (1 << 62)
    return [r for r in rows if lo <= r["time"] <= hi]


def _resample(rows: list[dict[str, Any]], factor: int) -> list[dict[str, Any]]:
    """Aggregate every ``factor`` consecutive candles into one."""
    if factor <= 1:
        return rows
    out: list[dict[str, Any]] = []
    for i in range(0, len(rows), factor):
        bucket = rows[i : i + factor]
        out.append(
            {
                "time": bucket[0]["time"],
                "open": bucket[0]["open"],
                "high": max(r["high"] for r in bucket),
                "low": min(r["low"] for r in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(r["volume"] for r in bucket),
            }
        )
    return out


def load_candles(
    data_ref: dict[str, Any],
    window: dict[str, Any],
    *,
    root: Path | None = None,
    max_candles: int = MAX_CANDLES,
) -> CandleResult:
    """Load OHLCV candles for a run, sliced to its window.

    Returns an empty candle list with an explanatory ``note`` — never
    raises — when candles are legitimately unavailable (synthetic run,
    missing parquet, path escaping the repo). Genuine parse failures of
    a present parquet still raise, since that is a data-integrity issue
    worth surfacing loudly.
    """
    ref = (data_ref or {}).get("manifest")
    if not ref:
        return CandleResult([], note="run has no data reference")
    if isinstance(ref, str) and ref.startswith(_SYNTHETIC_PREFIX):
        return CandleResult(
            [], note=f"synthetic dataset ({ref}) — candles are not persisted to disk"
        )

    root = root or repo_root()
    try:
        parquet_path = resolve_within_repo(str(ref), root)
    except PathOutsideRepoError as exc:
        return CandleResult([], note=str(exc))
    if not parquet_path.is_file():
        return CandleResult(
            [], note=f"parquet not found on this machine: {ref} (check TD_REPO_ROOT)"
        )

    import pandas as pd

    df = pd.read_parquet(parquet_path)
    rows = _rows_from_frame(df)
    rows = _slice_window(rows, _iso_to_epoch(window.get("start")), _iso_to_epoch(window.get("end")))

    factor = 1
    if len(rows) > max_candles:
        factor = (len(rows) + max_candles - 1) // max_candles
        rows = _resample(rows, factor)
    note = None
    if factor > 1:
        note = f"downsampled {factor}× for display ({len(rows)} candles shown)"
    return CandleResult(rows, note=note, resampled_factor=factor)
