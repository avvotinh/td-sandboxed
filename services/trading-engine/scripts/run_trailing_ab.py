"""Track 5 tier-1 — trailing-tactic A/B matrix (redesign plan 2026-07-02).

Runs the two active trend-followers (``supertrend``, ``donchian_breakout``)
through four exit-tactic variants on ONE manifest window + timeframe with
identical venue, fee, and window — so every delta in the comparison table
is attributable to the exit tactic alone:

* ``baseline``          — hard SL/TP bracket (Phase 12.A defaults).
* ``scaleout``          — Epic 13 Phase 1 overlay: 50% off at +1R, SL→BE,
                          Supertrend ATR(7)×2.1 trail on the remainder.
* ``trailonly``         — Turtle-style (entry-exit-trailing analysis §3.5):
                          full position keeps the original SL, no partial,
                          no BE move; the trail is the only tightener.
* ``scaleout-beoffset`` — scaleout + ``breakeven_offset_pips`` so the BE
                          stop lands at entry + costs instead of raw entry.

The BE offset is cost-recovery, not a free parameter (analysis §7): the
SIM XAUUSD instrument charges ``0.00002 × notional`` per fill (maker =
taker, runner_facade), so a round trip costs ``0.00004 × price`` per oz.
At the 2024–2026 XAUUSD range (~2 000–3 400, mid ≈ 2 600) that is
≈ $0.10/oz = 10 pips (pip = 0.01). FX pairs carry zero instrument fee in
this venue setup, hence no default — pass ``--be-offset-pips`` explicitly
when running an FX manifest with a non-zero-cost venue.

Usage::

    uv run python scripts/run_trailing_ab.py \\
      --manifest manifests/xauusd-2y.json \\
      --timeframe M5 \\
      --out ../../docs/sprint-artifacts/trailing-ab-2y-m5.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal, InvalidOperation
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


# StrategySpec params must stay JSON-primitive (enforced downstream by
# baseline_harness._check_json_primitive_params) — Decimals ride as str.
ParamValue = int | float | str | bool | None

# Phase 12.A defaults for the two eligible trend-followers — identical
# to scripts/run_epic12a_baseline.py so the ``baseline`` variant here
# reproduces the Track 4.1 rows (regression anchor for the matrix).
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
}

# Shared trail settings (Epic 13 Phase 1 numbers). ``tp_atr_mult`` is
# bumped to the safety cap so the hard TP is runaway protection, not an
# exit target — the trail does the exiting.
_TRAIL_COMMON: dict[str, ParamValue] = {
    "trailing_enabled": True,
    "trailing_method": "supertrend",
    "trailing_atr_period": 7,
    "trailing_atr_multiplier": "2.1",
    "safety_tp_atr_mult": "6.0",
    "tp_atr_mult": "6.0",
}

_SCALE_OUT_OVERLAY: dict[str, ParamValue] = {
    "scale_out_enabled": True,
    "scale_out_r_trigger": "1.0",
    "scale_out_close_fraction": "0.5",
    "breakeven_at_r": "1.0",
    **_TRAIL_COMMON,
}

# symbol → cost-recovery BE offset in pips (see module docstring).
_DEFAULT_BE_OFFSET_PIPS: dict[str, str] = {
    "XAUUSD": "10",
}


def _variant_overlays(be_offset_pips: str) -> dict[str, dict[str, ParamValue]]:
    """Return variant name → param overlay, ordered for the report."""
    return {
        "baseline": {},
        "scaleout": dict(_SCALE_OUT_OVERLAY),
        "trailonly": {
            "scale_out_enabled": False,
            # Explicit None: trail-only never moves SL to BE — the
            # trail activates immediately (bracket_scale_out §trail-only).
            "breakeven_at_r": None,
            **_TRAIL_COMMON,
        },
        "scaleout-beoffset": {
            **_SCALE_OUT_OVERLAY,
            "breakeven_offset_pips": be_offset_pips,
        },
    }


def _build_strategies(timeframe: str, *, be_offset_pips: str) -> tuple[StrategySpec, ...]:
    """8 specs: 2 strategies × 4 tactic variants, labels ``name[variant]``."""
    suffix = timeframe_to_bar_suffix(timeframe)
    overlays = _variant_overlays(be_offset_pips)
    return tuple(
        StrategySpec(
            name=name,
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params={**base, **overlay},
            label=f"{name}[{variant}]",
        )
        for name, base in _BASE_PARAMS.items()
        for variant, overlay in overlays.items()
    )


def _pips_arg(text: str) -> str:
    """argparse type for ``--be-offset-pips``: non-negative decimal, kept as str."""
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"invalid pips value: {text!r}") from None
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {text}")
    return text


def _resolve_be_offset(symbol: str, cli_value: str | None) -> str:
    """CLI override wins; otherwise the per-symbol cost map; else fail loudly."""
    if cli_value is not None:
        return cli_value
    try:
        return _DEFAULT_BE_OFFSET_PIPS[symbol.upper()]
    except KeyError:
        raise ValueError(
            f"No default BE offset for symbol {symbol!r} — the offset is "
            "derived from venue costs (see module docstring). Pass "
            "--be-offset-pips explicitly."
        ) from None


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
        help="Bar timeframe (MT-style: M5, M15, …) — must match a manifest entry",
    )
    parser.add_argument(
        "--be-offset-pips",
        type=_pips_arg,
        default=None,
        help=(
            "Override the cost-recovery BE offset (pips) for the "
            "scaleout-beoffset variant. Default: per-symbol cost map "
            f"({_DEFAULT_BE_OFFSET_PIPS})."
        ),
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
        default="track5-trailing-ab",
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

    try:
        be_offset = _resolve_be_offset(manifest.symbol, args.be_offset_pips)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"BE offset (scaleout-beoffset variant): {be_offset} pips")

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

    strategies = _build_strategies(args.timeframe, be_offset_pips=be_offset)
    run_label = (
        f"track5-trailing-ab-{manifest.symbol.lower()}-{args.timeframe.lower()}"
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
        f"\nrunning {len(strategies)} strategy×variant combos on "
        f"{manifest.symbol} {args.window_name} {args.timeframe}…"
    )
    results = run_baseline(config)
    print(f"  done. {len(results)} BacktestResults captured.\n")

    print(
        f"{'strategy[variant]':<34} {'trades':>6} {'win%':>6} {'EV':>8} "
        f"{'PF':>6} {'sharpe':>7} {'maxDD%':>7}"
    )
    for spec, r in zip(config.strategies, results, strict=True):
        m = r.metrics
        if m is None:
            print(f"{spec.display_label:<34} (no metrics)")
            continue
        print(
            f"{spec.display_label:<34} "
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
