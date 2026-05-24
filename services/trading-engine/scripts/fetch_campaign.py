"""Epic 16 historical-data fetch-campaign driver (story 16.3).

Drives the Go ``tv-cli`` across the symbol × timeframe × window matrix of a
:class:`DatasetSpec`, stepping the ``-to`` anchor backward (the TradingView
server caps ~5500 bars per anchor) until the window start OR the server
history floor is reached, then delegates de-duplication + canonical
manifest generation to ``scripts/stitch_chunks_to_window.py`` per shard.

Design notes
------------
* **Adaptive anchoring** — rather than guessing a fixed calendar step per
  timeframe, each call fetches ``[window.start, anchor]`` (the server
  returns ~5500 bars back from ``anchor`` regardless of ``-from``); the
  driver reads the chunk's actual minimum timestamp and sets the next
  ``anchor`` to it. The loop stops when the chunk reaches ``window.start``
  (target met), stops making progress (history floor), or ``tv-cli``
  reports zero bars. This handles the per-timeframe floor automatically
  (epic-16 Decision 2: M5 will floor shallower than the 5y target).
* **Credentials** — ``tv-cli`` runs with cwd = ``services/tv-api`` so it
  loads that directory's ``.env`` (``SESSION_ID`` / ``SESSION_SIGN``). This
  driver never reads or logs those values.
* **OANDA** — all prices come from OANDA; the fetch symbol is
  ``OANDA:<TICKER>`` (``tv-cli`` strips the prefix back to the bare ticker
  for the manifest, matching ``configs/datasets/*.yaml``).
* **--dry-run** — prints the planned first ``tv-cli`` call + the stitch
  command per shard and exits without touching the network or filesystem.
  This is the credential-free verification path.

Usage::

    uv run python scripts/fetch_campaign.py --spec configs/datasets/xauusd-5y.yaml
    uv run python scripts/fetch_campaign.py --spec configs/datasets/xauusd-5y.yaml --dry-run
    uv run python scripts/fetch_campaign.py --spec ... --timeframes H4,H1   # subset
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.backtesting.dataset.fetch_campaign import (
    build_fetch_argv,
    chunk_path,
    to_oanda_symbol,
    tv_timeframe,
)
from src.backtesting.dataset.spec import DatasetSpec, WindowSpec

# scripts/ → trading-engine → services → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data"
_DEFAULT_TV_API_DIR = _REPO_ROOT / "services" / "tv-api"
_TRADING_ENGINE_DIR = Path(__file__).resolve().parents[1]
_STITCH_SCRIPT = _TRADING_ENGINE_DIR / "scripts" / "stitch_chunks_to_window.py"

# Safety ceiling on stepped calls per shard — a 5y M5 shard is ~30-75
# anchors; 200 leaves headroom while bounding a runaway loop if the
# floor-detection ever fails to terminate.
_MAX_ANCHORS = 200

# Per-anchor tv-cli timeout. A live TradingView session can hang on a
# dropped connection or a rate-limit that holds the socket open; without a
# bound, one stuck call orphans a multi-hour campaign. Tunable via
# --fetch-timeout-s (M1/dense intraday anchors are slower to materialise).
_FETCH_TIMEOUT_S = 300


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_cli(tv_api_dir: Path, cli: str) -> Path:
    """Resolve the tv-cli binary, tolerating the Windows ``.exe`` suffix."""
    candidate = (tv_api_dir / cli).resolve()
    if candidate.exists():
        return candidate
    exe = candidate.with_suffix(".exe")
    if exe.exists():
        return exe
    raise FileNotFoundError(
        f"tv-cli not found at {candidate} (or .exe). Build it first:\n"
        f"  cd {tv_api_dir} && go build -o bin/tv-cli ./cmd/tv-cli"
    )


def _chunk_min_dt(parquet_path: Path) -> datetime:
    """Return the earliest bar timestamp in a chunk (``time`` is ms epoch)."""
    df = pd.read_parquet(parquet_path, columns=["time"])
    if df.empty:
        raise ValueError(f"chunk {parquet_path} has no rows")
    return datetime.fromtimestamp(int(df["time"].min()) / 1000, tz=UTC)


def _stitch_argv(
    *,
    chunks_dir: Path,
    out_parquet: Path,
    spec: DatasetSpec,
    tv_tf: str,
    window: WindowSpec,
) -> list[str]:
    return [
        sys.executable,
        str(_STITCH_SCRIPT),
        "--chunks-dir", str(chunks_dir),
        "--out-parquet", str(out_parquet),
        "--out-manifest", str(out_parquet) + ".manifest.json",
        "--spec-name", spec.name,
        "--dataset-version", spec.dataset_version,
        "--symbol", spec.symbol,
        # TODO(16.6): the manifest entry carries the tv value ("5","240"),
        # but the DatasetSpec timeframe label is "M5"/"H4". Verify how
        # baseline_harness._index_entries keys entries before materialize —
        # a label-vs-tv mismatch would be a silent lookup miss.
        "--timeframe", tv_tf,
        "--window-name", window.name,
        "--window-kind", window.kind.value,
        "--start", _iso_z(window.start),
        "--end", _iso_z(window.end),
        "--max-gap-hours", str(spec.max_gap_hours),
    ]


def _fetch_shard(
    *,
    spec: DatasetSpec,
    tf_label: str,
    window: WindowSpec,
    cli: Path,
    data_root: Path,
    tv_api_dir: Path,
    fetch_timeout_s: int,
    response_timeout_ms: int,
    dry_run: bool,
) -> None:
    """Fetch + stitch one (timeframe, window) shard."""
    tv_tf = tv_timeframe(tf_label)
    oanda = to_oanda_symbol(spec.symbol)
    chunks_dir = chunk_path(data_root, spec.symbol, tf_label, window.name, 0).parent
    out_parquet = chunks_dir.parent / f"{window.name}.parquet"

    print(f"\n=== {spec.symbol} {tf_label} {window.name} "
          f"[{_iso_z(window.start)} -> {_iso_z(window.end)}] ===")

    anchor = window.end
    prev_min: datetime | None = None
    for idx in range(_MAX_ANCHORS):
        out = chunk_path(data_root, spec.symbol, tf_label, window.name, idx)
        argv = build_fetch_argv(
            cli_path=str(cli),
            oanda_symbol=oanda,
            tv_tf=tv_tf,
            from_dt=window.start,
            to_dt=anchor,
            out_path=out,
            spec_name=spec.name,
            dataset_version=spec.dataset_version,
            window_name=window.name,
            window_kind=window.kind.value,
            response_timeout_ms=response_timeout_ms,
        )
        if dry_run:
            print("  [dry-run] fetch:", shlex.join(argv))
            print("  [dry-run] stitch:", shlex.join(_stitch_argv(
                chunks_dir=chunks_dir, out_parquet=out_parquet,
                spec=spec, tv_tf=tv_tf, window=window,
            )))
            print("  [dry-run] (showing first anchor only; live run steps "
                  "backward until window start or history floor)")
            return

        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                argv, cwd=tv_api_dir, capture_output=True, text=True,
                encoding="utf-8", check=False, timeout=fetch_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"tv-cli timed out after {fetch_timeout_s}s on {spec.symbol} "
                f"{tf_label} anchor {idx} (to={_iso_z(anchor)}). Re-run the "
                f"campaign (or raise --fetch-timeout-s for dense intraday)."
            ) from exc
        if proc.returncode != 0:
            if "zero bars" in (proc.stderr or "").lower():
                print(f"  anchor {idx}: history floor reached "
                      f"(server returned no bars before {_iso_z(anchor)})")
                break
            sys.stderr.write((proc.stdout or "") + (proc.stderr or ""))
            raise RuntimeError(
                f"tv-cli failed (exit {proc.returncode}) on {spec.symbol} "
                f"{tf_label} anchor {idx}"
            )
        # tv-cli is atomic (no partial file on error), but guard against an
        # exit-0-with-empty-output edge before reading the chunk.
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError(
                f"tv-cli exited 0 but wrote no chunk at {out} "
                f"({spec.symbol} {tf_label} anchor {idx})"
            )

        min_dt = _chunk_min_dt(out)
        print(f"  anchor {idx}: [{_iso_z(min_dt)} -> {_iso_z(anchor)}]")
        if min_dt <= window.start:
            print(f"  reached window start after {idx + 1} anchors")
            break
        if prev_min is not None and min_dt >= prev_min:
            print(f"  history floor reached at {_iso_z(min_dt)} "
                  f"(no progress) - actual depth shallower than target")
            break
        prev_min = min_dt
        anchor = min_dt
    else:
        raise RuntimeError(
            f"{spec.symbol} {tf_label} {window.name}: exceeded "
            f"{_MAX_ANCHORS} anchors without terminating"
        )

    # Delegate dedupe + canonical single-entry manifest to the canonical tool.
    stitch = _stitch_argv(
        chunks_dir=chunks_dir, out_parquet=out_parquet,
        spec=spec, tv_tf=tv_tf, window=window,
    )
    subprocess.run(stitch, cwd=_TRADING_ENGINE_DIR, check=True)
    print(f"  stitched -> {out_parquet}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True,
                        help="Path to a configs/datasets/*.yaml DatasetSpec.")
    parser.add_argument("--data-root", type=Path, default=_DEFAULT_DATA_ROOT,
                        help=f"Output root (default {_DEFAULT_DATA_ROOT}).")
    parser.add_argument("--tv-api-dir", type=Path, default=_DEFAULT_TV_API_DIR,
                        help="tv-api dir (cwd for tv-cli, loads its .env).")
    parser.add_argument("--cli", default="bin/tv-cli",
                        help="tv-cli path relative to --tv-api-dir.")
    parser.add_argument("--timeframes", default="",
                        help="Comma-separated subset of the spec timeframes.")
    parser.add_argument("--windows", default="",
                        help="Comma-separated subset of the spec window names.")
    parser.add_argument("--fetch-timeout-s", type=int, default=_FETCH_TIMEOUT_S,
                        help="Per-anchor tv-cli timeout in seconds "
                             f"(default {_FETCH_TIMEOUT_S}).")
    parser.add_argument("--response-timeout-ms", type=int, default=8000,
                        help="tv-cli per-batch response wait (default 8000; "
                             "tv-cli's own default of 2000 flakes on the "
                             "ReplayMode initial batch).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned commands; no network/filesystem.")
    args = parser.parse_args(argv)

    spec = DatasetSpec.from_yaml(args.spec)
    data_root = args.data_root.resolve()
    tv_api_dir = args.tv_api_dir.resolve()

    tf_filter = {t.strip() for t in args.timeframes.split(",") if t.strip()}
    win_filter = {w.strip() for w in args.windows.split(",") if w.strip()}
    timeframes = [t for t in spec.timeframes if not tf_filter or t in tf_filter]
    windows = [w for w in spec.windows if not win_filter or w.name in win_filter]

    cli = Path(args.cli)  # placeholder for dry-run
    if not args.dry_run:
        cli = _resolve_cli(tv_api_dir, args.cli)

    print(f"campaign: {spec.symbol} v{spec.dataset_version} "
          f"timeframes={timeframes} windows={[w.name for w in windows]} "
          f"data_root={data_root}{' (DRY RUN)' if args.dry_run else ''}")

    for tf_label in timeframes:
        for window in windows:
            _fetch_shard(
                spec=spec, tf_label=tf_label, window=window, cli=cli,
                data_root=data_root, tv_api_dir=tv_api_dir,
                fetch_timeout_s=args.fetch_timeout_s,
                response_timeout_ms=args.response_timeout_ms,
                dry_run=args.dry_run,
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
