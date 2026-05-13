# Epic 12 Phase 12.A — final verdict

**Story:** 12.7a follow-up — definitive Sharpe verification across all
12+ strategy × timeframe × tactic experiments
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`

---

## 1. TL;DR

After four experiments (M5 baseline, M15 baseline, Supertrend M15
scale-out, Donchian M5/M15 scale-out), **no strategy clears the
Decision §2 acceptance filter (Sharpe ≥ 0.80) on XAUUSD M5 or M15
in_sample**. The best Sharpe observed is **0.137** for
`ma_crossover` M15 baseline — still **5.8× below** the filter floor.

**Phase 12.B (Story 12.7b parameter sweep) is permanently gated** on
this dataset configuration. Recoverable directions inside the
current scope are exhausted; the remaining options are larger
investments outside Epic 12's footprint.

---

## 2. Full Sharpe matrix

All numbers are from `services/trading-engine/scripts/run_epic12a_baseline.py`
with the FTMO prop-firm actor wired (so `equity_curve` is populated
and Sharpe is real).

| Strategy | M5 baseline | M5 scale-out | M15 baseline | M15 scale-out | Best |
| --- | ---: | ---: | ---: | ---: | ---: |
| `supertrend` | −0.106 | (M5 SO measured via 13.9, but no Sharpe) | −0.028 | **−0.008** | **−0.008** (M15 SO) |
| `donchian_breakout` | +0.065 | hurt (EV crashed) | +0.032 | **+0.061** | **+0.065** (M5 baseline) |
| `ma_crossover` | +0.030 | (mixin not wired) | **+0.137** | (mixin not wired) | **+0.137** (M15 baseline) |
| `bollinger_mean_reversion` | −0.265 | (gated, not adopted) | −0.153 | (gated) | −0.153 (M15) |
| `rsi_mean_reversion` | −0.246 | (gated) | −0.141 | (gated) | −0.141 (M15) |
| `orb` | +0.026 | (gated, not adopted) | −0.019 | (gated) | +0.026 (M5) |

### Best Sharpe across the experiment universe

```
ma_crossover M15 baseline:  Sharpe = +0.137   (5.8× below 0.8 floor)
donchian_breakout M5:       Sharpe = +0.065   (12.3× below 0.8)
donchian_breakout M15 SO:   Sharpe = +0.061   (13.1× below 0.8)
supertrend M15 SO:          Sharpe = -0.008   (negative)
```

---

## 3. Findings

### 3.1 The 0.8 floor is too tight for the signal universe

The Decision §2 filter was calibrated as a **live-deployment
qualifier**, not an exploration threshold. With Sharpe values
clustered between −0.30 and +0.14 across all 12 strategy × timeframe
combinations, **no defaults-only configuration on XAUUSD M5/M15 can
clear it**. This is signal-quality information, not a tuning issue.

Per Decision §2 contract:

> Strategies pass filter sang Phase 12.B; fail → ghi lại nhưng không
> tune (overfitting risk).

Honouring this rule, **Phase 12.B sweep is not run.**

### 3.2 Scale-out tactic effect is strategy + timeframe dependent (not uniformly +30 %)

The Epic 13 quant review §2.6 estimated +30 % EV uplift from
"50/50 + trail uncapped" for trend-followers in general. Reality:

| Combo | EV uplift |
| --- | ---: |
| Supertrend M5 | **+52 %** |
| Supertrend M15 | **+62 %** |
| Donchian M5 | **−91 %** (HURT) |
| Donchian M15 | **+91 %** |

The +30 % average masks bimodal behaviour. Whipsaw-prone signals
(Supertrend) benefit on both timeframes because BE protection >
tail-foregone cost. Clean-breakout signals (Donchian) are
timeframe-gated: on M5 the half-at-1R + half-at-BE pattern wrecks the
median winner; on M15 noise amortization restores the favourable
arithmetic.

### 3.3 ma_crossover is the strongest profitable signal but missing scale-out wiring

`ma_crossover` M15 baseline has Sharpe 0.137 — the highest of all
defaults runs — but cannot test with scale-out because Story 13.11 has
not landed. `MACrossoverConfig` inherits `BaseStrategyConfig` (not
`BracketStrategyConfig`); the mixin requires a config refactor +
sizing change from fixed `trade_size` to ATR-based `risk_percent`
before it can compose.

Whether scale-out would lift `ma_crossover` past 0.8 is unknown. The
Donchian M15 data suggests trend-followers benefit ~+91 % on M15 →
ma_crossover would be EV +0.31 estimate, but Sharpe transfer is not
linear from EV transfer.

### 3.4 FTMO compliance is not the binding constraint

All 12 strategy × timeframe runs produce 0 daily-loss breaches, max DD
under 5.1 %, and zero rule violations. The strategies are
**well-behaved on the compliance dimension** — they simply do not
generate enough risk-adjusted return to clear a 0.8 Sharpe gate. This
matters: if the team decides to deploy a lower-Sharpe strategy with
robust compliance for live data collection, the path is open.

---

## 4. Recommended next steps (ordered by cost)

### 4.1 Lowest cost (~hours)

**Lower the exploration filter to a research-mode threshold.**
`BaselineFilter(min_sharpe=0.1)` would admit `ma_crossover` M15
(Sharpe 0.137) — the only candidate to enter the 12.7b sweep. The
sweep would tune EMA periods, slow_period, etc., and any output
configuration would still face the original Sharpe ≥ 0.8 gate before
live qualification.

Risk: a 0.1 threshold is so loose that it admits noise as well as
signal. The original 0.8 protects against overfitting; relaxing it
costs information.

### 4.2 Medium cost (~1–2 days)

**Story 13.11 — wire scale-out into `MACrossoverStrategy`.** Requires
refactoring `MACrossoverConfig` to inherit `BracketStrategyConfig` and
switching from fixed `trade_size` to ATR-based `risk_percent`. Then
re-run the baseline with scale-out overlay on the third trend-follower.
If `ma_crossover` M15 scale-out clears Sharpe 0.8, 12.7b has a real
candidate.

### 4.3 Larger cost (~weeks)

**Improve entry signals beyond defaults.** Multi-indicator confirmation,
regime gating from Epic 11 (already wired but the strategies pass
through unconditionally), filter for sessions / volatility regimes,
combine breakout + trend confluence. Each of these is a multi-story
epic in its own right.

**Multi-symbol coverage.** XAUUSD has the highest intraday volatility
in the FTMO instrument universe — strategies that lose on M5 noise
might win on EURUSD M15 with cleaner trends. Requires materializing
new datasets via `tv-cli backtest-fetch` (the Epic 12.7.0 tooling can
do this — operator work).

---

## 5. Closing the Phase 12.A loop

The Phase 12.A acceptance flow:

```
Phase 12.A: in-sample baseline (6 strategies on XAUUSD M5+M15)
    ↓ apply Decision §2 filter
Phase 12.B: parameter sweep on top 2-3 passing strategies   <-- HALTED HERE
    ↓
Phase 12.C: walk-forward OOS verification
    ↓
Phase 12.D: roster memo + deployment go/no-go
```

We halted at the 12.A → 12.B gate because **zero strategies pass**.
Story 12.7a is complete. Story 12.7b stays in `backlog` until one of
the directions in §4 changes the input. Story 12.12 (strategy roster
memo) becomes the natural closing artifact for Epic 12 — it would
consolidate the four reports (M5 baseline, M15 baseline, Donchian
scale-out, this verdict) into a single go/no-go document if/when the
team decides what to do next.

---

## 6. References

- `docs/sprint-artifacts/epic-12-baseline-comparison.md` — M5 baseline
- `docs/sprint-artifacts/epic-12-baseline-comparison-m15.md` — M15 retry
- `docs/sprint-artifacts/epic-12-baseline-comparison-m15-scaleout.md` — M15 with scale-out overlay (this run)
- `docs/sprint-artifacts/epic13-supertrend-m15-followup.md` — Supertrend M15 A/B
- `docs/sprint-artifacts/epic13-donchian-scaleout-results.md` — Story 13.10
- `docs/sprint-artifacts/validation-report-epic13.md` — Story 13.9
- `docs/epic-12-context.md` §2 — original Decision §2 filter
- `docs/research/strategy-tactics-quant-review.md` §2.6 — +30 % EV hypothesis (contradicted by §3.2 above)
