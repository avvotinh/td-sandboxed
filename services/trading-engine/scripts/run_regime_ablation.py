"""Track 4.3 — regime-gate ablation matrix (redesign plan 2026-07-02).

Runs the Track 5.1 winner cells (``entry-filter-ab-2y-verdict.md`` §3)
with the Epic 15 ``RegimeActor`` pipeline OFF (anchor) and ON, deciding
by the numbers whether the regime gate earns default-ON:

* ``mean_reversion`` — the headline question. Its allow-list is
  ``{RANGING}``; every baseline so far ran ungated, so its numbers were
  a floor. Runs both ``[none]`` and ``[recross]`` (Track 5.1's
  recommendation) so gate-vs-entry-fix composition is visible.
* ``donchian_breakout`` — best cells of the redesign (M5 ``[cross]``,
  M15 scale-out+BE-offset). Allow-list ``{TRENDING_UP, TRENDING_DOWN}``.
* ``supertrend`` — archive candidate. M5 runs its trail-only anchor and
  its least-bad ``[adx+session]`` shape; the gate is its last chance.

Regime calibration comes from ``configs/firms/ftmo.yaml``
(``regime_classifier:`` block, XAUUSD M5 thresholds) with ``enabled``
flipped ON in-memory — the shipped YAML stays default-OFF. NOTE: the
M15 arm reuses the M5-calibrated thresholds (the block's ``timeframe``
field is informational); indicator lookbacks are bar-counted, so their
wall-clock horizon stretches 3x on M15 — read those cells with that
caveat.

Gate mechanics (story 15.7): entries are suppressed unless the
confirmed regime is in the strategy's allow-list; HIGH_VOLATILITY and
UNKNOWN suppress everyone; exits are never gated. During extractor
warmup (~200 bars feature window) no snapshot is confirmed, so the ON
arm gives up a handful of early entries — the conservative warmup
delta pinned by story 15.9's ``orders_on <= orders_off``.

The OFF anchors must reproduce the corresponding rows of
``entry-filter-ab-2y-m5/m15.md`` exactly — that pin validates the
harness before the ON deltas are read.

Usage::

    uv run python scripts/run_regime_ablation.py \\
      --manifest manifests/xauusd-2y.json \\
      --timeframe M5 \\
      --out ../../docs/sprint-artifacts/regime-ablation-2y-m5.md
"""

from __future__ import annotations

import argparse
import dataclasses
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
from src.lab.result import BacktestResult
from src.config.firm_profile import RegimeConfig
from src.config.firm_registry import FirmRegistry


ParamValue = int | float | str | bool | None
Params = dict[str, ParamValue]

_REPO_ROOT = Path(__file__).resolve().parents[3]

# --- Base strategy params (Phase 12.A defaults, = entry-filter script) --

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

# --- Entry-filter overlays (Track 5.1 winners only) ---------------------

_ADX_GATE: Params = {"adx_gate_min": "25", "adx_gate_period": 14}
_SESSION_TREND: Params = {
    "session_filter_tz": "America/New_York",
    "session_filter_open_hour": 7,
    "session_filter_open_minute": 0,
    "session_filter_close_hour": 16,
    "session_filter_close_minute": 0,
    "session_filter_exit_policy": "flatten",
}
_CROSS_ONLY: Params = {"entry_on_cross_only": True}
_RECROSS: Params = {"entry_mode": "recross"}


@dataclasses.dataclass(frozen=True, slots=True)
class Cell:
    """One strategy configuration to ablate (gate OFF vs ON)."""

    strategy: str
    variant: str
    tactic: Params
    filters: Params

    @property
    def label(self) -> str:
        return f"{self.strategy}[{self.variant}]"

    def params(self) -> Params:
        return {**_BASE_PARAMS[self.strategy], **self.tactic, **self.filters}


# timeframe → cells. Anchors reproduce entry-filter-ab rows: supertrend
# M5 rides trail-only, M15 scale-out+BE-offset; donchian M5 bare(+cross),
# M15 scale-out+BE-offset; mean_reversion bare.
_CELLS: dict[str, tuple[Cell, ...]] = {
    "M5": (
        Cell("supertrend", "none", _TRAILONLY, {}),
        Cell("supertrend", "adx+session", _TRAILONLY, {**_ADX_GATE, **_SESSION_TREND}),
        Cell("donchian_breakout", "cross", {}, _CROSS_ONLY),
        Cell("mean_reversion", "none", {}, {}),
        Cell("mean_reversion", "recross", {}, _RECROSS),
    ),
    "M15": (
        Cell("supertrend", "none", _SCALEOUT_BEOFFSET, {}),
        Cell("donchian_breakout", "none", _SCALEOUT_BEOFFSET, {}),
        Cell("mean_reversion", "none", {}, {}),
        Cell("mean_reversion", "recross", {}, _RECROSS),
    ),
}


def _load_regime_config(firms_dir: Path, symbol: str) -> RegimeConfig:
    """Load the ftmo regime block and flip it ON in-memory.

    Raises ``ValueError`` (caught in ``main`` → stderr + exit 1) when the
    block is missing or has no calibration for ``symbol`` — classifying
    against another instrument's thresholds would silently invalidate
    the whole ablation.
    """
    registry = FirmRegistry(firms_dir)
    registry.load()
    regime = registry.get("ftmo").regime_classifier
    if regime is None:
        raise ValueError(
            f"ftmo.yaml in {firms_dir} has no regime_classifier block"
        )
    if symbol not in regime.instruments:
        raise ValueError(
            f"regime_classifier has no calibration for {symbol!r} "
            f"(available: {sorted(regime.instruments)})"
        )
    return dataclasses.replace(regime, enabled=True)


def _build_strategies(timeframe: str, *, arm: str) -> tuple[StrategySpec, ...]:
    suffix = timeframe_to_bar_suffix(timeframe)
    return tuple(
        StrategySpec(
            name=cell.strategy,
            timeframe=timeframe,
            bar_type_suffix=suffix,
            params=cell.params(),
            label=f"{cell.label}|gate={arm}",
        )
        for cell in _CELLS[timeframe]
    )


def _print_rows(
    specs: tuple[StrategySpec, ...], results: list[BacktestResult]
) -> None:
    for spec, r in zip(specs, results, strict=True):
        m = r.metrics
        if m is None:
            print(f"{spec.display_label:<44} (no metrics)")
            continue
        print(
            f"{spec.display_label:<44} "
            f"{m.trades.total_trades:>6} "
            f"{m.trades.win_rate * 100:>5.1f}% "
            f"{m.pnl.expectancy:>+8.3f} "
            f"{m.pnl.profit_factor:>6.3f} "
            f"{m.risk.sharpe_ratio:>+7.3f} "
            f"{m.drawdown.max_overall_dd_pct:>7.3f}"
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
        help="DatasetManifest window to backtest (default: %(default)s)",
    )
    parser.add_argument(
        "--timeframe",
        default="M5",
        choices=sorted(_CELLS),
        help="Bar timeframe — must have a cell mapping",
    )
    parser.add_argument(
        "--firms-dir",
        type=Path,
        default=_REPO_ROOT / "configs" / "firms",
        help="Firm-profile YAML directory (default: %(default)s)",
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
        default="track43-regime-ablation",
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
        regime_on = _load_regime_config(args.firms_dir, manifest.symbol)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    instr = regime_on.get_instrument(manifest.symbol)
    print(
        f"regime calibration: {manifest.symbol} (calibrated {instr.timeframe}) "
        f"confirmation={regime_on.confirmation_bars} "
        f"warmup={regime_on.warmup_bars} adx>={instr.thresholds.adx_trend_min}"
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

    run_label = (
        f"track43-regime-ablation-{manifest.symbol.lower()}-{args.timeframe.lower()}"
    )
    arms: list[tuple[str, RegimeConfig | None]] = [
        ("off", None),
        ("on", regime_on),
    ]

    header = (
        f"{'cell|arm':<44} {'trades':>6} {'win%':>6} {'EV':>8} "
        f"{'PF':>6} {'sharpe':>7} {'maxDD%':>7}"
    )
    all_specs: list[StrategySpec] = []
    all_results: list[BacktestResult] = []
    for arm, regime_cfg in arms:
        specs = _build_strategies(args.timeframe, arm=arm)
        # Same run_label across both arms — render_comparison_report
        # refuses diverging labels; the arm lives in each spec's label.
        config = BaselineConfig(
            run_label=run_label,
            manifest=manifest,
            window_name=args.window_name,
            venue=venue,
            strategies=specs,
            prop_firm=prop_firm,
            regime_config=regime_cfg,
        )
        print(
            f"\nrunning {len(specs)} cells with regime gate {arm.upper()} on "
            f"{manifest.symbol} {args.window_name} {args.timeframe}…"
        )
        results = run_baseline(config)
        print(header)
        _print_rows(specs, results)
        all_specs.extend(specs)
        all_results.extend(results)

    table_md = render_comparison_report(
        all_results, baseline_filter=BaselineFilter()
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(table_md + "\n", encoding="utf-8")
    print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
