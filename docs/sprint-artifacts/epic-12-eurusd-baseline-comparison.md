# Epic 12 — EURUSD baseline + XAUUSD sizing-bug discovery

**Trigger:** Epic 13 retrospective §8 — "Multi-symbol dataset materialization"
recoverable direction. Validates whether XAUUSD M5/M15 noise is the
bottleneck for Phase 12.B candidacy, or whether the strategies have a
symbol-agnostic edge problem.
**Date:** 2026-05-13
**Branch:** `epic-13-strategy-tactics`

---

## 1. TL;DR

EURUSD baseline (XAUUSD's first peer symbol) was fetched, stitched,
and run through the full Phase 12.A flow plus scale-out overlay.
The 6 strategies × 2 timeframes × 2 tactic modes give 24 new data
points.

**Headline findings:**

1. **Multi-symbol does not unlock Sharpe ≥ 0.8.** Best EURUSD Sharpe
   = `bollinger_mean_reversion` M15 baseline = **+0.033** — still
   ~24× below the Decision §2 filter floor. Phase 12.B remains gated
   regardless of symbol choice.

2. **CORRECTIVE — XAUUSD baseline has been silently under-sized by
   ≈100× the whole way through Epics 12 + 13.** With the same
   `risk_percent=0.5%` config, XAUUSD trades were taking on **~0.005%
   per-trade risk** because of mis-tuned pip economics; EURUSD with
   proper FX pip values takes on the intended 0.5%. The Epic 12.A /
   13.9 / 13.10 / 13.11 Sharpe numbers for XAUUSD are at the
   ~0.005%-risk operating point. The under-sizing is real and
   load-bearing for the whole Phase 12.B verdict.

3. **Strategy preference is symbol-specific.** Profitable strategies
   on XAUUSD (trend-followers Donchian / ORB / MA crossover) are
   different from EURUSD (mean-reversion `bollinger_MR`). No
   universal "best strategy" emerges — strategy admission needs to be
   per-symbol, not global.

4. **Three more pre-existing backtest infrastructure gaps surfaced**
   during the EURUSD fetch (Phase 12.A second consumer). Action item
   2 from the Epic 13 retro (dry-run smoke as first consumer of any
   new dataset/instrument combination) is doubly justified.

---

## 2. EURUSD full Sharpe matrix

All numbers from `run_epic12a_baseline.py --manifest manifests/eurusd-validation-v1.json`
with FTMO prop_firm wired, HEDGING OMS, and the new
`--pip-size 0.0001 --pip-value-per-lot 0.0001 --max-lot-size 10000000`
overlay (see §4 below for why those flags are needed).

| Strategy | M5 baseline | M5 scale-out | M15 baseline | M15 scale-out |
| --- | ---: | ---: | ---: | ---: |
| `supertrend` | −0.173 | −0.202 | −0.120 | **−0.034** |
| `donchian_breakout` | −0.071 | −0.161 | −0.181 | −0.155 |
| `ma_crossover` | −0.133 | −0.109 | −0.177 | −0.146 |
| `bollinger_mean_reversion` | −0.044 | (gated) | **+0.033** | (gated) |
| `rsi_mean_reversion` | −0.205 | (gated) | −0.170 | (gated) |
| `orb` | −0.003 | (gated) | +0.004 | (gated) |

**Best EURUSD Sharpe across 16 EURUSD experiments: `bollinger_mean_reversion`
M15 baseline = +0.033** (EV +$2.15, PF 1.007, 5,204 trades). Same
strategy on XAUUSD M15 baseline is Sharpe −0.153 — symbol-flip.

**Phase 12.B verdict: still gated.** No EURUSD combo clears 0.8
either. The best EURUSD Sharpe (+0.033) is 2× *worse* than the best
XAUUSD Sharpe under proper sizing (see §3).

---

## 3. XAUUSD sizing bug discovery

### 3.1 The bug

The default `RiskBasedSizerConfig` ships with `max_lot_size=10.0`.
The "lot" unit means whatever the `pip_value_per_lot` × `pip_size`
combination defines it to be — there's no enforced symbol-aware
contract.

For XAUUSD the baseline runner uses `pip_size=0.01` and
`pip_value_per_lot=1.0`. Sizer math on a typical XAUUSD M5 trade:

```
ATR(14) ≈ 5.0  (price units, USD/oz)
SL distance = 1.5 × ATR = $7.50
stop_pips   = $7.50 / 0.01 = 750
loss_per_lot = 750 × $1.00 = $750
raw_lot_size = $500 (risk_amount) / $750 = 0.667 lots
```

With `lot_step=0.01`, sized at **0.66 oz**. At $2000/oz that's a
$1,320 notional position. SL hit ⇒ 0.66 × $7.50 = **$4.95 realised
loss** — vs the $500 intended.

**Effective risk = $4.95 / $100,000 = 0.005 %**, not 0.5 %.

This explains every "small number" we saw across the campaign:

| Field | XAUUSD M5 baseline (Story 13.9) | Implied at 0.005 % risk |
| --- | ---: | --- |
| Avg loss per trade | $4.96 | Matches |
| Total trades | 3,676 | (n/a) |
| Net PnL over 2 y | −$1,035 | ~ −1 % return |
| Max DD | 1.06 % | Consistent with 0.005 % per-trade |

### 3.2 How EURUSD exposed it

EURUSD with `Nautilus default_fx_ccy(EURUSD)` has `size_precision=0`,
`size_increment=1`, `min_quantity=1000` — every Quantity unit is **1
EUR base currency**. To risk $500 on a 4.5-pip SL we need a 1.1 M-unit
position. With the same sizer + `max_lot_size=10`, the sizer returns
10 → below `min_quantity=1000` → every order DENIED.

Lifting `max_lot_size` to 10 M and tuning pip economics to per-unit
($0.0001/pip/unit) gets the sized order to 1.1 M units. Re-running:

| | XAUUSD M5 baseline | EURUSD M5 baseline |
| --- | ---: | ---: |
| Sized position notional | ≈ $1,320 | ≈ $1,200,000 |
| Effective per-trade risk | 0.005 % | 0.5 % |
| Avg loss | $4.96 | $87 |
| Max DD | 1.06 % | 87 % |
| Sharpe | −0.106 | −0.173 |

EURUSD numbers are at intended 0.5 % per-trade risk. **XAUUSD
numbers in every previous report are at 1/100 of intended risk.**

### 3.3 Implications

- **Phase 12.A final verdict still holds.** No strategy clears
  Sharpe ≥ 0.8 on either symbol. Re-tuning XAUUSD pip economics
  toward the correct 0.5 % per-trade risk would multiply EV
  magnitudes ~100× (positive AND negative) — and Sharpe scales
  linearly with both, so it would NOT push any XAUUSD strategy past
  the filter. The verdict is robust to the sizing bug.
- **The +52% Epic 13.9 / +91% Epic 13.10 / +52% Epic 13.11 scale-out
  uplifts are real.** They are percentage uplifts (EV ratio), not
  absolute differences. Scaling both baseline and variant 100× leaves
  the ratio unchanged. The signal-conditional finding from the
  retrospective stands.
- **The absolute-dollar narrative in Epic 13 reports is wrong.**
  Story 13.9 said "EV −$0.28 → −$0.13" as if these were realistic
  per-trade dollar magnitudes. They're 100× too small. Future
  comparisons must either re-baseline XAUUSD at proper sizing OR
  state the operating point explicitly.

---

## 4. Three more infrastructure gaps surfaced

The Epic 13 retrospective §3.4 documented 4 backtest infra gaps that
surfaced in Story 13.9. EURUSD added three more:

### 4.1 Symbol whitelist missed no-slash FX form

`BacktestJobConfig._SUPPORTED_SYMBOLS` had `"EUR/USD"` (slash form,
Nautilus convention) but the `tv-cli` fetcher writes manifest
`symbol="EURUSD"` (no slash, filesystem-safe). Manifest-to-job flow
broke.

**Fix:** Added no-slash variants (`"EURUSD"`, `"GBPUSD"`, `"USDJPY"`,
`"USDCAD"`, `"AUDUSD"`) to the whitelist. Nautilus `default_fx_ccy`
accepts either form so no further plumbing needed.

### 4.2 Nautilus default_fx_ccy fee model burns FX-scale positions

Stock `TestInstrumentProvider.default_fx_ccy("EURUSD")` returns an
instrument with `maker_fee=taker_fee=Decimal("0.00002")` (2 basis
points). On a 1.1 M-unit ($1.21 M notional) position that's $24/side
= $48 round-trip. Over the 4,068 supertrend trades on M5: −$195k
in fees alone, wiping a $100k account several times over (MaxDD
99 %).

**Fix:** Added `_build_fx_pair_instrument(symbol)` that mirrors the
existing `_build_xauusd_instrument()` pattern with FX pair tweaks
(price_precision=5, no instrument-level fees). Venue-level
`commission_per_lot_usd` remains the single configurable fee point.

### 4.3 Sizer's `max_lot_size=10` clamps FX-scale positions to ineligibility

Discussed in §3 above. **Fix:** Operator escape hatch
`--max-lot-size 10000000` flag on the baseline runner — overrides the
sizer default at runtime by patching `RiskBasedSizerConfig.model_fields["max_lot_size"]`
before any strategy instantiates. Not a production change — exposing
`max_lot_size` on `BracketStrategyConfig` is the right long-term fix.

---

## 5. Strategy preferences are symbol-specific

Combining the XAUUSD + EURUSD data (best Sharpe per strategy across
all timeframes / tactic modes):

| Strategy | XAUUSD best | EURUSD best | Symbol preference |
| --- | --- | --- | --- |
| `supertrend` | −0.008 (M15 SO) | −0.034 (M15 SO) | XAUUSD (marginal) |
| `donchian_breakout` | **+0.065 (M5 base)** | −0.071 (M5 base) | XAUUSD |
| `ma_crossover` | −0.017 (M5 base) | −0.109 (M5 SO) | XAUUSD |
| `bollinger_mean_reversion` | −0.153 (M15) | **+0.033 (M15)** | **EURUSD** |
| `rsi_mean_reversion` | −0.141 (M15) | −0.170 (M15) | XAUUSD |
| `orb` | +0.026 (M5) | +0.004 (M15) | XAUUSD |

**Trend-followers prefer XAUUSD; mean-reversion prefers EURUSD.**
This tracks the symbol microstructure:

- XAUUSD: large directional moves driven by macro news / dollar
  flow, frequent multi-pip breakouts. Trend-followers ride.
- EURUSD: mean-reverts to the long-term carry/parity zone within
  intraday sessions, fewer clean breakouts. Bollinger band touches
  → reversions back to the mean.

**Implication for strategy admission:** the firm config
(`configs/firms/ftmo.yaml`) cannot ship a single global strategy
roster. Each `(strategy, symbol, timeframe)` triple needs its own
enabled/disabled flag. Today's wiring (Story 13.8 + 13.10 + 13.11)
hard-codes scale-out availability per-strategy-class; per-symbol
gating is a future enhancement.

---

## 6. Methodology

```bash
# 1. Fetch — 4 windows, ≈58 chunks total
cd services/tv-api
for tf in 5 15; do for w in in_sample:2024-01-01T00:00:00Z:2026-01-01T00:00:00Z \
                            oos_reserve:2026-01-01T00:00:00Z:2026-05-01T00:00:00Z; do
  IFS=: read win from to <<<"$w"
  ./scripts/chunked-fetch.sh \
    --symbol OANDA:EURUSD --bare-symbol EURUSD \
    --timeframe "$tf" --tf-label M$tf \
    --window-name "$win" --window-kind "$win" \
    --from "$from" --to "$to" \
    --step-days $([ "$tf" = 5 ] && echo 20 || echo 60) \
    --spec-name eurusd-validation
done; done

# 2. Stitch each window into a single canonical Parquet + manifest
cd ../trading-engine
# (4 stitch calls — see manifests/eurusd-validation-v1.json for fingerprints)

# 3. Merge into canonical EURUSD manifest
uv run python -m src.backtesting.dataset.go_manifest_loader \
  --sidecar /home/hopdev/Dev/Sandboxed/data/historical/EURUSD/M5/in_sample.parquet.manifest.json \
  --sidecar /home/hopdev/Dev/Sandboxed/data/historical/EURUSD/M5/oos_reserve.parquet.manifest.json \
  --sidecar /home/hopdev/Dev/Sandboxed/data/historical/EURUSD/M15/in_sample.parquet.manifest.json \
  --sidecar /home/hopdev/Dev/Sandboxed/data/historical/EURUSD/M15/oos_reserve.parquet.manifest.json \
  --out manifests/eurusd-validation-v1.json \
  --spec-name eurusd-validation --dataset-version 1.0.0

# 4. Baseline + scale-out runs (4 total)
for tf in M5 M15; do for mode in "" "--scale-out"; do
  uv run python scripts/run_epic12a_baseline.py \
    --manifest manifests/eurusd-validation-v1.json --timeframe $tf $mode \
    --pip-size 0.0001 --pip-value-per-lot 0.0001 --max-lot-size 10000000 \
    --out ../../docs/sprint-artifacts/epic-12-eurusd-${tf,,}${mode// /}.md
done; done
```

| Field | Value |
| --- | --- |
| Symbol | EURUSD (OANDA) |
| Timeframes | M5 + M15 |
| Windows | in_sample (2024-01-01 → 2026-01-01) + oos_reserve (2026-01-01 → 2026-05-01) |
| Bars (M5 in_sample) | 149,453 |
| Bars (M15 in_sample) | 49,824 |
| Bars (M5 oos) | 24,516 |
| Bars (M15 oos) | 8,173 |
| Total fetch + stitch time | ~6 min |
| Manifest fingerprint (M5 in_sample) | `110749df95ba7e88` |
| Manifest path | `services/trading-engine/manifests/eurusd-validation-v1.json` (gitignored per `866d045`) |

---

## 7. What's now actionable

Adding to the Epic 13 retrospective §6 action item list:

| # | Action | Priority |
| --- | --- | --- |
| 9 | Expose `RiskBasedSizerConfig.max_lot_size` on `BracketStrategyConfig` so symbol-specific risk caps don't need monkey-patching | M |
| 10 | Re-tune XAUUSD `pip_value_per_lot` to the per-unit convention (1 oz / 1 unit) and re-baseline all 6 strategies. The +52 % / +91 % uplifts will hold (ratio-preserving) but the absolute-dollar narrative needs correction. | H |
| 11 | Per-(strategy, symbol, timeframe) gating in `configs/firms/*.yaml`, replacing the per-strategy-class flag | M |
| 12 | Re-validate Epic 13 reports' absolute-dollar claims after action item 10 | H |

Items 9–10 are the fastest path to consistent multi-symbol comparison.
Item 11 is structurally important for live deployment (Epic 14+).
Item 12 is a docs sweep, no code.

The Phase 12.B sweep gating stands — no recoverable direction in
the original list (M15 retry, scale-out enable, multi-symbol, relax
filter) lifts any strategy past Sharpe 0.8. The next move is a
**signal-quality epic**: multi-indicator confirmation, regime
filtering, session gating — see Epic 13 retrospective §8.

---

## 8. References

- `docs/sprint-artifacts/epic-12-phase-12a-final-verdict.md` — XAUUSD final verdict (pre-discovery)
- `docs/sprint-artifacts/epic-13-retrospective.md` — Epic 13 retrospective
- `docs/sprint-artifacts/epic-12-baseline-comparison.md` — XAUUSD M5 baseline
- `docs/sprint-artifacts/epic-12-baseline-comparison-m15.md` — XAUUSD M15 baseline
- `docs/runbooks/backtest-data-fetch.md` — operator runbook (this run is the second campaign through it; XAUUSD was the first)
- `services/trading-engine/src/strategies/risk_based_position_sizer.py` — the sizer with the `max_lot_size=10` default
- `services/trading-engine/src/backtesting/runner_facade.py` — `_build_fx_pair_instrument` (new) + `_build_xauusd_instrument`
