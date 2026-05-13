"""Consolidate a directory of Go-fetched Parquet shards into one window.

The chunked tv-cli campaign (services/tv-api/scripts/chunked-fetch-*.sh)
writes one Parquet + sidecar per anchor because the TradingView server
caps each anchor at ~5500 bars. Downstream backtest harness
(``baseline_harness._index_entries``) keys entries by
``(window_name, timeframe) → 1 DatasetEntry``, so 37 sub-window
manifests cannot be consumed as a single canonical ``in_sample``
window.

This script stitches the chunks into a single deduped Parquet plus a
matching single-entry :class:`DatasetManifest`, suitable as the
canonical dataset path referenced by ``configs/datasets/*.yaml`` and
loaded by the validation harness.

Usage::

    uv run python scripts/stitch_chunks_to_window.py \\
      --chunks-dir /…/XAUUSD/M5/in_sample/chunks \\
      --out-parquet /…/XAUUSD/M5/in_sample.parquet \\
      --out-manifest /…/XAUUSD/M5/in_sample.parquet.manifest.json \\
      --window-name in_sample --window-kind in_sample \\
      --timeframe 5 --symbol XAUUSD \\
      --start 2024-01-01T00:00:00Z --end 2026-01-01T00:00:00Z
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.backtesting.data_cache import ContentHashFingerprint
from src.backtesting.dataset.manifest import DatasetEntry, DatasetManifest
from src.backtesting.dataset.pipeline import detect_gaps
from src.backtesting.dataset.spec import WindowKind


_MS_TO_NS = 1_000_000


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"start/end must be tz-aware ISO, got {value!r}")
    return parsed.astimezone(UTC)


def _load_and_dedupe(chunks_dir: Path) -> pd.DataFrame:
    parquet_files = sorted(chunks_dir.glob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"no *.parquet shards in {chunks_dir}")

    frames = [pd.read_parquet(p) for p in parquet_files]
    raw = pd.concat(frames, ignore_index=True)
    raw_rows = len(raw)

    # Each chunk overlaps its neighbour by ~5 days to absorb weekend gaps;
    # the same bar can appear in two adjacent shards. Dedupe on `time`
    # (ms since epoch) — the unique key per-bar.
    deduped = (
        raw.drop_duplicates(subset=["time"], keep="first")
        .sort_values("time")
        .reset_index(drop=True)
    )
    dropped = raw_rows - len(deduped)
    print(  # noqa: T201
        f"stitched {len(parquet_files)} shards: "
        f"raw_rows={raw_rows:,} deduped_rows={len(deduped):,} "
        f"overlap_dupes_dropped={dropped:,}"
    )
    return deduped


def _build_entry(
    df: pd.DataFrame,
    *,
    parquet_path: Path,
    timeframe: str,
    window_name: str,
    window_kind: WindowKind,
    window_start: datetime,
    window_end: datetime,
    max_gap_hours: float,
) -> DatasetEntry:
    if df.empty:
        raise ValueError("cannot build entry from empty DataFrame")

    min_ts_ns = int(df["time"].iloc[0]) * _MS_TO_NS
    max_ts_ns = int(df["time"].iloc[-1]) * _MS_TO_NS
    fingerprint = ContentHashFingerprint(
        min_ts=min_ts_ns,
        max_ts=max_ts_ns,
        row_count=len(df),
    )

    # detect_gaps expects a tz-aware DatetimeIndex; convert ms → ns → UTC.
    gap_df = df.set_index(
        pd.to_datetime(df["time"], unit="ms", utc=True)
    )
    gaps = detect_gaps(
        gap_df,
        timeframe=timeframe,
        window_name=window_name,
        max_gap_hours=max_gap_hours,
    )

    return DatasetEntry(
        timeframe=timeframe,
        window_name=window_name,
        window_kind=window_kind,
        start=window_start,
        end=window_end,
        parquet_path=parquet_path,
        fingerprint=fingerprint,
        row_count=len(df),
        gaps=gaps,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-dir", type=Path, required=True)
    parser.add_argument("--out-parquet", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    parser.add_argument("--spec-name", default="xauusd-validation")
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="5")
    parser.add_argument("--window-name", default="in_sample")
    parser.add_argument(
        "--window-kind",
        choices=[k.value for k in WindowKind],
        default=WindowKind.IN_SAMPLE.value,
    )
    parser.add_argument(
        "--start",
        type=_parse_iso_utc,
        required=True,
        help="Window start (ISO-8601 with timezone, e.g. 2024-01-01T00:00:00Z).",
    )
    parser.add_argument(
        "--end",
        type=_parse_iso_utc,
        required=True,
        help="Window end (ISO-8601 with timezone, e.g. 2026-01-01T00:00:00Z).",
    )
    parser.add_argument("--max-gap-hours", type=float, default=48.0)
    args = parser.parse_args(argv)

    df = _load_and_dedupe(args.chunks_dir)

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out_parquet, index=False)
    print(f"wrote {args.out_parquet}  rows={len(df):,}")  # noqa: T201

    entry = _build_entry(
        df,
        parquet_path=args.out_parquet.resolve(),
        timeframe=args.timeframe,
        window_name=args.window_name,
        window_kind=WindowKind(args.window_kind),
        window_start=args.start,
        window_end=args.end,
        max_gap_hours=args.max_gap_hours,
    )
    manifest = DatasetManifest(
        spec_name=args.spec_name,
        dataset_version=args.dataset_version,
        symbol=args.symbol,
        generated_at=datetime.now(UTC),
        max_gap_hours=args.max_gap_hours,
        entries=(entry,),
    )
    manifest.save_json(args.out_manifest)
    print(  # noqa: T201
        f"wrote {args.out_manifest}  "
        f"fingerprint={entry.fingerprint.sha256()}  gaps={len(entry.gaps)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
