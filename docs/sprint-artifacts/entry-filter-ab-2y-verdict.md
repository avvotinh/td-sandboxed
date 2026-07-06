# Entry-filter A/B matrix — XAUUSD 2y (Track 5.1 verdict)

**Story:** Track 5.1 (docs/strategy-redesign-plan-2026-07-02.md) — implement +
validate the Nhóm-A entry-quality changes from
`docs/research/entry-exit-trailing-analysis-2026-07-05.md`
**Date:** 2026-07-06
**Branch:** `main`
**Script:** `services/trading-engine/scripts/run_entry_filter_ab.py`
**Data:** XAUUSD `xauusd-validation` v1.0.0, in_sample 2024-01→2026-01 (2y),
M5 fp `ca810a6170c12167`, M15 fp `b0ad700694500da8`. Bars verified UTC
(weekend-boundary check: Friday closes 20:55/21:55 UTC, Sunday opens
21:00/22:00 UTC with the correct summer/winter split) — session-filter tz math
is safe on this data.

**What shipped (all config-gated, default-OFF — legacy configs bit-identical):**

| Change | Config | Strategies |
|---|---|---|
| ADX(14) ≥ 25 entry gate | `adx_gate_min` / `adx_gate_period` | supertrend, donchian |
| Session window | `session_filter_tz/open/close/exit_policy` | all 3 (trend: flatten; MR: block_entry) |
| Crossing semantics | `entry_on_cross_only` | donchian |
| Re-cross entry | `entry_mode="recross"` | mean_reversion |

Each strategy runs on its best exit tactic from
`trailing-ab-2y-verdict.md` (supertrend M5: trail-only, M15:
scale-out+BE-offset; donchian M5: bare, M15: scale-out+BE-offset; MR: bare).
`[none]` anchors reproduce those cells exactly.

---

## Tóm tắt Tiếng Việt

Implement 4 thay đổi entry (ADX gate, session filter, donchian crossing, MR
re-cross) và chạy ma trận 26 ô. Bốn kết luận: (1) **donchian
`entry_on_cross_only` M5 là ô tốt nhất toàn bộ redesign** — Sharpe
+0.063→+0.087, PF 1.034→1.079, DD 40→26%, EV gần gấp đôi, trades −32%; đúng
tiêu chí thành công (DD nén + PF tăng + ít trades hơn) và là design fix thuần,
không tune tham số. (2) **ADX(14)≥25 gate THẤT BẠI validation** — làm xấu
Sharpe ở mọi ô (donchian M5 +0.063→−0.020); ADX lag ~28 bar nên chặn cả
entry đầu trend, đúng caveat trong research doc. Ghi nhận, không tune ngưỡng
(kỷ luật Decision §2). (3) **Session filter London+NY cho trend không có
edge trên XAUUSD** sau khi sửa bug staleness (số "đẹp" ban đầu của
donchian[session] M15 là artifact của bug — reviewer bắt đúng); riêng combo
supertrend M5 adx+session nén DD 41→14.2% nhưng Sharpe vẫn âm. (4) **MR
re-cross cắt DD khủng** (97.8→53.8% M5; +session → 41.5%) nhưng vẫn lỗ —
số phận mean_reversion vẫn chờ Track 4.3 regime gate.

---

## 1. Results

### M5 (142,130 bars)

| Strategy[filter] | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|
| supertrend[none] *(trail-only)* | −0.030 | 41.4% | 0.962 | 29.9% | 3951 | −9.66 |
| supertrend[adx] | −0.074 | 36.7% | 0.859 | 30.0% | 970 | −36.61 |
| supertrend[session] | −0.069 | 49.1% | 0.896 | 30.1% | 1773 | −24.13 |
| supertrend[adx+session] | −0.015 | **14.2%** | 0.949 | 30.5% | 478 | −14.55 |
| donchian[none] *(bare)* | +0.063 | 40.1% | 1.034 | 35.4% | 4445 | +18.70 |
| donchian[adx] | −0.020 | 27.8% | 0.973 | 33.8% | 2584 | −8.09 |
| donchian[session] | −0.023 | 27.8% | 0.968 | 37.7% | 2143 | −8.57 |
| **donchian[cross]** | **+0.087** | **25.7%** | **1.079** | 36.2% | 3029 | **+36.13** |
| donchian[adx+session+cross] | −0.032 | 22.6% | 0.942 | 37.2% | 950 | −15.93 |
| mean_reversion[none] | −0.216 | 97.8% | 0.886 | 35.9% | 11119 | −8.79 |
| mean_reversion[recross] | −0.040 | 53.8% | 0.950 | 38.8% | 2670 | −12.03 |
| mean_reversion[session] | −0.235 | 92.7% | 0.850 | 34.0% | 4434 | −20.88 |
| mean_reversion[recross+session] | −0.069 | 41.5% | 0.890 | 37.1% | 1000 | −30.69 |

### M15 (47,383 bars)

| Strategy[filter] | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|
| supertrend[none] *(scaleout-beoffset)* | −0.011 | 29.9% | 0.977 | 32.9% | 1255 | −6.07 |
| supertrend[adx] | −0.070 | 20.2% | 0.866 | 31.6% | 351 | −39.22 |
| supertrend[session] | −0.015 | 21.1% | 0.969 | 31.8% | 757 | −8.31 |
| supertrend[adx+session] | −0.002 | 16.4% | 0.985 | 32.5% | 274 | −4.13 |
| donchian[none] *(scaleout-beoffset)* | **+0.062** | **20.9%** | 1.046 | 39.1% | 1682 | +13.27 |
| donchian[adx] | −0.064 | 25.4% | 0.924 | 37.0% | 890 | −20.30 |
| donchian[session] | −0.046 | 24.4% | 0.934 | 38.4% | 872 | −14.06 |
| donchian[cross] | +0.048 | 23.8% | 1.035 | 39.0% | 1618 | +9.59 |
| donchian[adx+session+cross] | −0.142 | 23.4% | 0.769 | 38.2% | 419 | −48.08 |
| mean_reversion[none] | −0.153 | 64.0% | 0.927 | 35.7% | 3836 | −16.04 |
| mean_reversion[recross] | −0.189 | 41.3% | 0.823 | 36.3% | 893 | −44.49 |
| mean_reversion[session] | −0.202 | 57.1% | 0.858 | 33.5% | 1581 | −34.21 |
| mean_reversion[recross+session] | −0.128 | 22.5% | 0.817 | 34.2% | 360 | −55.77 |

Full tables: `entry-filter-ab-2y-m5.md` / `entry-filter-ab-2y-m15.md`.

---

## 2. Findings

### 2.1 Donchian crossing semantics — the first clean win of the redesign

`entry_on_cross_only` on M5 hits the Track 5.1 success criterion exactly:
trades −32% (4445→3029), PF 1.034→1.079, DD 40.1→25.7%, EV +18.7→+36.1,
Sharpe +0.063→+0.087. The removed trades were precisely the churn re-entries
(same-episode re-fires after an SL/TP exit) diagnosed in the analysis §1.2.
On M15 the effect is mildly negative (+0.062→+0.048) — M15 bars rarely sit
outside the channel for long, so there is little churn to remove and the
filter only delays entries. **Recommendation: adopt on M5 (config), keep
level-triggered on M15.**

### 2.2 ADX(14) ≥ 25 gate — hypothesis REJECTED

The gate makes Sharpe worse in every cell it touches (donchian M5
+0.063→−0.020, M15 +0.062→−0.064; supertrend M5 −0.030→−0.074 despite DD
relief). Mechanism matches the research doc's own caveat: Wilder ADX needs
~2×14 bars to confirm, so on M5/M15 the gate opens ~2.3h/7h *after* the move
starts — it removes early-trend winners along with chop losers, and what
remains (late-trend entries) is net-negative after costs. Per Decision §2
discipline this is **recorded, not tuned** — no threshold sweep. The ADX gate
config stays in the codebase (default-off) for future regime-conditioned use,
but it is not a roster lever.

### 2.3 Session filter (London+NY) — no edge for trend on XAUUSD; pre-fix numbers were a bug

Post-fix, session-gating trend strategies is negative on both timeframes
(donchian M5 −0.023, M15 −0.046 vs positive anchors). XAUUSD trends evidently
do not respect the London+NY window enough to pay for the entries and
overnight continuations given up. Two important notes:

* The **first** run of this matrix showed donchian[session] M15 at +0.044 /
  15.9% DD — that number was an artifact of the session-gate staleness bug
  (rolling band references frozen across the gap, python-reviewer HIGH
  finding). After the fix (state advances on every bar) the same cell is
  −0.046 / 24.4%. A useful reminder that filter backtests are exquisitely
  sensitive to state-across-gap semantics.
* orb's low DD (the internal evidence that motivated the session hypothesis)
  comes from its opening-range *design* (one entry/session, range-anchored
  stop), not from the time window per se — transplanting the window alone
  does not transplant the DD profile.

The one interesting combo: supertrend M5 `adx+session` compresses DD
41.4→14.2% at Sharpe −0.015 — the two filters together throttle supertrend to
~500 trades and near-breakeven. Still not a viable cell (negative edge), but
it is the least-bad supertrend has ever looked; if supertrend survives at all,
this is its shape.

### 2.4 MR re-cross — right direction, still not a strategy

Re-cross entry does exactly what it was designed to do: stop catching falling
knives. M5: trades 11119→2670, DD 97.8→53.8%, Sharpe −0.216→−0.040. Adding the
Asian-session gate compresses DD further (41.5% M5, 22.5% M15) but PF
deteriorates — the surviving trades still lose on average. mean_reversion
remains a floor-measurement without its RANGING regime gate: **Track 4.3 is
now unambiguously the next MR experiment**, run with `entry_mode="recross"`.

### 2.5 Filters do not compose additively

Every "stack everything" cell (donchian adx+session+cross) is worse than the
best single filter alone — the ADX drag dominates whatever the others add.
Filter selection is per-strategy × per-timeframe, same lesson as the trailing
matrix (§2.2 there).

---

## 3. Current best-known roster configuration (2y XAUUSD evidence)

| Cell | Config | Sharpe | Max DD |
|---|---|---:|---:|
| donchian M5 | bare + `entry_on_cross_only` | **+0.087** | 25.7% |
| donchian M15 | scale-out + BE-offset 10p | +0.062 | 20.9% |
| supertrend M5 | trail-only (+adx+session if DD-bound) | −0.030 / −0.015 | 41.4% / 14.2% |
| mean_reversion | recross — pending Track 4.3 regime gate | −0.040 (M5) | 53.8% |

Still 0 cells past the FTMO gate (DD ≤ 10%, Sharpe ≥ 0.8) and none past the
plan's ~0.3 decision point — but donchian M5 cross at +0.087 is the first
material move since the redesign began, and it came from signal design, not
parameters.

---

## 4. Next steps

1. **Track 4.3 — regime ablation** (RegimeActor ON vs OFF) with
   `mean_reversion[recross]` and the donchian/supertrend winners above. Last
   cheap experiment before the meta-labeling decision point.
2. **Walk-forward the donchian M5 cross cell** (per plan §5.1's
   walk-forward requirement) before promoting `entry_on_cross_only` into the
   production config default.
3. Session filter + ADX gate: keep default-off; revisit only as
   regime-conditioned features (e.g. meta-label inputs), not as static gates.
4. Follow-up (review MEDIUM): migrate `trailing_method` /
   `session_filter_exit_policy` / `entry_mode` to `Literal` types together.

---

## 5. References

- `docs/sprint-artifacts/entry-filter-ab-2y-m5.md` / `-m15.md` — full tables
- `docs/sprint-artifacts/trailing-ab-2y-verdict.md` — exit-tactic anchors
- `docs/research/entry-exit-trailing-analysis-2026-07-05.md` — design input
- `docs/research/trend-confirmation-filters-2026-07-05.md`,
  `session-filters-xauusd-fx-2026-07-05.md` — filter research (Track 3)
- `services/trading-engine/src/strategies/mixins/entry_filter_mixin.py` — impl
