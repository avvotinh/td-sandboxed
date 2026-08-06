"""Track 5.1 — entry-filter A/B matrix (redesign plan 2026-07-02).

Runs the active roster through the Track 5.1 entry filters on top of
each strategy's best exit tactic from the trailing A/B
(``docs/sprint-artifacts/trailing-ab-2y-verdict.md``):

* ``supertrend``  — M5 rides **trail-only**, M15 rides
  **scale-out + BE-offset** (its best cells).
* ``donchian_breakout`` — M5 rides **bare** (no tactic — tactics hurt
  it on M5), M15 rides **scale-out + BE-offset**.
* ``mean_reversion``   — bare (its tactic story is Track 4.3's regime
  gate, not exits).

Filter variants (all config-only, default-OFF fields shipped in the
Track 5.1 change):

* ``adx``     — ADX(14) >= 25 entry gate (trend strategies only).
* ``session`` — trend: London+NY 07:00-16:00 America/New_York,
  force-flatten outside; MR: Asian low-vol 19:00-03:00
  America/New_York (overnight wrap), block-entry-only.
* ``cross``   — donchian edge-triggered breakout episodes
  (``entry_on_cross_only``).
* ``recross`` — MR snap-back entry (``entry_mode="recross"``).

Each strategy's no-filter anchor row reproduces the corresponding
trailing-A/B (or 12.A baseline) cell, pinning the comparison.

Success criterion (Track 3 research + 4.1 verdict §2.5): DD compression
and PF uplift at materially LOWER trade count — not Sharpe alone.

Usage::

    uv run python scripts/run_entry_filter_ab.py \\
      --manifest manifests/xauusd-2y.json \\
      --timeframe M5 \\
      --out ../../docs/sprint-artifacts/entry-filter-ab-2y-m5.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

from src.lab.dataset.baseline_harness import (
    BaselineConfig,
    StrategySpec,
    run_baseline,
    timeframe_to_bar_suffix,
)
from src.lab.dataset.comparison_report import (
    BaselineFilter,
    render_comparison_report,
)
from src.lab.dataset.manifest import DatasetManifest
from src.lab.job_config import PropFirmSpec, VenueSpec


ParamValue = int | float | str | bool | None
Params = dict[str, ParamValue]

# --- Base strategy params (Phase 12.A defaults) -----------------------

_BASE_PARAMS: dict[str, Params] = {
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

# --- Exit-tactic overlays (winners per trailing-ab-2y-verdict.md) ------

_TRAIL_COMMON: Params = {
    "trailing_enabled": True,
    "trailing_method": "supertrend",
    "trailing_atr_period": 7,
    "trailing_atr_multiplier": "2.1",
    "safety_tp_atr_mult": "6.0",
    "tp_atr_mult": "6.0",
}
_TRAILONLY: Params = {
    "scale_out_enabled": False,
    "breakeven_at_r": None,
    **_TRAIL_COMMON,
}
_SCALEOUT_BEOFFSET: Params = {
    "scale_out_enabled": True,
    "scale_out_r_trigger": "1.0",
    "scale_out_close_fraction": "0.5",
    "breakeven_at_r": "1.0",
    "breakeven_offset_pips": "10",  # XAUUSD SIM cost recovery
    **_TRAIL_COMMON,
}

# strategy → timeframe → tactic overlay (the per-cell winners).
_TACTIC_BY_CELL: dict[str, dict[str, Params]] = {
    "supertrend": {"M5": _TRAILONLY, "M15": _SCALEOUT_BEOFFSET},
    "donchian_breakout": {"M5": {}, "M15": _SCALEOUT_BEOFFSET},
    "mean_reversion": {"M5": {}, "M15": {}},
}

# --- Track 5.1 filter overlays ----------------------------------------

_ADX_GATE: Params = {"adx_gate_min": "25", "adx_gate_period": 14}
# Trend window: London open → NY afternoon (session-filters research).
_SESSION_TREND: Params = {
    "session_filter_tz": "America/New_York",
    "session_filter_open_hour": 7,
    "session_filter_open_minute": 0,
    "session_filter_close_hour": 16,
    "session_filter_close_minute": 0,
    "session_filter_exit_policy": "flatten",
}
# MR window: Asian low-vol overnight wrap; entries blocked outside, open
# positions keep their middle-band exit.
_SESSION_MR: Params = {
    "session_filter_tz": "America/New_York",
    "session_filter_open_hour": 19,
    "session_filter_open_minute": 0,
    "session_filter_close_hour": 3,
    "session_filter_close_minute": 0,
    "session_filter_exit_policy": "block_entry",
}
_CROSS_ONLY: Params = {"entry_on_cross_only": True}
_RECROSS: Params = {"entry_mode": "recross"}

# strategy → ordered {variant label: filter overlay}. "none" anchors the
# comparison against the trailing-A/B cell.
_FILTER_VARIANTS: dict[str, dict[str, Params]] = {
    "supertrend": {
        "none": {},
        "adx": _ADX_GATE,
        "session": _SESSION_TREND,
        "adx+session": {**_ADX_GATE, **_SESSION_TREND},
    },
    "donchian_breakout": {
        "none": {},
        "adx": _ADX_GATE,
        "session": _SESSION_TREND,
        "cross": _CROSS_ONLY,
        "adx+session+cross": {**_ADX_GATE, **_SESSION_TREND, **_CROSS_ONLY},
    },
    "mean_reversion": {
        "none": {},
        "recross": _RECROSS,
        "session": _SESSION_MR,
        "recross+session": {**_RECROSS, **_SESSION_MR},
    },
}


def _build_strategies(timeframe: str) -> tuple[StrategySpec, ...]:
    """13 specs: roster × filter variants on each cell's tactic winner."""
    suffix = timeframe_to_bar_suffix(timeframe)
    specs: list[StrategySpec] = []
    for name, variants in _FILTER_VARIANTS.items():
        tactic = _TACTIC_BY_CELL[name][timeframe]
        base = {**_BASE_PARAMS[name], **tactic}
        specs.extend(
            StrategySpec(
                name=name,
                timeframe=timeframe,
                bar_type_suffix=suffix,
                params={**base, **overlay},
                label=f"{name}[{variant}]",
            )
            for variant, overlay in variants.items()
        )
    return tuple(specs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/xauusd-2y.json"),
        help="Path to the dataset manifest (default: %(default)s)",
    )
    parser.add_argument(
        "--window-name",
        default="in_sample",
        help="DatasetManifest window to backtest (default: %(default)s)",
    )
    parser.add_argument(
        "--timeframe",
        default="M5",
        choices=sorted({tf for m in _TACTIC_BY_CELL.values() for tf in m}),
        help="Bar timeframe — must have a tactic-winner mapping",
    )
    parser.add_argument(
        "--ftmo-preset",
        type=Path,
        default=Path("src/lab/presets/ftmo.yaml"),
        help="FTMO preset YAML (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Markdown report output path",
    )
    parser.add_argument(
        "--account-id",
        default="track51-entry-filter-ab",
        help="Account id stamped into the prop-firm compliance actor",
    )
    parser.add_argument(
        "--starting-balance",
        type=Decimal,
        default=Decimal("100000"),
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
    if not args.ftmo_preset.exists():
        print(f"FTMO preset not found: {args.ftmo_preset}", file=sys.stderr)
        return 1

    manifest = DatasetManifest.load_json(args.manifest)
    print(
        f"loaded manifest: {manifest.spec_name} v{manifest.dataset_version}  "
        f"symbol={manifest.symbol}"
    )
    for e in manifest.entries:
        print(
            f"  {e.window_name} {e.timeframe} rows={e.row_count} "
            f"fp={e.fingerprint.sha256()}"
        )

    venue = VenueSpec(
        name="SIM",
        starting_balance=args.starting_balance,
        currency="USD",
        oms_type="HEDGING",  # per Epic 13.9 — trade-by-trade reporting
    )
    prop_firm = PropFirmSpec(
        preset_path=args.ftmo_preset,
        account_id=args.account_id,
        session_timezone="Europe/Berlin",
        max_drawdown_method="equity_peak",
    )

    strategies = _build_strategies(args.timeframe)
    run_label = (
        f"track51-entry-filter-ab-{manifest.symbol.lower()}-{args.timeframe.lower()}"
    )
    config = BaselineConfig(
        run_label=run_label,
        manifest=manifest,
        window_name=args.window_name,
        venue=venue,
        strategies=strategies,
        prop_firm=prop_firm,
    )

    print(
        f"\nrunning {len(strategies)} strategy x filter combos on "
        f"{manifest.symbol} {args.window_name} {args.timeframe}…"
    )
    results = run_baseline(config)
    print(f"  done. {len(results)} BacktestResults captured.\n")

    print(
        f"{'strategy[filter]':<42} {'trades':>6} {'win%':>6} {'EV':>8} "
        f"{'PF':>6} {'sharpe':>7} {'maxDD%':>7}"
    )
    for spec, r in zip(config.strategies, results, strict=True):
        m = r.metrics
        if m is None:
            print(f"{spec.display_label:<42} (no metrics)")
            continue
        print(
            f"{spec.display_label:<42} "
            f"{m.trades.total_trades:>6} "
            f"{m.trades.win_rate * 100:>5.1f}% "
            f"{m.pnl.expectancy:>+8.3f} "
            f"{m.pnl.profit_factor:>6.3f} "
            f"{m.risk.sharpe_ratio:>+7.3f} "
            f"{m.drawdown.max_overall_dd_pct:>7.3f}"
        )

    filter_ = BaselineFilter()
    table_md = render_comparison_report(results, baseline_filter=filter_)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table_md + "\n", encoding="utf-8")
    print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
