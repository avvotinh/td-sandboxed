"""Phase 12.A — in-sample baseline run on all 6 production strategies.

Pins the canonical XAUUSD M5 in_sample window from the Epic 12.7.0
dataset, runs ``run_baseline()`` (Story 12.2) across every strategy
in the production registry, applies the Decision §2 acceptance filter
(Story 12.3), and writes a side-by-side markdown comparison report to
``docs/sprint-artifacts/epic-12-baseline-comparison.md``.

This is the **input** for Story 12.7b (parameter sweep on top 2-3
filter-passing strategies). It is intentionally a one-shot operator
script rather than a CLI subcommand because the experiment is run
once per dataset bump — the CLI footprint already covers ``run`` /
``sweep`` / ``walkforward`` / ``ab`` for recurring use.

Usage::

    uv run python scripts/run_epic12a_baseline.py \\
      --manifest manifests/xauusd-validation-v1.json \\
      --out      ../../docs/sprint-artifacts/epic-12-baseline-comparison.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from pathlib import Path

from src.backtesting.dataset.baseline_harness import (
    BaselineConfig,
    StrategySpec,
    run_baseline,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.comparison_report import (
    BaselineFilter,
    render_comparison_report,
)
from src.backtesting.dataset.manifest import DatasetManifest
from src.backtesting.job_config import PropFirmSpec, VenueSpec


# Production strategies (registry keys) + default-ish params. We
# intentionally use each strategy's __post_init__ defaults wherever
# possible (`scale_out_enabled` stays False because Epic 13 ships
# default-OFF — this baseline is the pre-tactic comparison).
#
# Parameters are timeframe-independent except where noted: the same
# defaults are used on M5 and M15 so the comparison shows pure
# timeframe-effect, not param-and-timeframe co-variation.
# Epic 13 Phase 1 scale-out overlay applied to trend-followers that
# inherit ``BracketScaleOutMixin`` (Supertrend story 13.5, Donchian
# story 13.10, MA crossover story 13.11). Mean-reversion strategies
# are intentionally excluded per Story 13.8 firm-config wiring —
# natural target exits, scale-out + uncapped trail is the wrong shape.
_SCALE_OUT_OVERLAY: dict[str, object] = {
    "scale_out_enabled": True,
    "scale_out_r_trigger": "1.0",
    "scale_out_close_fraction": "0.5",
    "breakeven_at_r": "1.0",
    "trailing_enabled": True,
    "trailing_method": "supertrend",
    "trailing_atr_period": 7,
    "trailing_atr_multiplier": "2.1",
    "safety_tp_atr_mult": "6.0",
    # When scale-out is active, the hard TP becomes an anti-runaway
    # cap rather than an exit target — bump it to 6 × ATR so the
    # uncapped trail can run.
    "tp_atr_mult": "6.0",
}
_SCALE_OUT_STRATEGIES: frozenset[str] = frozenset(
    {"supertrend", "donchian_breakout", "ma_crossover"}
)


def _build_strategies(timeframe: str, *, scale_out: bool = False) -> tuple[StrategySpec, ...]:
    """Return StrategySpec tuple bound to ``timeframe`` (e.g. ``"M5"``).

    When ``scale_out=True``, the Epic 13 Phase 1 overlay is applied to
    strategies in ``_SCALE_OUT_STRATEGIES``; other strategies keep their
    defaults so the comparison isolates the tactic effect on the
    eligible trend-followers without mixing in tactic-incompatible
    strategies (mean-reversion + MA crossover).

    The bar-type suffix is derived via :func:`timeframe_to_bar_suffix`,
    so passing an unsupported timeframe raises before any runner is
    spun up.
    """
    suffix = timeframe_to_bar_suffix(timeframe)

    def _maybe_overlay(name: str, params: dict[str, object]) -> dict[str, object]:
        if scale_out and name in _SCALE_OUT_STRATEGIES:
            return {**params, **_SCALE_OUT_OVERLAY}
        return params

    return (
        StrategySpec(
            name="supertrend",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params=_maybe_overlay(
                "supertrend",
                {
                    "period": 10,
                    "multiplier": 3.0,
                    "atr_period": 14,
                    "sl_atr_mult": "1.5",
                    "tp_atr_mult": "3.0",
                    "risk_percent": "0.5",
                    "pip_size": "0.01",
                    "pip_value_per_lot": "1.0",
                },
            ),
        ),
        StrategySpec(
            name="donchian_breakout",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params=_maybe_overlay(
                "donchian_breakout",
                {
                    "channel_period": 20,
                    "atr_period": 14,
                    "sl_atr_mult": "2.0",
                    "tp_atr_mult": "4.0",
                    "risk_percent": "0.5",
                    "pip_size": "0.01",
                    "pip_value_per_lot": "1.0",
                },
            ),
        ),
        StrategySpec(
            name="ma_crossover",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params=_maybe_overlay(
                "ma_crossover",
                {
                    "fast_period": 20,
                    "slow_period": 50,
                    "atr_period": 14,
                    "sl_atr_mult": "1.5",
                    "tp_atr_mult": "3.0",
                    "risk_percent": "0.5",
                    "pip_size": "0.01",
                    "pip_value_per_lot": "1.0",
                },
            ),
        ),
        StrategySpec(
            name="bollinger_mean_reversion",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params={
                "period": 20,
                "num_std": 2.0,
                "atr_period": 14,
                "sl_atr_mult": "1.0",
                "tp_atr_mult": "2.0",
                "risk_percent": "0.5",
                "pip_size": "0.01",
                "pip_value_per_lot": "1.0",
            },
        ),
        StrategySpec(
            name="rsi_mean_reversion",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params={
                "rsi_period": 14,
                "oversold": 0.3,
                "overbought": 0.7,
                "exit_neutral": 0.5,
                "atr_period": 14,
                "sl_atr_mult": "1.0",
                "tp_atr_mult": "2.0",
                "risk_percent": "0.5",
                "pip_size": "0.01",
                "pip_value_per_lot": "1.0",
            },
        ),
        StrategySpec(
            name="orb",
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params={
                "session_open_hour": 8,
                "session_open_minute": 0,
                "session_close_hour": 16,
                "session_close_minute": 30,
                "session_tz": "Europe/London",
                "opening_range_minutes": 30,
                "atr_period": 14,
                "sl_atr_mult": "1.0",
                "tp_atr_mult": "2.0",
                "risk_percent": "0.5",
                "pip_size": "0.01",
                "pip_value_per_lot": "1.0",
            },
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/xauusd-validation-v1.json"),
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
        help="Bar timeframe (MT-style code: M5, M15, etc.) — must match a manifest entry (default: %(default)s)",
    )
    parser.add_argument(
        "--scale-out",
        action="store_true",
        help="Apply Epic 13 Phase 1 scale-out overlay on eligible trend-followers (supertrend + donchian_breakout)",
    )
    parser.add_argument(
        "--ftmo-preset",
        type=Path,
        default=Path("src/backtesting/presets/ftmo.yaml"),
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
        default="epic12a-baseline",
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
    print(f"loaded manifest: {manifest.spec_name} v{manifest.dataset_version}  symbol={manifest.symbol}")
    for e in manifest.entries:
        print(f"  {e.window_name} {e.timeframe} rows={e.row_count} fp={e.fingerprint.sha256()}")

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

    strategies = _build_strategies(args.timeframe, scale_out=args.scale_out)
    suffix = "-scaleout" if args.scale_out else ""
    run_label = (
        f"epic-12a-baseline-{manifest.symbol.lower()}-{args.timeframe.lower()}{suffix}"
    )
    config = BaselineConfig(
        run_label=run_label,
        manifest=manifest,
        window_name=args.window_name,
        venue=venue,
        strategies=strategies,
        prop_firm=prop_firm,
    )

    overlay_tag = " [scale-out overlay applied to supertrend + donchian_breakout]" if args.scale_out else ""
    print(
        f"\nrunning {len(strategies)} strategies on {manifest.symbol} {args.window_name} "
        f"{args.timeframe}{overlay_tag}…"
    )
    results = run_baseline(config)
    print(f"  done. {len(results)} BacktestResults captured.\n")

    # Short console summary before we render markdown.
    print(f"{'strategy':<28} {'trades':>6} {'win%':>6} {'EV':>7} {'PF':>6} {'sharpe':>7} {'maxDD%':>7}")
    for r in results:
        m = r.metrics
        if m is None:
            print(f"{r.strategy_name:<28} {'-':>6} {'-':>6} {'-':>7} {'-':>6} {'-':>7} {'-':>7}  (no metrics)")
            continue
        print(
            f"{r.strategy_name:<28} "
            f"{m.trades.total_trades:>6} "
            f"{m.trades.win_rate * 100:>5.1f}% "
            f"{m.pnl.expectancy:>+7.3f} "
            f"{m.pnl.profit_factor:>6.3f} "
            f"{m.risk.sharpe_ratio:>+7.3f} "
            f"{m.drawdown.max_overall_dd_pct:>7.3f}"
        )

    filter_ = BaselineFilter()
    table_md = render_comparison_report(results, baseline_filter=filter_)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table_md + "\n")
    print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
