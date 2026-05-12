# Story 13.10 — Donchian scale-out validation

**Story:** 13.10 — Wire `BracketScaleOutMixin` into `DonchianBreakoutStrategy`
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`
**Trigger:** Phase 12.A recoverable direction §3.2 — re-baseline trend-followers with `scale_out_enabled=true`

---

## 1. Summary

`DonchianBreakoutStrategy` now inherits `BracketScaleOutMixin` via the
same Story 13.5 wiring used for `SupertrendStrategy`. The mixin is
default-OFF, so the strategy keeps the legacy single-fill + hard-TP
behaviour unless a YAML / firm config explicitly turns scale-out on.

A/B comparison on XAUUSD M5 and M15 in_sample windows surfaces a
**strategy- and timeframe-dependent** tactic effect that the Epic 13
quant review (§2.6) did not anticipate:

| Combo | EV baseline | EV scale-out | Δ% | PF baseline → variant |
| --- | ---: | ---: | ---: | ---: |
| Supertrend M5 (13.9) | −0.282 | −0.134 | **+52%** | 0.92 → 0.96 |
| Supertrend M15 (follow-up) | −0.075 | −0.029 | **+62%** | 0.98 → 0.99 |
| **Donchian M5** | **+0.167** | **+0.015** | **−91%** | 1.05 → 1.005 |
| **Donchian M15** | **+0.075** | **+0.144** | **+91%** | 1.02 → 1.05 |

The headline: **Donchian M5 is hurt by scale-out** (EV crashes 91 %),
while **Donchian M15 benefits** (EV +91 %). Supertrend benefits on
both timeframes. The tactic is not strategy-agnostic.

### Donchian M15 scale-out is the strongest profitable config tested

| Field | Value |
| --- | ---: |
| Total trades | 1,681 |
| Win rate | 36.6 % |
| Expectancy ($/trade) | **+0.144** |
| Profit factor | **1.051** |
| Return on $100k | **+0.24 %** |
| p95 winner R | 3.37 (vs 1.97 baseline) |
| Largest winner R | 3.38 |
| FTMO breaches | (not measured in `backtest ab` — re-run via `run_baseline` for Sharpe) |

This is the **first** strategy × timeframe × tactic combination across
all experiments to land EV above +0.10 with PF > 1.05. Whether it can
clear the Decision §2 Sharpe ≥ 0.8 filter requires a re-run via
`run_baseline()` with the FTMO prop-firm actor wired (the `backtest ab`
CLI path does not populate `equity_curve` — same gap documented in
13.9 §3.3).

---

## 2. Interpretation

### 2.1 Why M5 Donchian is hurt

Donchian breakouts on M5 are **structurally different** from
Supertrend's flip signals:

- **Supertrend's edge is whipsaw absorption.** The default Supertrend
  signal flips often on M5 noise; baseline trades that flap around the
  band give up R repeatedly. Scale-out at +1R + BE move + uncapped
  trail locks in some profit before the flap-back, then rides the
  remainder when the trend extends. This is **net positive** on M5
  because the BE protection > the half-position-tail-foregone cost.

- **Donchian's edge is breakout follow-through.** A clean break of the
  prior 20-bar channel produces a directional move. Baseline rides the
  full position to 2R (`tp_atr_mult / sl_atr_mult = 4.0 / 2.0`) and
  takes the full $X profit. With scale-out enabled:
  - Half the position closes at 1R → locks 0.5R per full position.
  - The other half hits BE-SL on the post-1R retrace (M5 noise easily
    retraces SL distance) → locks 0R.
  - Net per "winning" full position: 0.5R, vs baseline 2R.

The M5 winner-R distribution confirms this:

| Stat | M5 baseline | M5 scale-out | Δ |
| --- | ---: | ---: | ---: |
| p50 winner R | 1.92 | 1.26 | **−0.66** (median crashes) |
| p95 winner R | 1.94 | 3.29 | +1.35 (some tail) |
| Avg loss abs | 5.14 | 4.52 | −0.62 (BE move shrinks losses) |
| Largest winner R | 2.21 | 3.39 | +1.19 |

Median winner drops from 1.92R to 1.26R: the **half-at-1R + half-at-BE
pattern dominates the distribution**. Tail capture (p95 up 1.35R) is
real but happens on too few trades to compensate. Profit factor
collapses from 1.05 to 1.005.

### 2.2 Why M15 Donchian benefits

Same structural argument, opposite direction. On M15:

- **Bars are 3× slower** — noise retracements that would whipsaw BE-SL
  on M5 stop short on M15.
- **Trends carry further per bar** — the half-position trail line has
  more room to ride before flipping.
- **Donchian channel period stays at 20 bars** = 5 hours window on
  M15 (vs 100 min on M5), giving the strategy a real trend filter.

M15 winner-R distribution:

| Stat | M15 baseline | M15 scale-out | Δ |
| --- | ---: | ---: | ---: |
| p50 winner R | 1.95 | 1.42 | −0.54 (still dilution, but smaller) |
| p95 winner R | 1.97 | 3.37 | +1.40 (tail capture) |
| Largest winner R | 1.98 | 3.38 | +1.40 |

Median dilution is smaller (−0.54R vs −0.66R on M5), tail capture is
larger (+1.40R vs +1.35R), and the resulting EV moves +91 % (vs −91 %
on M5).

### 2.3 What this means for Phase 12.B

The Epic 13 quant review §2.6 estimated +30 % EV uplift from
"50/50 + trail uncapped" for trend-followers in general. The actual
results on XAUUSD are bimodal:

- Supertrend (whipsaw-heavy signal): +52 % M5, +62 % M15 — **tactic helps**
- Donchian (clean-breakout signal): **−91 % M5**, +91 % M15 — **timeframe-gated**

**Implication for sweep selection (12.7b):** Donchian M15 scale-out is
the top candidate but its Sharpe needs verifying via `run_baseline()`
with the FTMO actor wired. Donchian M5 scale-out should NOT enter the
sweep; the baseline (no scale-out) is strictly better.

---

## 3. Implementation summary

### 3.1 Code

- `services/trading-engine/src/strategies/donchian_breakout.py`: Add
  `BracketScaleOutMixin` to MRO (prepended, matching Supertrend
  pattern). Add `_supertrend_trail` indicator (only when
  `trailing_enabled`). Override `on_event` to dispatch via
  `_dispatch_scale_out_event`; override `on_bar` to drive
  `_evaluate_scale_out_for_bar`. The four methods are intentionally
  copy-equivalent to the Story 13.5 wiring in `supertrend.py` —
  extraction into a shared helper queued for after Story 13.11 lands a
  third user (rule of three).

- `services/trading-engine/configs/backtest/`:
  - `epic13-donchian-baseline-m5.yaml`
  - `epic13-donchian-scaleout-m5.yaml`
  - `epic13-donchian-baseline-m15.yaml`
  - `epic13-donchian-scaleout-m15.yaml`

### 3.2 Tests

- `tests/unit/test_donchian_breakout_strategy.py`: +15 new unit tests
  mirroring the Story 13.5 Supertrend test classes
  (`TestScaleOutMRO`, `TestDispatchScaleOutEvent`,
  `TestEvaluateScaleOutForBar`, `TestTrailIndicatorWiring`).
- `tests/integration/test_bracket_strategies_smoke.py`: Add
  `test_donchian_scale_out_e2e_synthetic_bars` mirroring the 13.7
  Supertrend e2e on BTCUSDT.BINANCE synthetic bars. Smoking-gun
  assertion: at least one reduce-only MARKET order (the standalone
  scale-out partial).

Total: 3,439 unit + 7 integration pass (up from 3,416 + 6 before).

### 3.3 Default-OFF safety

`scale_out_enabled` defaults to `False` per `BracketStrategyConfig`
(Story 13.2). The existing `configs/firms/ftmo.yaml` `donchian_breakout`
block also defaults to False (Story 13.8). No existing Donchian
backtest changes behaviour. The 12.7a M5 baseline numbers for Donchian
(EV +0.167, PF 1.050) are still valid because that run was made BEFORE
this story landed — but they would re-produce byte-for-byte on the
current code given the same defaults.

### 3.4 Pattern duplication note

The four scale-out wiring methods (`on_event`, `_dispatch_scale_out_event`,
`_try_init_scale_state`, `on_bar`, `_evaluate_scale_out_for_bar`) are
nearly identical between `supertrend.py` and `donchian_breakout.py`.
This duplication is conscious: Story 13.11 (MA crossover scale-out)
will add a third user, which is the natural trigger to extract the
wiring into a shared host-side helper (rule of three). Refactoring
after only two users would be premature.

---

## 4. Reproducing the A/B

```bash
cd services/trading-engine

# M5
uv run trading-engine backtest ab \
  --baseline configs/backtest/epic13-donchian-baseline-m5.yaml \
  --variant  configs/backtest/epic13-donchian-scaleout-m5.yaml \
  --out      ../../docs/sprint-artifacts/epic13-donchian-ab-m5-raw.json

# M15
uv run trading-engine backtest ab \
  --baseline configs/backtest/epic13-donchian-baseline-m15.yaml \
  --variant  configs/backtest/epic13-donchian-scaleout-m15.yaml \
  --out      ../../docs/sprint-artifacts/epic13-donchian-ab-m15-raw.json
```

Total wall-clock: ~90 s for both runs.

---

## 5. References

- `docs/sprint-artifacts/epic-12-baseline-comparison.md` — Phase 12.A M5 baseline (Donchian profitable at +0.167)
- `docs/sprint-artifacts/epic-12-baseline-comparison-m15.md` — Phase 12.A M15 retry
- `docs/sprint-artifacts/epic13-supertrend-m15-followup.md` — Supertrend M15 scale-out follow-up
- `docs/sprint-artifacts/validation-report-epic13.md` — Story 13.9 Supertrend M5 A/B (the original +52 % EV result)
- `docs/sprint-artifacts/epic13-donchian-ab-m5-raw.json` — raw output (this story)
- `docs/sprint-artifacts/epic13-donchian-ab-m15-raw.json` — raw output (this story)
