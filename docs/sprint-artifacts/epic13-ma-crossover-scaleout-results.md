# Story 13.11 — MA crossover scale-out validation

**Story:** 13.11 — Wire `BracketScaleOutMixin` into `MACrossoverStrategy`
(requires migrating `MACrossoverConfig` from `BaseStrategyConfig` to
`BracketStrategyConfig` and adding ATR-based bracket sizing)
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`
**Trigger:** Phase 12.A recoverable direction §3.2 — re-baseline
trend-followers with `scale_out_enabled=true` (Donchian shipped 13.10,
this closes the MA crossover side)

---

## 1. Summary

`MACrossoverStrategy` now uses ATR-based bracket orders + Epic 13
Phase 1 scale-out via the same `BracketScaleOutMixin` previously
wired into Supertrend (Story 13.5) and Donchian (Story 13.10). The
migration required a config-class change
(`BaseStrategyConfig` → `BracketStrategyConfig`) and replacing the
plain `submit_order(market)` flow with `_submit_bracket_for_entry`.

**Headline corrective finding**: the pre-13.11 MA crossover had **no
stop-loss at all** — it only exited on opposite signal. That meant
trades could ride trends well past any TP and survive arbitrary
retracements. The pre-13.11 Sharpe of **0.137 on M15** (the apparent
winner from Phase 12.A) was an artifact of that risk-free pattern,
not a deployable signal. With proper ATR brackets the same strategy
posts:

| | Pre-13.11 (no SL) | Post-13.11 (ATR bracket) |
| --- | ---: | ---: |
| MA crossover M5 Sharpe | +0.030 | −0.017 |
| MA crossover M15 Sharpe | **+0.137** | **−0.097** |

The Phase 12.A apparent winner becomes another losing strategy once
proper risk management is applied. This is not a regression — it is
the strategy's true character surfacing now that the FTMO-compliant
brackets are in place. A no-SL strategy could never have been
deployed to FTMO regardless of backtest Sharpe.

---

## 2. A/B comparison post-13.11

### M5 (XAUUSD in_sample, 142k bars)

| Metric | Baseline (bracket) | Variant (scale-out) | Δ |
| --- | ---: | ---: | ---: |
| Total trades | 2,576 | 2,637 | +61 |
| Win rate | 33.8 % | 30.4 % | −3.4pp |
| Expectancy | −0.056 | **+0.045** | +0.10 (sign flip) |
| Profit factor | 0.983 | 1.017 | +3.5 % |
| **Sharpe** | −0.017 | **+0.014** | +0.031 |
| Max DD | 0.35 % | 0.34 % | flat |
| p95 winner R | 1.99 | **4.71** | **+137 %** |
| Largest winner R | 2.01 | 4.74 | +136 % |

**MA crossover M5 + scale-out turns profitable** (EV +0.045, Sharpe
+0.014). Small but the sign flip is real — the tactic moves the
strategy from net-losing to net-positive. Sharpe still 57× below 0.8.

### M15 (XAUUSD in_sample, 47k bars)

| Metric | Baseline (bracket) | Variant (scale-out) | Δ |
| --- | ---: | ---: | ---: |
| Total trades | 808 | 827 | +19 |
| Win rate | 31.1 % | 28.2 % | −2.9pp |
| Expectancy | −0.315 | **−0.407** | −0.09 (worse) |
| Profit factor | 0.904 | 0.865 | −4.3 % |
| **Sharpe** | −0.097 | **−0.112** | −0.015 |
| Max DD | 0.34 % | 0.34 % | flat |
| p95 winner R | 2.07 | **4.81** | **+132 %** |
| Largest winner R | 2.08 | 4.83 | +133 % |

**MA crossover M15 + scale-out is HURT** (EV gets worse, Sharpe
slightly worse). Even though p95 winner R doubles, the median winner
drops 2.05R → 1.31R and the loss-rate climbs.

### Strategy × timeframe × tactic matrix (final)

| Strategy | M5 baseline | M5 scale-out | M15 baseline | M15 scale-out |
| --- | ---: | ---: | ---: | ---: |
| `supertrend` | −0.106 | −0.044 | −0.028 | −0.008 |
| `donchian_breakout` | **+0.065** | +0.006 | +0.032 | +0.061 |
| `ma_crossover` | −0.017 | +0.014 | −0.097 | −0.112 |
| `bollinger_mean_reversion` | −0.265 | (gated) | −0.153 | (gated) |
| `rsi_mean_reversion` | −0.246 | (gated) | −0.141 | (gated) |
| `orb` | +0.026 | (gated) | −0.019 | (gated) |

**Best Sharpe across all 16 experiments**: `donchian_breakout` M5
baseline = **+0.065**. Still 12.3× below the 0.8 floor.

Note: this matrix uses the **post-13.11** numbers. The pre-13.11
matrix in `epic-12-phase-12a-final-verdict.md` is now outdated —
`ma_crossover` M15 dropped from +0.137 → −0.097 due to the
risk-management refactor.

---

## 3. Interpretation

### 3.1 Why MA crossover gets opposite tactic effect on M5 vs M15

- **M5**: 20/50 EMA on M5 = 100 min / 250 min ≈ trend filter for
  noisy intraday moves. The crossover is whipsaw-heavy — many bars
  produce signals that retrace immediately. Scale-out at +1R + BE
  protection > tail-foregone cost on this signal shape (similar to
  Supertrend's profile). Result: EV sign flip, Sharpe lifts above 0.
- **M15**: 20/50 EMA on M15 = 5h / 12.5h — a much cleaner trend
  filter that catches longer moves. The signal is structurally
  cleaner; baseline trades ride well to 2R full size. Half-at-1R +
  half-at-BE pattern then dilutes the winners without enough tail to
  compensate — same failure mode Donchian M5 exhibited.

### 3.2 The pattern unifies

Combining Story 13.10 (Donchian) + Story 13.11 (MA crossover) data,
the scale-out tactic effect is now characterizable:

| Signal noise level | Cleaner timeframe → tactic | Noisier timeframe → tactic |
| --- | --- | --- |
| `supertrend` (whipsaw-heavy) | **benefits** | **benefits** |
| `donchian_breakout` (medium) | benefits (M15) | **HURTS** (M5) |
| `ma_crossover` (medium) | **HURTS** (M15) | benefits (M5) |

The split point is **the signal's noise on the chosen timeframe**:
- High-noise signal → scale-out's BE protection dominates → benefits
- Low-noise signal → tail-truncation cost dominates → hurts

This is a refinement of the Epic 13 quant review §2.6 hypothesis
that all trend-followers gain ~+30 % EV uniformly. They don't —
scale-out is a **signal-conditional** tactic.

### 3.3 No Phase 12.B sweep candidate emerges from 13.11

Donchian M5 baseline remains the highest-Sharpe single configuration
across the entire experiment grid (+0.065). MA crossover's apparent
+0.137 was an artifact of having no SL, not a real signal advantage.
Story 12.7b sweep stays gated.

---

## 4. Implementation summary

### 4.1 Config migration

`MACrossoverConfig` now inherits `BracketStrategyConfig` (was
`BaseStrategyConfig`). The legacy `trade_size` field remains on the
inherited surface but is unused — position size now comes from
`RiskBasedPositionSizer` keyed on `risk_percent`. `__post_init__`
validates the fast/slow invariants plus a minimal set of bracket
field sanity checks, matching the Supertrend / Donchian precedent.

### 4.2 Strategy MRO

```
MACrossoverStrategy(
    BracketScaleOutMixin,   # new — Phase 1 scale-out
    BaseStrategy,           # unchanged — Nautilus host
    ATRStopMixin,           # new — ATR-derived SL helper
    RiskSizedMixin,         # new — risk-percent sizing
    BracketStrategyMixin,   # new — _submit_bracket_for_entry
)
```

The `_go_long` / `_go_short` legacy helpers are removed.
`_execute_signal` now mirrors Supertrend: close-on-reversal followed
by `_submit_bracket_for_entry(signal, atr_value)` with the same
`is_atr_unsafe` guard.

### 4.3 Scale-out wiring

The four host-side wiring methods (`on_event`,
`_dispatch_scale_out_event`, `_try_init_scale_state`, `on_bar`,
`_evaluate_scale_out_for_bar`) are copy-equivalent to the
Story 13.5 / 13.10 versions. **The rule of three has now been met** —
three users (Supertrend, Donchian, MA crossover) with identical
wiring. Extraction into a shared host-side helper is the natural
next refactor (queued, not in this story).

### 4.4 Tests

- 35 existing MA crossover tests still pass without modification
  (they test pure logic via simulation helpers, not the actual
  strategy instance).
- **+17 new unit tests** mirror Donchian's scale-out test classes
  (`TestScaleOutMRO`, `TestDispatchScaleOutEvent`,
  `TestEvaluateScaleOutForBar`, `TestTrailIndicatorWiring`).
- **+1 e2e integration test** `test_ma_crossover_scale_out_e2e_synthetic_bars`
  mirrors the 13.7 / 13.10 BTCUSDT pattern with the same smoking-gun
  assertion (at least one reduce-only MARKET scale-out partial).
- **1 strategy roster gate updated**:
  `tests/unit/test_strategy_validation_gate.py` moves `ma_crossover.py`
  from `EXPECTED_NON_BRACKET_STRATEGIES` to `EXPECTED_BRACKET_STRATEGIES`.

3,458 unit + 7 integration pass (up from 3,439 / 7 before).

### 4.5 Default-OFF preserved

`scale_out_enabled` defaults to `False` per `BracketStrategyConfig`
(Story 13.2). `configs/firms/ftmo.yaml` ma_crossover block was already
default-False per Story 13.8, so no firm-config change is needed.
**Existing MA crossover backtests change behaviour** — the SL/TP
brackets now constrain trade life. This is intentional and required
for FTMO compliance; the pre-13.11 unbounded behaviour was unsafe.

---

## 5. References

- `docs/sprint-artifacts/epic13-donchian-scaleout-results.md` — Story 13.10
- `docs/sprint-artifacts/epic-12-phase-12a-final-verdict.md` — verdict before this story (now superseded for MA crossover row)
- `docs/sprint-artifacts/validation-report-epic13.md` — Story 13.9 (Supertrend M5)
- `docs/sprint-artifacts/epic13-supertrend-m15-followup.md` — Supertrend M15 follow-up
- `docs/sprint-artifacts/epic13-ma-crossover-ab-m5-raw.json` — raw M5 output
- `docs/sprint-artifacts/epic13-ma-crossover-ab-m15-raw.json` — raw M15 output
- `services/trading-engine/configs/backtest/epic13-ma-crossover-{baseline,scaleout}-{m5,m15}.yaml`
- `docs/research/strategy-tactics-quant-review.md` §2.6 — uniform-uplift hypothesis (refined by §3.2 above)
