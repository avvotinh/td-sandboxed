# Epic 13 Phase 1 — Backtest A/B Validation Report

**Story:** 13.9 — Backtest A/B validation report  
**Date:** 2026-05-12  
**Branch:** `epic-13-strategy-tactics`  
**Author:** Sandboxed dev team

---

## 1. Summary

The 50/50 scale-out + Supertrend ATR(7)×2.1 trail tactic from Epic 13 was
validated against the previous single-TP baseline on a 2-year XAUUSD M5
dataset. The variant **lifts per-trade expectancy by +52%** and
**extends 95th-percentile winner R-multiples by +132%** — meeting both
acceptance criteria in §8 of the implementation plan. Neither strategy
is profitable in absolute terms on this window, so the validation
quantifies an **exit-tactic improvement**, not strategy approval for
live trading.

### Headline numbers

| Metric                   | Baseline   | Variant    | Δ        | Δ%       |
| ------------------------ | ---------- | ---------- | -------- | -------- |
| Total trades             | 3,676      | 3,871      | +195     | +5.3%    |
| Win rate                 | 32.9%      | 29.2%      | −3.6pp   | −11.0%   |
| Expectancy ($/trade)     | −0.28      | −0.13      | +0.15    | **+52%** |
| Profit factor            | 0.916      | 0.956      | +0.041   | +4.5%    |
| Net return               | −1.04%     | −0.51%     | +0.52pp  | +50%     |
| 95p winner R             | 1.98R      | 4.59R      | +2.61    | **+132%**|
| Largest winner R         | 2.92R      | 4.62R      | +1.70    | +58%     |

### Acceptance criteria from `docs/research/strategy-tactics-implementation-plan.md` §8

- [x] **≥100 trades XAUUSD M5** — both variants produced 3,676–3,871 closed
      positions on 2 years of M5 bars.
- [x] **Scale-out variant ≥ baseline EV** — expectancy −0.13 > −0.28.
- [x] **Improvement on 95th-percentile winner** — 1.98R → 4.59R (+132%).

The +52% EV uplift compares favorably to the +30% prediction in the
quant review §2.6.

---

## 2. Methodology

### 2.1 Dataset

| Field             | Value                                          |
| ----------------- | ---------------------------------------------- |
| Symbol            | XAUUSD                                         |
| Timeframe         | M5 (5-minute bars)                             |
| Window            | 2024-01-01 → 2026-01-01 (in_sample, 2 years)   |
| Bar count         | 142,130                                        |
| Source            | TradingView Premium (Epic 12.7 chunked fetch)  |
| Manifest          | `services/trading-engine/manifests/xauusd-validation-v1.json` |
| Spec config       | `configs/datasets/xauusd-validation.yaml`      |
| Dataset version   | 1.0.0                                          |

The fallback to combined `in_sample + oos_reserve` was **not needed** —
2 years of M5 produced 3,676 closed positions for the baseline, well
above the ≥100 acceptance threshold. The `oos_reserve` window is
preserved untouched for a future Phase 2 sanity check.

### 2.2 Strategy + venue

Both jobs run `SupertrendStrategy` (Epic 13.5–13.6 integration) on the
same dataset, same venue (`SIM`), same starting balance ($100,000),
same OMS type (`HEDGING` — required for trade-by-trade reporting; see
§3.3 below). Only the strategy parameters differ.

#### Baseline (`configs/backtest/epic13-baseline.yaml`)

```yaml
strategy_params:
  period: 10
  multiplier: 3.0
  atr_period: 14
  sl_atr_mult: "1.5"
  tp_atr_mult: "3.0"      # hard 2R TP cap
  risk_percent: "0.5"
  pip_size: "0.01"
  pip_value_per_lot: "1.0"
  scale_out_enabled: false
  trailing_enabled: false
```

#### Variant (`configs/backtest/epic13-scaleout.yaml`)

```yaml
strategy_params:
  # ...identical entry / SL params...
  tp_atr_mult: "6.0"           # raised — TP is now anti-runaway cap, not exit target
  scale_out_enabled: true
  scale_out_r_trigger: "1.0"
  scale_out_close_fraction: "0.5"
  breakeven_at_r: "1.0"
  trailing_enabled: true
  trailing_method: supertrend
  trailing_atr_period: 7
  trailing_atr_multiplier: "2.1"
  safety_tp_atr_mult: "6.0"
```

### 2.3 Harness

A new CLI subcommand `trading-engine backtest ab` (Story 13.9) drives
the comparison. It loads two `BacktestJobConfig` YAMLs, runs each via
`run_backtest`, computes a winner-R distribution on top of the
existing `PropFirmMetricsSchema`, and emits side-by-side metric deltas
plus optional JSON.

```bash
uv run trading-engine backtest ab \
  --baseline configs/backtest/epic13-baseline.yaml \
  --variant  configs/backtest/epic13-scaleout.yaml \
  --out      docs/sprint-artifacts/epic13-ab-raw.json
```

Raw machine-readable output: [`epic13-ab-raw.json`](./epic13-ab-raw.json).

---

## 3. Results

### 3.1 Trade-level metrics

| Metric                    | Baseline   | Variant    | Δ          | Δ%        |
| ------------------------- | ---------- | ---------- | ---------- | --------- |
| Total trades              | 3,676      | 3,871      | +195       | +5.30%    |
| Winning trades            | 1,208      | 1,132      | −76        | −6.3%     |
| Losing trades             | 2,468      | 2,738      | +270       | +10.9%    |
| Win rate                  | 32.86%     | 29.24%     | −3.62pp    | −11.01%   |
| Avg win ($)               | 9.28       | 9.96       | +0.68      | +7.3%     |
| Avg loss ($)              | −4.96      | −4.31      | +0.65      | −13.2%    |
| Expectancy ($/trade)      | −0.28      | −0.13      | +0.148     | **−52.45%** (less negative) |
| Profit factor             | 0.916      | 0.956      | +0.041     | +4.47%    |
| Return on $100k           | −1.04%     | −0.51%     | +0.52pp    | −50.34%   |
| Final balance             | $98,964.53 | $99,485.77 | +$521.24   | —         |
| Max consecutive losses    | 17         | 18         | +1         | +5.88%    |

### 3.2 Winner R-multiple distribution

R-multiple convention: `R = pnl / |avg_loss|` per side (matching
`PropFirmMetricsSchema.avg_r_multiple` heuristic, §3.3). Distribution
covers only winning trades.

| Statistic           | Baseline | Variant | Δ     |
| ------------------- | -------- | ------- | ----- |
| Winner count        | 1,208    | 1,132   | −76   |
| Avg loss (abs $)    | 4.96     | 4.31    | −0.66 |
| **p50 winner R**    | 1.96     | 1.55    | −0.41 |
| **p75 winner R**    | 1.97     | 4.56    | +2.60 |
| **p90 winner R**    | 1.98     | 4.58    | +2.61 |
| **p95 winner R**    | 1.98     | **4.59**| **+2.61** |
| **p99 winner R**    | 1.99     | 4.61    | +2.62 |
| Largest winner R    | 2.92     | 4.62    | +1.70 |

#### Reading the distribution

The baseline distribution is **clustered tightly around 2R** because
the hard TP at `tp_atr_mult / sl_atr_mult = 3.0 / 1.5 = 2.0` caps every
winner at exactly +2R. Tiny variance above 2R comes from slippage on
TP fills. The largest winner (2.92R) is presumably a rare gap-through
of the TP level.

The variant distribution is **bimodal**:

- Lower mode at ~1.55R (median): scale-out partial close at +1R locks
  ~0.5R of profit, then the remainder hits BE-SL after Supertrend
  flips. Combined PnL ≈ 0.5R + 0R = 0.5R per full position, but each
  half is counted as a separate trade under HEDGING accounting —
  hence the 1.55R single-side median.
- Upper mode at ~4.6R (p75 onwards): scale-out at +1R combines with
  uncapped trail riding the Supertrend channel for the remaining 50%.
  This is the **tail capture** the quant review predicted.

The p95 jump from 1.98R to 4.59R (+132%) is the quantitative evidence
that uncapped trailing extracts trend-tail PnL the baseline leaves on
the table.

### 3.3 Caveats and known gaps

1. **R-multiple convention is a heuristic, not initial-risk R.**
   Per-trade R uses `pnl / |avg_loss|` because `TradeRecord` does not
   yet carry per-trade SL distance. The convention is symmetric across
   baseline + variant, so the **relative** comparison is sound; the
   absolute R values are recovery-per-avg-loss, not true initial-risk
   R. Capturing per-trade SL on TradeRecord is a Phase 2 follow-up.

2. **Drawdown / Sharpe / Sortino / Calmar all show 0.** These metrics
   depend on `equity_curve`, which is populated only when a
   `prop_firm` actor is wired into the backtest. The Epic 13 jobs run
   without prop-firm wiring (intentional — we are validating exit
   tactics, not FTMO compliance). Wiring a prop-firm preset would
   produce real DD/Sharpe but distort the exit-tactic comparison with
   compliance-triggered closures. Hooking equity-curve extraction
   off the backtest engine independently of prop-firm actor is
   another Phase 2 follow-up.

3. **HEDGING OMS for trade-by-trade reporting.** Nautilus's default
   `NETTING` mode collapses opposite-direction fills into one running
   position, so closed-position count drops to 1 for a strategy that
   flips ~3,700 times. The Epic 13 YAMLs explicitly set
   `oms_type: HEDGING` on the venue to preserve discrete entry-to-exit
   cycles. This produces the trade-level granularity required by the
   acceptance criteria but may yield slightly different aggregate PnL
   than a NETTING-only broker would report for the same fills (the
   per-position margin accounting differs).

4. **Both strategies lose money in absolute terms.** Net return −1.04%
   (baseline) vs −0.51% (variant) over 2 years on $100k. The
   validation is **relative** — does the Phase 1 scale-out + trail
   tactic improve the exit shape of an existing Supertrend signal —
   not whether the Supertrend signal itself is profitable on XAUUSD
   M5. Tuning the signal (parameter sweep) is Epic 12 scope; tactic
   validation is Epic 13 scope.

5. **Live deployment is not validated here.** Epic 13 ships
   backtest-only per §5.5 of the implementation plan. Live order
   modification requires Epic 14 (MT5 EA) to remove the
   `ZmqExecutionClient.modify_order` `NotImplementedError`. The
   scale-out tactics ship live only after Epic 14 + Epic 15.

### 3.4 Infrastructure gaps surfaced and fixed

Running this validation surfaced four pre-existing backtest
infrastructure gaps that the Story 13.9 commit fixes:

1. **Parquet schema adapter** — the `stitch_chunks_to_window.py`
   output (`index=False`, `time` int64 ms column) was not loadable by
   `run_backtest`. `runner_facade._normalise_parquet_index` now
   accepts both that shape and the `CachedBarLoader` DatetimeIndex
   shape transparently.

2. **YAML Decimal coercion** — strategy params declared as `Decimal`
   in `BracketStrategyConfig` would arrive as `str` after
   `yaml.safe_load`, breaking `__post_init__` validation.
   `runner_facade._coerce_strategy_params` walks the config class's
   type hints and lifts `str` / `int` / `float` into `Decimal` for
   any field annotated as such.

3. **XAUUSD instrument precision** — Nautilus's stock
   `TestInstrumentProvider.default_fx_ccy("XAUUSD")` returns a
   CurrencyPair with `size_precision=0`, which rejects fractional lot
   sizes. `_build_xauusd_instrument` now constructs a gold-specific
   CurrencyPair with `size_precision=2` (MT5 0.01-lot convention) and
   `price_precision=3`.

4. **Money → Decimal conversion** — `_extract_trades` blew up because
   `Decimal(str(Money(123.45, USD)))` can't parse `"123.45 USD"`. A
   new `_pos_pnl_decimal` helper uses `Money.as_decimal()` when
   available and falls back to `Decimal(str(...))` for scalar inputs.

Each fix is covered by a unit test in `test_runner_facade.py` so the
gap does not regress.

---

## 4. Reproducing the report

```bash
cd services/trading-engine

# 1. Confirm parquet is on disk + manifest fingerprints match.
ls -la /home/hopdev/Dev/Sandboxed/data/historical/XAUUSD/M5/in_sample.parquet
uv run python -c "
from src.backtesting.dataset.manifest import DatasetManifest
m = DatasetManifest.load_json('manifests/xauusd-validation-v1.json')
for e in m.entries:
    print(f'{e.timeframe} {e.window_name}: {e.row_count} rows fp={e.fingerprint.sha256()}')
"

# 2. Run the A/B.
uv run trading-engine backtest ab \
  --baseline configs/backtest/epic13-baseline.yaml \
  --variant  configs/backtest/epic13-scaleout.yaml \
  --out      ../../docs/sprint-artifacts/epic13-ab-raw.json
```

Expected wall-clock time: ~40s on a typical dev laptop (2 × ~17s
backtests + bar-load + Nautilus init/dispose overhead).

---

## 5. References

- `docs/research/strategy-tactics-implementation-plan.md` (§3.1, §6, §8)
- `docs/research/strategy-tactics-quant-review.md` (§2.6 — +30% EV prediction)
- `services/trading-engine/src/backtesting/ab_compare.py` — comparison + winner-R distribution
- `services/trading-engine/src/backtesting/cli.py` — `backtest ab` subcommand
- `services/trading-engine/configs/backtest/epic13-baseline.yaml`
- `services/trading-engine/configs/backtest/epic13-scaleout.yaml`
- `docs/sprint-artifacts/epic13-ab-raw.json` — machine-readable raw output
