# Epic 12 Phase 12.A — M15 baseline retry

**Story:** 12.7a follow-up — M15 retry of the in-sample baseline (recoverable direction §3.1 in `epic-12-baseline-comparison.md`)
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`
**Runner:** `services/trading-engine/scripts/run_epic12a_baseline.py --timeframe M15`

---

## 1. Summary

Re-ran the same six production strategies on the **M15 in_sample window**
(47,383 bars, same 2024-01-01 → 2026-01-01 calendar period as the M5 run)
to test whether slower bars lift Sharpe above the Decision §2 filter floor
of 0.8. **No strategy clears the filter on M15 either**, but the picture
changes in interesting ways:

- **`ma_crossover` is the standout** — Sharpe **0.137** (best across all 12 runs
  M5 + M15), EV **+0.161**, profit factor **1.246**, max DD 0.03%. Still
  fails Sharpe ≥ 0.8 but the **gap is now the smallest** of any strategy.
- **`orb` flips negative** — on M5 it was profitable (EV +0.197); on M15
  EV drops to −0.080. ORB's signal is structurally tied to the early-
  session bars; M15 leaves only 2 opening-range bars (30 min ÷ 15) instead
  of 6 (30 ÷ 5), degrading the signal.
- **Mean-reversion strategies still lose** but **less than on M5**
  (RSI EV −0.18 vs −0.32; Bollinger EV −0.20 vs −0.34).
- **`supertrend` loses less on M15** (EV −0.075 vs −0.282 on M5) —
  consistent with the Epic 13 quant review hypothesis that Supertrend's
  whipsaw cost dominates on fast bars.

### M5 vs M15 side-by-side

| Strategy | M5 EV | M5 Sharpe | M15 EV | M15 Sharpe | Δ Sharpe | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ma_crossover` | +0.018 | +0.03 | **+0.161** | **+0.137** | +0.11 | **best signal**; still FAIL 0.8 |
| `donchian_breakout` | +0.167 | +0.07 | +0.075 | +0.03 | −0.04 | M5 better; both FAIL |
| `orb` | +0.197 | +0.03 | −0.080 | −0.02 | −0.05 | M15 broke it; revert to M5 |
| `supertrend` | −0.282 | −0.11 | −0.075 | −0.03 | +0.08 | M15 less bad; still losing |
| `bollinger_mean_reversion` | −0.344 | −0.27 | −0.199 | −0.15 | +0.12 | less bad; still losing |
| `rsi_mean_reversion` | −0.317 | −0.25 | −0.182 | −0.14 | +0.11 | less bad; still losing |

Two strategies improved meaningfully (`ma_crossover`, `supertrend`); two
worsened slightly (`donchian`, `orb`); two improved but stayed net-
negative (`bollinger`, `rsi`).

---

## 2. Interpretation

### 2.1 Why `ma_crossover` benefits most from M15

EMA(20)/EMA(50) on M15 ≈ 5h / 12.5h smoothing — a meaningful intraday
trend filter. On M5 the same periods translate to 1h40m / 4h10m, which
is short enough that whipsaws dominate. The ~3pp win-rate change isn't
dramatic (30.2% vs 27.7%), but **profit factor jumps 1.05 → 1.25** and
Sharpe rises 4.5×. This is the textbook signature of a trend filter
that's now operating on its natural timescale.

### 2.2 Why `orb` regresses on M15

ORB defines "opening range" as the first `opening_range_minutes` of the
session — 30 min by default. On M5 that's six bars (enough to form a
shape with high + low + middle); on M15 it's **two bars**, often a
single candle pair with one shape. The breakout direction becomes
noise. Either:
- Lower `opening_range_minutes` to 15 on M15 (= 1 bar — still degenerate)
- Keep ORB on M5
- Or use a finer timeframe like M1 (would give 30 bars in the opening
  range, but M1 data is more expensive to fetch)

The cleanest read: **ORB belongs on M5 for this symbol**.

### 2.3 Mean-reversion: less bad, not good

Bollinger MR and RSI MR both improve on M15 (less negative EV, less
negative Sharpe). The hypothesis: M15 amplitude is higher than M5, so
2-sigma Bollinger bands and RSI 30/70 thresholds become more
meaningful events. But neither is profitable yet; both need a regime
filter or trend-confirmation gate before they could pass the 0.8
threshold.

---

## 3. Phase 12.B / Story 12.7b go/no-go

**Still gated.** No strategy passes Sharpe ≥ 0.8 on either M5 or M15
defaults. Per Decision §2:

> Strategies pass filter sang Phase 12.B; fail → ghi lại nhưng không
> tune (overfitting risk).

### Best candidates for the next recoverable direction

The three positive-EV combinations across M5 + M15 are now identified:

1. `ma_crossover` M15 — EV +0.161, Sharpe **0.137**, PF 1.246
2. `orb` M5 — EV +0.197, Sharpe 0.03, PF 1.06
3. `donchian_breakout` M5 — EV +0.167, Sharpe 0.07, PF 1.05

Of these, **`ma_crossover` M15** is the only one with Sharpe meaningfully
above zero and a profit factor above 1.20. It is the natural next
target for either:

- **(2) Re-baseline with `scale_out_enabled=true`** (Epic 13 tactic
  default-on per Story 13.8 firm config). Story 13.9 showed +52 % EV
  uplift for `supertrend` on M5; the same tactic is wired for
  `ma_crossover` and may push Sharpe over 0.8 on M15.
- **(3) Relax Sharpe floor to 0.5 for exploration mode** so
  `ma_crossover` M15 enters parameter sweep (Story 12.7b), with the
  original 0.8 filter applied to sweep outputs before live
  qualification.

(1) M15 retry — this report — is exhausted. The data is in.

### Recommendation

**Try (2) next.** Re-baseline `ma_crossover` + `donchian_breakout` on
both M5 and M15 with `scale_out_enabled=true`, `trailing_enabled=true`.
That isolates the Epic 13 tactic effect on the two strongest
trend-following candidates. If Sharpe lifts past 0.8, we have a sweep
candidate. If not, fall back to (3).

---

## 4. Methodology

Identical to the M5 baseline run (`epic-12-baseline-comparison.md` §4)
except for `--timeframe M15`. Strategy parameters are unchanged — the
same defaults run on M15 bars so the comparison is **pure timeframe
effect**, not param-and-timeframe co-variation.

| Field | Value |
| --- | --- |
| Symbol | XAUUSD |
| Timeframe | M15 |
| Window | 2024-01-01 → 2026-01-01 (in_sample, 2 y) |
| Bar count | 47,383 |
| Manifest fingerprint | `b0ad700694500da8` |
| Run label | `epic-12a-baseline-xauusd-m15` |
| Wall-clock | ~1 minute (M15 runs faster than M5 due to fewer bars) |

```bash
cd services/trading-engine
uv run python scripts/run_epic12a_baseline.py \
  --timeframe M15 \
  --out ../../docs/sprint-artifacts/epic-12-baseline-comparison-m15.md
```

### Caveats specific to this retry

1. **Same param defaults across timeframes.** A real M15-tuned config
   for some strategies (e.g. ORB `opening_range_minutes`, RSI
   `rsi_period`) would likely lift their numbers. We intentionally did
   not co-vary params with timeframe so the comparison isolates the
   timeframe effect.
2. **No scale-out tactic applied.** `scale_out_enabled=False` (Epic 13
   default-OFF) on all six. Direction (2) in §3 explicitly re-runs
   with tactic-on as the next experiment.

---

## 5. Machine-readable comparison (rendered by Story 12.3 writer)

# In-sample comparison report

- Run label: `epic-12a-baseline-xauusd-m15`
- Dataset: `xauusd-validation` v`1.0.0` (window `in_sample`)
- Dataset fingerprint: `b0ad700694500da8`
- Filter: sharpe ≥ 0.80, max DD ≤ 8.00%, trades ≥ 200, daily-loss breaches ≤ 0, max-DD breach blocks

| Strategy | Sharpe | Sortino | Max DD | Profit Factor | Win Rate | Trades | Breaches | Verdict |
|---|---|---|---|---|---|---|---|---|
| supertrend | -0.03 | -0.05 | 0.26% | 0.98 | 33.7% | 1198 | 0 | FAIL — sharpe -0.03 < 0.80 |
| donchian_breakout | 0.03 | 0.06 | 0.33% | 1.02 | 34.4% | 1685 | 0 | FAIL — sharpe 0.03 < 0.80 |
| ma_crossover | 0.14 | 0.34 | 0.03% | 1.25 | 30.2% | 884 | 0 | FAIL — sharpe 0.14 < 0.80 |
| bollinger_mean_reversion | -0.15 | -0.25 | 1.11% | 0.94 | 36.7% | 4911 | 0 | FAIL — sharpe -0.15 < 0.80 |
| rsi_mean_reversion | -0.14 | -0.21 | 0.62% | 0.93 | 48.6% | 3247 | 0 | FAIL — sharpe -0.14 < 0.80 |
| orb | -0.02 | -0.03 | 0.19% | 0.98 | 34.0% | 517 | 0 | FAIL — sharpe -0.02 < 0.80 |

## Summary
- Pass: _none_ — no strategies eligible for Phase 12.B.
- Fail (6): `supertrend`, `donchian_breakout`, `ma_crossover`, `bollinger_mean_reversion`, `rsi_mean_reversion`, `orb` — do not tune (overfitting trap, see Decision §2).

---

## 6. References

- `docs/sprint-artifacts/epic-12-baseline-comparison.md` — M5 baseline (this is the companion report)
- `docs/sprint-artifacts/validation-report-epic13.md` — Supertrend scale-out A/B on M5 (+52% EV)
- `docs/research/strategy-tactics-quant-review.md` §2.6 — Supertrend whipsaw-on-fast-bars analysis
- `services/trading-engine/scripts/run_epic12a_baseline.py` — runner (supports `--timeframe`)
