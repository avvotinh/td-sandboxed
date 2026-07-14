"""Backtest chart viewer — run ONE cell and render an interactive HTML chart.

Runs a single (strategy × manifest window × timeframe) backtest with the
same venue conventions as the A/B harnesses (HEDGING OMS so every
entry→exit cycle is a discrete trade), then renders a self-contained
TradingView Lightweight Charts HTML report: candlesticks + volume, every
trade's entry/exit markers, initial SL + TP levels, the SL modification
path (breakeven move / trailing ratchets), and the strategy's indicator
overlays (Supertrend line, Donchian bands, Bollinger + RSI pane, optional
trail line / ADX gate pane).

The chart re-reads the SAME parquet shard the backtest consumed and
recomputes indicators by feeding the identical ``Bar`` stream through the
identical indicator classes — plotted lines match what the strategy saw.

Usage::

    uv run python scripts/run_backtest_chart.py \\
      --manifest manifests/xauusd-2y.json \\
      --strategy donchian_breakout --timeframe M5 \\
      --start 2025-01-01 --end 2025-04-01

    # exit-tactic variants from the Track 5 matrix:
    uv run python scripts/run_backtest_chart.py \\
      --manifest manifests/xauusd-2y.json \\
      --strategy supertrend --timeframe M5 --tactic trailonly

Full-window M5 (~142k bars) produces a ~40 MB HTML — prefer --start/--end
slices for day-to-day inspection.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from src.backtesting.bar_converter import dataframe_to_bars
from src.backtesting.dataset.baseline_harness import timeframe_to_bar_suffix
from src.backtesting.dataset.manifest import DatasetManifest
from src.backtesting.job_config import (
    BacktestJobConfig,
    ParquetDataSpec,
    VenueSpec,
)
from src.backtesting.reports.chart_data import build_chart_payload
from src.backtesting.reports.chart_writer import write_chart_html
from src.backtesting.runner_facade import (
    build_instrument_and_bar_type,
    load_parquet_bars_frame,
    run_backtest,
)

ParamValue = int | float | str | bool | None

# Phase 12.A defaults — identical to scripts/run_epic12a_baseline.py /
# run_trailing_ab.py so a chart cell reproduces the verdict-table rows.
_BASE_PARAMS: dict[str, dict[str, ParamValue]] = {
    "supertrend": {
        "period": 10,
        "multiplier": 3.0,
        "atr_period": 14,
        "sl_atr_mult": "1.5",
        "tp_atr_mult": "3.0",
        "risk_percent": "0.5",
    },
    "donchian_breakout": {
        "channel_period": 20,
        "atr_period": 14,
        "sl_atr_mult": "2.0",
        "tp_atr_mult": "4.0",
        "risk_percent": "0.5",
    },
    "mean_reversion": {
        "bb_period": 20,
        "num_std": 2.0,
        "rsi_period": 14,
        "oversold": 0.3,
        "overbought": 0.7,
        "atr_period": 14,
        "sl_atr_mult": "1.0",
        "tp_atr_mult": "2.0",
        "risk_percent": "0.5",
    },
}

# Exit-tactic overlays from the Track 5 trailing A/B matrix
# (scripts/run_trailing_ab.py) — kept in sync by the shared numbers, so
# a chart of e.g. supertrend[trailonly] shows exactly the matrix cell.
_TRAIL_COMMON: dict[str, ParamValue] = {
    "trailing_enabled": True,
    "trailing_method": "supertrend",
    "trailing_atr_period": 7,
    "trailing_atr_multiplier": "2.1",
    "safety_tp_atr_mult": "6.0",
    "tp_atr_mult": "6.0",
}

_TACTIC_OVERLAYS: dict[str, dict[str, ParamValue]] = {
    "baseline": {},
    "scaleout": {
        "scale_out_enabled": True,
        "scale_out_r_trigger": "1.0",
        "scale_out_close_fraction": "0.5",
        "breakeven_at_r": "1.0",
        **_TRAIL_COMMON,
    },
    "trailonly": {
        "scale_out_enabled": False,
        "breakeven_at_r": None,
        **_TRAIL_COMMON,
    },
}


def _utc_date(text: str) -> datetime:
    """argparse type: ``YYYY-MM-DD`` (or full ISO) → tz-aware UTC datetime."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid date: {text!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _params_json(text: str) -> dict[str, ParamValue]:
    """argparse type for ``--params``: a JSON object of overrides."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("--params must be a JSON object")
    return value


def _default_out(args: argparse.Namespace, symbol: str) -> Path:
    stem = f"{args.strategy}-{symbol.lower()}-{args.timeframe.lower()}-{args.window_name}"
    if args.tactic != "baseline":
        stem += f"-{args.tactic}"
    if args.start or args.end:
        def fmt(d: datetime | None) -> str:
            return d.strftime("%Y%m%d") if d else "x"

        stem += f"-{fmt(args.start)}-{fmt(args.end)}"
    return Path("reports/charts") / f"{stem}.html"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/xauusd-2y.json"),
        help="Dataset manifest (default: %(default)s)",
    )
    parser.add_argument(
        "--strategy",
        required=True,
        choices=sorted(_BASE_PARAMS),
        help="Strategy to run and chart",
    )
    parser.add_argument(
        "--timeframe",
        default="M5",
        help="MT-style timeframe matching a manifest entry (default: %(default)s)",
    )
    parser.add_argument(
        "--window-name",
        default="in_sample",
        help="Manifest window (default: %(default)s)",
    )
    parser.add_argument(
        "--tactic",
        default="baseline",
        choices=sorted(_TACTIC_OVERLAYS),
        help="Exit-tactic overlay from the Track 5 matrix (default: %(default)s)",
    )
    parser.add_argument(
        "--params",
        type=_params_json,
        default={},
        help="JSON object of strategy-param overrides (merged last)",
    )
    parser.add_argument(
        "--start",
        type=_utc_date,
        default=None,
        help="Slice start (YYYY-MM-DD, UTC) — defaults to the window start",
    )
    parser.add_argument(
        "--end",
        type=_utc_date,
        default=None,
        help="Slice end (YYYY-MM-DD, UTC) — defaults to the window end",
    )
    parser.add_argument(
        "--starting-balance",
        type=Decimal,
        default=Decimal("100000"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output HTML path (default: reports/charts/<auto>.html)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show Nautilus engine logs (default: suppressed)",
    )
    args = parser.parse_args(argv)

    if not args.verbose:
        logging.disable(logging.CRITICAL)

    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 1

    manifest = DatasetManifest.load_json(args.manifest)
    entry = next(
        (
            e
            for e in manifest.entries
            if e.window_name == args.window_name
            and e.timeframe == args.timeframe
        ),
        None,
    )
    if entry is None:
        available = sorted(
            f"{e.window_name}/{e.timeframe}" for e in manifest.entries
        )
        print(
            f"no manifest entry for window={args.window_name!r} "
            f"timeframe={args.timeframe!r}; available: {available}",
            file=sys.stderr,
        )
        return 1

    start = args.start or entry.start
    end = args.end or entry.end
    if end <= start:
        print(f"end ({end}) must be after start ({start})", file=sys.stderr)
        return 1

    params: dict[str, ParamValue] = {
        **_BASE_PARAMS[args.strategy],
        **_TACTIC_OVERLAYS[args.tactic],
        **args.params,
    }
    label = f"{args.strategy}[{args.tactic}]"
    print(
        f"cell: {label} {manifest.symbol} {args.timeframe} "
        f"{args.window_name} {start:%Y-%m-%d} -> {end:%Y-%m-%d}"
    )

    job = BacktestJobConfig(
        strategy=args.strategy,
        strategy_params={k: v for k, v in params.items()},
        venue=VenueSpec(
            name="SIM",
            starting_balance=args.starting_balance,
            currency="USD",
            oms_type="HEDGING",  # discrete trades — one position per cycle
        ),
        instrument_symbol=manifest.symbol,
        bar_type_suffix=timeframe_to_bar_suffix(args.timeframe),
        data=ParquetDataSpec(path=entry.parquet_path),
        start=start,
        end=end,
    )

    print("running backtest…")
    result = run_backtest(job)
    print(
        f"done: {len(result.trades)} trades, "
        f"final balance {result.final_balance:,.2f}"
    )

    print("building chart payload…")
    df = load_parquet_bars_frame(entry.parquet_path).loc[start:end]
    if df.empty:
        print("no bars in the requested slice", file=sys.stderr)
        return 1
    instrument, bar_type = build_instrument_and_bar_type(
        manifest.symbol, job.bar_type_suffix
    )
    bars = dataframe_to_bars(df, bar_type=bar_type, instrument=instrument)
    payload = build_chart_payload(
        df=df,
        bars=bars,
        result=result,
        strategy_name=args.strategy,
        params=params,
        symbol=manifest.symbol,
        timeframe=args.timeframe,
        window_label=args.window_name,
        display_label=label,
    )

    out = args.out or _default_out(args, manifest.symbol)
    written = write_chart_html(payload, out)
    size_mb = written.stat().st_size / 1_048_576
    print(f"chart written: {written} ({size_mb:.1f} MB)")
    print("open it in a browser — fully offline, no network needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
