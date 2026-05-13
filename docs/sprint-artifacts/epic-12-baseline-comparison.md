# Epic 12 Phase 12.A — In-sample Baseline Comparison

**Story:** 12.7a — Phase 12.A in-sample baseline (6 strategies, XAUUSD M5 in_sample)
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`
**Runner:** `services/trading-engine/scripts/run_epic12a_baseline.py`

---

## 1. Summary

All six production strategies were run with their default config parameters
against the canonical XAUUSD M5 in_sample window (2024-01-01 → 2026-01-01,
142,130 bars). **None of the six clears the Decision §2 acceptance filter**
(Sharpe ≥ 0.80, max DD ≤ 8%, ≥ 200 trades, 0 daily-loss breaches). Per the
filter contract, **Phase 12.B (parameter sweep / story 12.7b) is not run** —
tuning a strategy that fails in-sample on defaults is an overfitting trap
(epic-12-context.md §2).

The pass/fail outcome is not the only signal. Three strategies are **profitable
on default parameters** (positive EV) despite low Sharpe; three are **net-
negative**. The split tracks the intuitive divide between trend-following and
mean-reversion on a high-volatility intraday gold series.

### Per-strategy headline (XAUUSD M5 in_sample, 2 years)

| Strategy | Trades | Win % | EV ($/trade) | PF | Sharpe | Max DD % | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `donchian_breakout` | 4,445 | 35.4 % | **+0.167** | **1.050** | +0.07 | 0.49 | FAIL (Sharpe) |
| `orb` | 517 | 36.6 % | **+0.197** | **1.059** | +0.03 | 0.15 | FAIL (Sharpe) |
| `ma_crossover` | 2,776 | 27.7 % | **+0.018** | 1.051 | +0.03 | 0.08 | FAIL (Sharpe) |
| `supertrend` | 3,676 | 32.9 % | −0.282 | 0.915 | −0.11 | 1.06 | FAIL (Sharpe + EV) |
| `bollinger_mean_reversion` | 14,187 | 36.6 % | −0.344 | 0.895 | −0.27 | 5.01 | FAIL (Sharpe + EV) |
| `rsi_mean_reversion` | 9,816 | 48.1 % | −0.317 | 0.882 | −0.25 | 3.19 | FAIL (Sharpe + EV) |

Full machine-readable table at the bottom of this report (rendered by 12.3
`render_comparison_report`).

---

## 2. Interpretation

### 2.1 Profitable but low-Sharpe (3): `donchian_breakout`, `orb`, `ma_crossover`

All three have **positive EV and profit factor > 1.05** with **near-zero max
drawdown** (0.08 % – 0.49 %). They make money on average but the per-trade
return is small relative to its variance, so the Sharpe ratio remains close
to zero. This is the typical signature of a **weak but real edge that is
being diluted by:**

- **Conservative position sizing** — `risk_percent: 0.5 %` of $100k = $500
  per trade, but XAUUSD volatility means win/loss magnitudes are far below
  that risk cap. The strategy isn't risking what it can.
- **Wide range of trade outcomes** — high standard deviation of per-trade
  returns drags Sharpe down even when the mean is positive.

These are the strategies worth investigating further (more aggressive sizing,
trailing exits, regime filters). Story 13.9 already demonstrated this idea
for `supertrend` (the Epic 13 scale-out tactic lifts the EV by +52% even on
the net-losing baseline). The same tactic is now wired for `donchian_breakout`
and `ma_crossover` per Story 13.8 ftmo.yaml — but **defaults-OFF**, so this
baseline measures the pre-tactic signal.

### 2.2 Net-negative (3): `supertrend`, `bollinger_mean_reversion`, `rsi_mean_reversion`

All three lose money on defaults. The two mean-reversion strategies have
**negative Sharpe combined with high trade frequency** (9,816 and 14,187
trades over 2 years — every ~30–60 minutes). Such overtrading on a
trending-with-noise series like XAUUSD M5 is structurally fragile.

`supertrend` is more nuanced: 3,676 trades, EV −0.28, PF 0.915. The
13.9 A/B run on the same dataset showed the **scale-out variant lifts
expectancy to −0.13 (+52 %)**. So the Phase 1 tactic improves but does not
rescue the raw signal on M5. M15 may be the more natural timeframe (longer
warmup, less whipsaw).

### 2.3 What about the FTMO compliance gate?

All six strategies pass FTMO compliance (0 daily-loss breaches, max DD well
under the 8 % filter threshold and the 10 % FTMO hard cap) on the in-sample
window. Compliance is not the binding constraint — **signal quality is**.

---

## 3. Phase 12.B / Story 12.7b — go / no-go

Per the Decision §2 contract in `docs/epic-12-context.md`:

> Phase 12.A — In-sample validation pass: pin một dataset chuẩn → chạy 6
> strategies với YAML defaults → produce comparable metrics report → áp
> explicit filter. Strategies pass filter sang Phase 12.B; fail → ghi lại
> nhưng không tune (overfitting risk).

**No strategy passes. Phase 12.B is therefore skipped on this dataset
configuration.** The findings are recorded here and via the sprint-status
update for 12.7a. Story 12.7b (parameter sweep) is left in `backlog`
state until one of the recoverable directions below produces a Phase 12.A
pass.

### Recoverable directions (in cost order)

1. **Try M15 timeframe (cheap, 1 h work).** Re-run the baseline on the
   `in_sample` M15 window (47,383 bars). Slower bars typically lift Sharpe
   for trend-following because the warm-up cost is amortized over fewer
   trades and the average win:loss widens. If `supertrend` or `donchian`
   produces Sharpe > 0.8 on M15, sweep proceeds on M15.
2. **Re-run with Epic 13 scale-out enabled (default in firm config).** The
   13.9 A/B showed scale-out improves `supertrend` EV by 52 % and p95 winner
   R by 132 % on M5. Re-running this baseline with `scale_out_enabled: true`
   for the three trend-followers (per Story 13.8 firm config) gives a fairer
   "in-production" measurement. The default-OFF safety pin from 13.8 keeps
   this opt-in.
3. **Relax the Sharpe filter to 0.5 for exploration** — Decision §2 picked
   0.8 for live-deployment qualification, not exploration. A 0.5 floor lets
   `donchian_breakout`, `orb`, `ma_crossover` enter sweep so we learn what
   parameter regions exist before committing to a hard 0.8 production
   threshold. The original filter would still gate any sweep output before
   live deployment.

Option (2) is the natural next step because it stays inside the current
campaign scope (defaults the team has actually picked for production) and
reuses the dataset already on disk. (1) and (3) are follow-ups if (2) does
not lift any strategy past 0.8.

---

## 4. Methodology

### 4.1 Dataset

| Field | Value |
| --- | --- |
| Symbol | XAUUSD |
| Timeframe | M5 |
| Window | 2024-01-01 → 2026-01-01 (in_sample, 2 y) |
| Bar count | 142,130 |
| Source | TradingView Premium (Epic 12.7.0 chunked fetch) |
| Manifest | `services/trading-engine/manifests/xauusd-validation-v1.json` |
| Fingerprint | `ca810a6170c12167` |
| Dataset version | 1.0.0 |

### 4.2 Strategy params

Defaults from each strategy's `Config.__post_init__` (no per-firm
overrides applied). Phase 1 tactics (`scale_out_enabled`,
`trailing_enabled`) default to **False** in `BracketStrategyConfig`, so
this baseline is the **pre-tactic** measurement. See
`scripts/run_epic12a_baseline.py` for the exact parameter dict per
strategy.

### 4.3 Venue + compliance

| Field | Value |
| --- | --- |
| Account | $100,000 starting balance, USD, SIM venue |
| OMS type | `HEDGING` (per Epic 13.9 — required for trade-by-trade Sharpe / DD) |
| FTMO preset | `src/backtesting/presets/ftmo.yaml` (5 % daily loss, 10 % max DD, profit target 10 %, min 4 trading days) |
| Session timezone | Europe/Berlin (FTMO CET) |
| Max DD method | `equity_peak` (the conservative default; Epic 9.6 follow-up will switch FTMO Challenge to `balance_based`) |

The prop-firm actor populates `equity_curve` so `Sharpe`, `Sortino`,
`max_dd_pct` are real numbers — distinct from the Epic 13.9 setup where
the actor was intentionally not wired (Epic 13 measured exit-tactic
delta, not compliance).

### 4.4 Harness

`services/trading-engine/scripts/run_epic12a_baseline.py` orchestrates
the six runs via `run_baseline()` from Story 12.2 (`baseline_harness`),
then renders the comparison via `render_comparison_report()` from
Story 12.3.

```bash
cd services/trading-engine
uv run python scripts/run_epic12a_baseline.py \
  --manifest manifests/xauusd-validation-v1.json \
  --out      ../../docs/sprint-artifacts/epic-12-baseline-comparison.md
```

Total wall-clock time: ~3 minutes on a typical dev laptop (six Nautilus
init / dispose cycles dominate).

### 4.5 Caveats

1. **Single dataset, single timeframe.** This baseline covers only
   XAUUSD M5 in_sample. M15 in_sample (47k bars) is on the same
   manifest but not run here. Multi-symbol coverage requires additional
   datasets that the Epic 12.7.0 fetcher can produce but have not been
   materialized.
2. **Defaults only.** Strategy params are the in-repo defaults. The
   firm-config layer (`configs/firms/ftmo.yaml`) carries per-strategy
   overrides that are tested elsewhere; this run is intentionally a
   pre-tactic, pre-tuning baseline.
3. **In-sample only.** The `oos_reserve` window (4 months, 23k M5
   bars) is held out for the final go/no-go sanity check after any
   sweep on the passing strategies. Touching it here would compromise
   its out-of-sample status.
4. **R-multiple, percentile-of-winners, etc. are not in this report.**
   This baseline reports the schema-level metrics that the Decision §2
   filter consumes. Per-strategy R-multiple distributions are produced
   by Story 13.9's `backtest ab` flow when comparing baseline vs
   tactic variant.

---

## 5. Machine-readable comparison (rendered by Story 12.3 writer)

# In-sample comparison report

- Run label: `epic-12a-baseline-xauusd-m5`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `ca810a6170c12167`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend | -0.11 | -0.18 | 1.06% | 0.92 | 32.9% | 3676 | 0 | FAIL — sharpe -0.11 < 0.80 |
| donchian_breakout | 0.07 | 0.11 | 0.49% | 1.05 | 35.4% | 4445 | 0 | FAIL — sharpe 0.07 < 0.80 |
| ma_crossover | 0.03 | 0.07 | 0.08% | 1.05 | 27.7% | 2776 | 0 | FAIL — sharpe 0.03 < 0.80 |
| bollinger_mean_reversion | -0.27 | -0.43 | 5.01% | 0.89 | 36.6% | 14187 | 0 | FAIL — sharpe -0.27 < 0.80 |
| rsi_mean_reversion | -0.25 | -0.36 | 3.19% | 0.88 | 48.1% | 9816 | 0 | FAIL — sharpe -0.25 < 0.80 |
| orb | 0.03 | 0.05 | 0.15% | 1.06 | 36.6% | 517 | 0 | FAIL — sharpe 0.03 < 0.80 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (6): `supertrend`, `donchian_breakout`, `ma_crossover`, `bollinger_mean_reversion`, `rsi_mean_reversion`, `orb` — do not tune (overfitting trap, see Decision §2).

---

## 6. References

- `docs/epic-12-context.md` — Phase 12.A / 12.B / 12.C plan, Decision §2 filter
- `services/trading-engine/src/backtesting/dataset/baseline_harness.py` — Story 12.2
- `services/trading-engine/src/backtesting/dataset/comparison_report.py` — Story 12.3
- `services/trading-engine/scripts/run_epic12a_baseline.py` — this Phase 12.A runner
- `docs/sprint-artifacts/validation-report-epic13.md` — Epic 13 scale-out validation (the +52 % EV uplift on `supertrend` referenced above)
