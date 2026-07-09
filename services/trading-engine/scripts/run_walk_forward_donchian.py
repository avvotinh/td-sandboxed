"""Walk-forward validation of donchian M5 ``entry_on_cross_only`` (plan §5.1).

The Track 5.1 verdict promoted-with-conditions ``donchian[cross]`` M5
(+0.087 Sharpe / 25.7% DD over the 2y in-sample) and required a
walk-forward pass before the config becomes a production default. The
Track 4.3 OOS addendum sharpened the question: the whole
``oos_reserve`` window (2026-01→05) was hostile to every cell
(donchian[cross] −0.109), so is the in-sample edge *stable across
2024–25* (regime-local OOS miss) or *concentrated in a few lucky
months* (spurious)?

Method — story 12.5 fixed-params harness (``walk_forward_harness``):
rolling folds (train 6m / test 1m / step 1m ⇒ ~18 one-month test
slices across the 2y window), strategy params FIXED (no per-fold
tuning — Decision §2 discipline), per-fold OOS metrics aggregated and
checked against Decision §4 acceptance (mean OOS Sharpe ≥ 0.7 × IS,
CV ≤ 0.5). The train slices are ignored by construction — nothing is
fitted. Runs BOTH ``donchian[cross]`` and the level-triggered
``donchian[none]`` anchor so the promotion question is comparative:
does ``cross`` beat ``none`` fold-by-fold, or only in aggregate?

Each fold starts its indicators cold (channel 20 + ATR 14 bars ≈ 2h of
M5 — negligible against a one-month slice, and identical for both
variants). IS anchor rows are recomputed in-process so the report is
self-contained and re-checkable against ``entry-filter-ab-2y-verdict.md``.

Usage::

    uv run python scripts/run_walk_forward_donchian.py \\
      --manifest manifests/xauusd-2y.json \\
      --out ../../docs/sprint-artifacts/walk-forward-donchian-m5.md
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from decimal import Decimal
from pathlib import Path

from src.backtesting.dataset.baseline_harness import (
    BaselineConfig,
    StrategySpec,
    run_baseline,
    timeframe_to_bar_suffix,
)
from src.backtesting.dataset.manifest import DatasetManifest
from src.backtesting.dataset.walk_forward_harness import (
    FoldGenerationConfig,
    OOSAggregate,
    WalkForwardOutcome,
    aggregate_oos,
    render_walk_forward_section,
    run_walk_forward_fixed_params,
)
from src.backtesting.job_config import PropFirmSpec, VenueSpec


ParamValue = int | float | str | bool | None
Params = dict[str, ParamValue]

_TIMEFRAME = "M5"

# Phase 12.A donchian defaults (= entry-filter / regime-ablation scripts).
_DONCHIAN_BASE: Params = {
    "channel_period": 20,
    "atr_period": 14,
    "sl_atr_mult": "2.0",
    "tp_atr_mult": "4.0",
    "risk_percent": "0.5",
}

# variant label → filter overlay. ``none`` is the level-triggered anchor;
# ``cross`` is the promotion candidate (Track 5.1 §2.1).
_VARIANTS: dict[str, Params] = {
    "none": {},
    "cross": {"entry_on_cross_only": True},
}


def _spec(variant: str) -> StrategySpec:
    return StrategySpec(
        name="donchian_breakout",
        timeframe=_TIMEFRAME,
        bar_type_suffix=timeframe_to_bar_suffix(_TIMEFRAME),
        params={**_DONCHIAN_BASE, **_VARIANTS[variant]},
        label=f"donchian_breakout[{variant}]",
    )


def _sanitise_cell(value: str) -> str:
    """Escape pipes / strip newlines so arbitrary exception text cannot
    break the markdown table (mirrors the harness-private helper)."""
    return value.replace("|", "\\|").replace("\r", "").replace("\n", " ")


def _render_fold_table(outcome: WalkForwardOutcome) -> str:
    """Per-fold detail — the fold dispersion IS the finding."""
    lines = [
        f"### Per-fold detail — {outcome.label}",
        "",
        "| Fold | Test window | Trades | Win% | PF | Sharpe | Max DD |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for fc in outcome.fold_outcomes:
        window = (
            f"{fc.fold.test_start:%Y-%m-%d} → {fc.fold.test_end:%Y-%m-%d}"
        )
        if fc.oos_result is None or fc.oos_result.metrics is None:
            reason = _sanitise_cell(fc.error or "no metrics")
            lines.append(f"| {fc.fold_index} | {window} | — | — | — | — | {reason} |")
            continue
        m = fc.oos_result.metrics
        lines.append(
            f"| {fc.fold_index} | {window} "
            f"| {m.trades.total_trades} "
            f"| {m.trades.win_rate * 100:.1f}% "
            f"| {m.pnl.profit_factor:.3f} "
            f"| {m.risk.sharpe_ratio:+.3f} "
            f"| {m.drawdown.max_overall_dd_pct:.1f}% |"
        )
    lines.append("")
    return "\n".join(lines)


def _fmt(value: float, *, sign: bool = False) -> str:
    if not math.isfinite(value):
        return "—"
    return f"{value:+.3f}" if sign else f"{value:.3f}"


def _print_aggregate(agg: OOSAggregate, is_sharpe: float) -> None:
    print(
        f"  {agg.label:<28} folds={agg.n_folds_with_metrics}/{agg.n_folds} "
        f"mean OOS sharpe={_fmt(agg.mean_oos_sharpe, sign=True)} "
        f"std={_fmt(agg.std_oos_sharpe)} "
        f"IS={_fmt(is_sharpe, sign=True)} "
        f"mean DD={_fmt(agg.mean_oos_max_dd_pct)}% "
        f"trades={agg.total_oos_trades}"
    )


def _print_fold_errors(outcome: WalkForwardOutcome) -> None:
    """Surface fold crashes on stdout even when engine logs are disabled
    (the harness's own warning goes through ``logging``, which the
    default non-``--verbose`` mode silences)."""
    for fc in outcome.fold_outcomes:
        if fc.error is not None:
            print(
                f"  !! fold {fc.fold_index} "
                f"({fc.fold.test_start:%Y-%m-%d}) crashed: {fc.error}"
            )


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
        help="Manifest window to fold over (default: %(default)s)",
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
        default="track51-walk-forward-donchian",
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
    specs = tuple(_spec(v) for v in _VARIANTS)

    # --- IS anchors: full-window run, pins against entry-filter A/B ---
    print(
        f"\nIS anchors: full {args.window_name} {_TIMEFRAME} window "
        f"({len(specs)} variants)…"
    )
    try:
        is_results = run_baseline(
            BaselineConfig(
                run_label="walk-forward-donchian-is-anchor",
                manifest=manifest,
                window_name=args.window_name,
                venue=venue,
                strategies=specs,
                prop_firm=prop_firm,
            )
        )
    except KeyError as exc:  # unknown window/timeframe in the manifest
        print(exc, file=sys.stderr)
        return 1
    is_sharpe_by_label: dict[str, float] = {}
    for spec, result in zip(specs, is_results, strict=True):
        if result.metrics is None:
            print(f"IS anchor produced no metrics: {spec.display_label}",
                  file=sys.stderr)
            return 1
        is_sharpe_by_label[spec.display_label] = (
            result.metrics.risk.sharpe_ratio
        )
        print(
            f"  {spec.display_label:<28} "
            f"sharpe={result.metrics.risk.sharpe_ratio:+.3f} "
            f"DD={result.metrics.drawdown.max_overall_dd_pct:.1f}% "
            f"trades={result.metrics.trades.total_trades}"
        )

    # --- Walk-forward: fixed params, rolling 6m/1m/1m (Decision §4) ---
    fold_config = FoldGenerationConfig()  # 12.5 defaults
    print(
        f"\nwalk-forward: rolling train={fold_config.train_window.days}d "
        f"test={fold_config.test_window.days}d step={fold_config.step.days}d…"
    )
    rows: list[tuple[OOSAggregate, float]] = []
    fold_tables: list[str] = []
    for spec in specs:
        try:
            outcome = run_walk_forward_fixed_params(
                spec=spec,
                manifest=manifest,
                window_name=args.window_name,
                venue=venue,
                fold_config=fold_config,
                prop_firm=prop_firm,
            )
        except KeyError as exc:  # unknown window in the manifest
            print(exc, file=sys.stderr)
            return 1
        agg = aggregate_oos(outcome)
        is_sharpe = is_sharpe_by_label[spec.display_label]
        _print_aggregate(agg, is_sharpe)
        _print_fold_errors(outcome)
        rows.append((agg, is_sharpe))
        fold_tables.append(_render_fold_table(outcome))

    summary = render_walk_forward_section(rows)
    report = "\n".join(
        [
            f"# Walk-forward — donchian {_TIMEFRAME} cross vs none "
            f"({manifest.symbol})",
            "",
            (
                f"Data: {manifest.spec_name} v{manifest.dataset_version}, "
                f"window `{args.window_name}`. Fixed params (no per-fold "
                f"tuning); rolling train "
                f"{fold_config.train_window.days}d / test "
                f"{fold_config.test_window.days}d / step "
                f"{fold_config.step.days}d; train slices unused "
                f"(story 12.5 fixed-params mode)."
            ),
            "",
            summary,
            *fold_tables,
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n", encoding="utf-8")
    print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
