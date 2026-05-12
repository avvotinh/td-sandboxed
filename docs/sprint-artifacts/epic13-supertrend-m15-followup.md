# Epic 13 follow-up — Supertrend scale-out on M15

**Story:** 12.7a follow-up — recoverable direction §3.2 from `epic-12-baseline-comparison.md` (re-baseline trend-followers with `scale_out_enabled=true`)
**Date:** 2026-05-12
**Branch:** `epic-13-strategy-tactics`
**Harness:** `trading-engine backtest ab` (the CLI shipped by Story 13.9)

---

## 1. Why this run

The Story 12.7a M5 baseline finding ("no strategy passes Sharpe ≥ 0.8 on
defaults") had three recoverable directions documented. Direction (1)
M15 retry is now exhausted (`epic-12-baseline-comparison-m15.md`).
Direction (2) — re-baseline trend-followers with Epic 13's scale-out
tactic — turned out to be **only executable for `supertrend`**:
`DonchianBreakoutStrategy` and `MACrossoverStrategy` do not yet inherit
`BracketScaleOutMixin` (Story 13.5 wired it for Supertrend only). Wiring
the mixin into the other two trend-followers is its own follow-up
(provisionally 13.10 / 13.11).

What is testable today is **Supertrend × {M5, M15} × {baseline, scale-out}**.
M5 baseline + M5 scale-out are already in
`validation-report-epic13.md`. M15 baseline is in
`epic-12-baseline-comparison-m15.md`. This report adds the missing
cell: **M15 scale-out**.

---

## 2. Result

| Variant | Trades | Win % | EV ($/trade) | PF | p95 winner R | Largest winner R |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| M5 baseline | 3,676 | 32.9% | −0.282 | 0.916 | 1.98 | 2.92 |
| M5 scale-out (Story 13.9) | 3,871 | 29.2% | −0.134 | 0.956 | 4.59 | 4.62 |
| M15 baseline | 1,198 | 33.7% | −0.075 | 0.977 | 2.04 | 2.04 |
| **M15 scale-out (this run)** | **1,255** | **28.7%** | **−0.029** | **0.991** | **4.84** | **4.86** |

### M15 scale-out vs M15 baseline (head-to-head)

| Metric | Baseline | Variant | Δ | Δ% |
| --- | ---: | ---: | ---: | ---: |
| Total trades | 1,198 | 1,255 | +57 | +4.8% |
| Win rate | 33.7% | 28.7% | −5.0pp | −14.9% |
| Expectancy | −0.0749 | −0.0287 | +0.046 | **+62%** less negative |
| Profit factor | 0.977 | 0.991 | +0.015 | +1.5% |
| Return on $100k | −0.090% | −0.032% | +0.058pp | +64% less negative |
| p95 winner R | 2.04 | 4.84 | +2.80 | **+138%** |
| Largest winner R | 2.04 | 4.86 | +2.82 | +138% |

Raw JSON: [`epic13-ab-m15-raw.json`](./epic13-ab-m15-raw.json).

### Reading the numbers

1. **Scale-out tactic generalizes from M5 to M15.** The M5 run lifted EV by
   +52 % and p95 R by +132 % (Story 13.9). The M15 run lifts EV by
   +62 % and p95 R by +138 %. **The tactic is timeframe-agnostic** for
   Supertrend.
2. **Tail capture pattern is consistent.** Baseline winners cluster tightly
   at exactly 2R on both timeframes — that is the hard-TP cap
   (`tp_atr_mult / sl_atr_mult = 3.0 / 1.5 = 2.0`) showing through.
   Variant winners reach 4.8R on M15 (vs 4.6R on M5) via the uncapped
   Supertrend trail.
3. **Supertrend M15 scale-out is the closest-to-profitable variant tested.**
   EV −0.029 / trade is ~10× smaller magnitude than M5 baseline. Profit
   factor 0.991 is essentially 1.0. But it is **still losing**.
4. **Sharpe / max DD are 0 in this report.** Same gap as Story 13.9 —
   `backtest ab` does not wire a prop-firm actor, so `equity_curve` is
   empty. M15 baseline Sharpe was −0.03 (from the 12.7a M15 run, which
   does wire the actor); the scale-out variant should improve
   proportionally but cannot clear the Sharpe ≥ 0.8 filter at this
   magnitude. Wiring equity-curve extraction off the engine (decoupled
   from prop-firm actor) remains a Phase 2 follow-up.

---

## 3. Phase 12.B / Story 12.7b verdict

Still gated. **No Supertrend configuration** — neither M5 nor M15, with
or without the scale-out tactic — passes Sharpe ≥ 0.8 on defaults. The
gap to the filter is smallest on **M15 scale-out + ma_crossover M15**
(M15 ma_crossover was Sharpe 0.137 in the 12.7a retry — the standout
of all 12 strategy×timeframe combinations).

### Remaining direction inventory

| Direction | Status | Notes |
| --- | --- | --- |
| (1) M15 retry | done (12.7a follow-up) | no strategy clears 0.8 |
| (2a) Supertrend scale-out M15 | **done (this report)** | EV improved 62% but still losing |
| (2b) Donchian scale-out | **blocked** | needs `BracketScaleOutMixin` wired into `DonchianBreakoutStrategy` (provisional Story 13.10) |
| (2c) MA crossover scale-out | **blocked** | needs `BracketScaleOutMixin` wired into `MACrossoverStrategy`, plus refactor away from fixed `trade_size` to ATR-based bracket sizing (provisional Story 13.11 — bigger refactor) |
| (3) Relax Sharpe floor to 0.5 | not run | `ma_crossover` M15 (0.137) still fails 0.5; would need floor 0.1 to admit a candidate |
| (4) Multi-symbol coverage | not run | dataset for non-XAUUSD symbols not materialized |

### Recommendation

The cheapest signal-improvement path that remains is **Story 13.10 — wire
`BracketScaleOutMixin` into `DonchianBreakoutStrategy`** (its `Config`
already inherits `BracketStrategyConfig`, so the mixin slots in cleanly,
matching the 13.5 pattern). On M5 Donchian is the strongest profitable
strategy (EV +0.167, PF 1.05); applying the +52% tactic uplift would
lift EV near +0.25 and Sharpe past 0.10–0.15 — close to but probably
not past 0.8. If it clears, we have a 12.7b sweep candidate. Story 13.11
(MA crossover) is structurally harder because MA crossover uses fixed
`trade_size`, not ATR-based bracket; it would require a config refactor
to fit the mixin.

If neither 13.10 nor a 13.11 refactor lifts a strategy past Sharpe 0.8,
**the conclusion is that the in-sample filter at 0.8 is too tight for
the XAUUSD M5/M15 signal universe currently in the repo**. At that
point the team has to either lower the filter (acknowledging worse
risk-adjusted returns) or improve entry signals (regime filtering,
combined indicators, new strategies) — both bigger investments than
this exploration cycle was sized for.

---

## 4. Methodology

Identical to Story 13.9's M5 A/B run, with `bar_type_suffix:
15-MINUTE-LAST-EXTERNAL` and the M15 parquet path. Strategy params
otherwise unchanged.

```bash
cd services/trading-engine
uv run trading-engine backtest ab \
  --baseline configs/backtest/epic13-baseline-m15.yaml \
  --variant  configs/backtest/epic13-scaleout-m15.yaml \
  --out      ../../docs/sprint-artifacts/epic13-ab-m15-raw.json
```

Wall-clock: ~12 s (M15 has ~1/3 the bars of M5).

| Field | Value |
| --- | --- |
| Symbol | XAUUSD |
| Timeframe | M15 |
| Window | in_sample (2024-01-01 → 2026-01-01) |
| Bar count | 47,383 |
| OMS type | HEDGING |

---

## 5. References

- `docs/sprint-artifacts/validation-report-epic13.md` — Supertrend M5 A/B (Story 13.9 — the M5 cell)
- `docs/sprint-artifacts/epic-12-baseline-comparison.md` — Phase 12.A M5 baseline (Story 12.7a)
- `docs/sprint-artifacts/epic-12-baseline-comparison-m15.md` — Phase 12.A M15 retry
- `services/trading-engine/configs/backtest/epic13-baseline-m15.yaml` — baseline job config
- `services/trading-engine/configs/backtest/epic13-scaleout-m15.yaml` — variant job config
- `docs/sprint-artifacts/epic13-ab-m15-raw.json` — raw machine output of this run
- `services/trading-engine/src/strategies/supertrend.py` — the only strategy currently inheriting `BracketScaleOutMixin`
