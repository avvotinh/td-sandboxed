# Regime-gate ablation — XAUUSD 2y (Track 4.3 verdict)

**Story:** Track 4.3 (docs/strategy-redesign-plan-2026-07-02.md) — RegimeActor
(Epic 15) ablation ON vs OFF; decide default-ON by the numbers.
**Date:** 2026-07-09
**Branch:** `main`
**Script:** `services/trading-engine/scripts/run_regime_ablation.py`
**Data:** XAUUSD `xauusd-validation` v1.0.0, in_sample 2024-01→2026-01 (2y),
M5 fp `ca810a6170c12167`, M15 fp `b0ad700694500da8` — same shards as the
trailing and entry-filter matrices.
**Calibration:** `configs/firms/ftmo.yaml` `regime_classifier:` block
(XAUUSD, M5-calibrated: ADX≥25/40, BB-width 0.30/0.80 pct, realized-vol
0.025, EMA-slope 5e-4; confirmation 2 bars, warmup 50, feature window 200),
`enabled` flipped ON in-memory by the script — the shipped YAML stays
default-OFF. Allow-lists from the production `@register_strategy`
declarations: supertrend + donchian `{TRENDING_UP, TRENDING_DOWN}`,
mean_reversion `{RANGING}`; HIGH_VOLATILITY/UNKNOWN suppress everyone
(kill-switch); exits never gated (story 15.7).

Cells are the Track 5.1 winners on their trailing-A/B exit tactics. Every
gate-OFF anchor reproduces its `entry-filter-ab-2y-verdict.md` row exactly —
the harness pin held before any ON delta was read.

---

## Tóm tắt Tiếng Việt

Chạy RegimeActor ON vs OFF trên các ô thắng của Track 5.1. Bốn kết luận:

1. **mean_reversion[recross] + gate M5 = ô MR dương đầu tiên của toàn bộ
   redesign**: Sharpe −0.040→+0.035, PF 1.139, win 44.6%, **DD 53.8→4.8%** —
   lần đầu tiên một ô MR nằm dưới ngưỡng FTMO max-DD 10%. Giả thuyết
   Track 2 ("MR chỉ sống trong RANGING") được xác nhận bằng số; recross sửa
   *cách vào*, gate sửa *khi nào được vào* — hai fix cộng hưởng.
2. **supertrend thoát án archive**: gate biến −0.030/DD 41.4% thành
   +0.032/**DD 3.4%** (59 trades). Regime classifier đa-feature + hysteresis
   làm được việc mà ADX(14)≥25 thô không làm được (5.1 §2.2). Nhưng 59
   trades/2y là mẫu cực mỏng — giữ trong roster, chưa promote.
3. **Gate làm hỏng donchian — KHÔNG bật global**: ô tốt nhất redesign
   (+0.087 M5 cross) tụt còn −0.013; M15 +0.062→+0.001. Breakout vào lệnh
   tại *điểm khởi phát* trend — trước khi classifier kịp confirm; phần còn
   lại là entry muộn, lỗ sau phí. Đúng cơ chế ADX-lag đã bác ở 5.1.
   → Cần **per-strategy opt-out** trước khi wire live.
4. **M15 không dùng được với calibration M5** (trường `timeframe` chỉ là
   thông tin — script tái dùng ngưỡng M5): mọi ô M15 gate-ON đều tệ đi hoặc
   không viable (supertrend −0.084, MR[recross] chỉ còn 38 trades). Gate là
   công cụ M5 cho đến khi có calibration riêng M15.

Đòn quyết định: **không** flip `enabled: true` trong YAML. Hướng dùng đúng =
gate theo strategy: MR[recross]+gate và supertrend+gate (M5), donchian
ungated. Hai ô gated M5 lần đầu pass FTMO DD nhưng Sharpe (~+0.03) còn rất
xa gate 0.8 và mẫu mỏng (59–166 trades) — cần OOS + walk-forward trước khi
tin.

---

## 1. Results

### M5 (142,130 bars)

| Cell | Arm | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---|---:|---:|---:|---:|---:|---:|
| supertrend[none] *(trail-only)* | off | −0.030 | 41.4% | 0.962 | 29.9% | 3951 | −9.66 |
| | **on** | **+0.032** | **3.4%** | 1.296 | 37.3% | 59 | +77.42 |
| supertrend[adx+session] | off | −0.015 | 14.2% | 0.949 | 30.5% | 478 | −14.55 |
| | **on** | +0.021 | 2.9% | 1.208 | 38.6% | 44 | +54.67 |
| donchian[cross] *(bare)* | off | **+0.087** | 25.7% | 1.079 | 36.2% | 3029 | +36.13 |
| | **on** | −0.013 | 20.9% | 0.967 | 33.5% | 558 | −11.21 |
| mean_reversion[none] | off | −0.216 | 97.8% | 0.886 | 35.9% | 11119 | −8.79 |
| | **on** | −0.073 | 59.4% | 0.912 | 37.1% | 2893 | −17.59 |
| mean_reversion[recross] | off | −0.040 | 53.8% | 0.950 | 38.8% | 2670 | −12.03 |
| | **on** | **+0.035** | **4.8%** | 1.139 | 44.6% | 166 | +43.31 |

### M15 (47,383 bars) — ⚠ M5-calibrated thresholds (see §2.4)

| Cell | Arm | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---|---:|---:|---:|---:|---:|---:|
| supertrend[none] *(scaleout-beoffset)* | off | −0.011 | 29.9% | 0.977 | 32.9% | 1255 | −6.07 |
| | on | −0.084 | 9.5% | 0.721 | 29.7% | 91 | −87.57 |
| donchian[none] *(scaleout-beoffset)* | off | +0.062 | 20.9% | 1.046 | 39.1% | 1682 | +13.27 |
| | on | +0.001 | 14.8% | 0.993 | 36.8% | 440 | −3.09 |
| mean_reversion[none] | off | −0.153 | 64.0% | 0.927 | 35.7% | 3836 | −16.04 |
| | on | −0.137 | 36.1% | 0.881 | 34.0% | 1055 | −33.65 |
| mean_reversion[recross] | off | −0.189 | 41.3% | 0.823 | 36.3% | 893 | −44.49 |
| | on | −0.011 | 2.6% | 0.942 | 36.8% | 38 | −19.32 |

Full tables: `regime-ablation-2y-m5.md` / `regime-ablation-2y-m15.md`.

---

## 2. Findings

### 2.1 MR[recross] + RANGING gate — the composition the redesign was waiting for

The Track 2 archival thesis (MR strategies died because they traded through
trends) is now measured, not assumed. On M5 the gate removes 94% of
mean_reversion[recross]'s trades and what survives is the first positive MR
cell of the entire campaign: +0.035 Sharpe, PF 1.139, 44.6% win, 4.8% DD.
The two fixes are orthogonal and compose: `recross` fixes *how* to enter
(no falling knives), the gate fixes *when* entering is allowed at all
(confirmed RANGING only). Neither alone is positive (−0.040 recross-only;
gate-only on [none] is −0.073 — the raw band-touch entry stays broken even
inside RANGING).

Caveats before celebrating: 166 trades over 2 years (~1.6/week), and the
per-trade EV (+$43) has to survive out-of-sample. This cell and the
supertrend one below are the priority candidates for the oos_reserve window
(2026-01→2026-05) and a walk-forward pass.

### 2.2 Supertrend escapes the archive — the classifier is the trend filter ADX wasn't

Track 5.1 rejected the raw ADX(14)≥25 gate because its ~28-bar lag removed
early-trend winners along with chop (5.1 §2.2). The regime classifier gates
on four features (ADX, BB-width, realized vol, EMA slope) with 2-bar
hysteresis, and the difference shows: supertrend[none] goes from
−0.030/41.4% DD to +0.032/3.4% DD. Supertrend's *indicator* needs a trend to
be profitable but its *entries* fire constantly; an external "is there
actually a trend" arbiter is exactly the missing piece.

Two implications:

* **The archive verdict is stayed.** Supertrend remains in the roster as a
  gated-only strategy. 59 trades/2y is too thin to promote anything.
* **Stacked static filters are redundant under the gate**: [adx+session]+gate
  is *worse* than [none]+gate (fewer trades, lower EV) — the classifier
  already subsumes the ADX condition, and the session window just deletes
  valid regime-confirmed entries. If the gate is on, run supertrend bare.

### 2.3 The gate breaks donchian — do NOT enable globally

donchian[cross] M5, the redesign's best cell, drops +0.087 → −0.013 under
the gate (M15: +0.062 → +0.001). The mechanism is the same lag that killed
the ADX gate: a Donchian breakout *is* the first bars of a trend — by the
time the classifier confirms TRENDING (features + 2-bar hysteresis), the
channel breakout entry has passed and only late, worse-priced episodes
remain. The kill-switch and warmup suppression also delete a slice of valid
breakouts outright.

This splits the roster's regime story in two:

| Strategy | Regime gate | Why |
|---|---|---|
| mean_reversion | **ON** (M5) | RANGING is confirmable *while it persists* |
| supertrend | **ON** (M5) | enters mid-trend anyway; gate deletes chop |
| donchian_breakout | **OFF** | enters at trend inception; gate = pure lag |

Consequence for wiring: `regime_classifier.enabled` is account-scoped today —
flipping it ON gates every strategy on the account, including donchian
(store injection is unconditional in `runner_facade`/node_factory). A
**per-strategy opt-out** (e.g. `regime_gate: false` in the strategy block)
is now a prerequisite for any live use. Until that exists, the YAML stays
`enabled: false` and gated runs are experiment-only.

### 2.4 M15 needs its own calibration before the gate means anything there

`InstrumentRegimeConfig.timeframe` is informational — the actor classifies
whatever bar stream it is attached to, so the M15 arm ran M5-calibrated
thresholds on bars with 3× the wall-clock horizon and ~√3× the per-bar
volatility. Predictably: supertrend M15 flips *negative* under the gate
(−0.011→−0.084 — the confirmed-TRENDING set on M15 is a different, worse
population), donchian loses its edge, and MR[recross] is starved to 38
trades. No M15 conclusion beyond "recalibrate first" is warranted, and the
M5 wins should not be extrapolated.

### 2.5 Sample-size honesty

Every attractive gated cell is thin: 59 (supertrend), 166 (MR recross)
trades over 2 years. The EV/DD numbers are real but the confidence
intervals are wide — a dozen bad trades would erase the edge. This is why
the verdict is "stay of execution + OOS validation", not "promote".

---

## 3. Current best-known roster configuration (2y XAUUSD evidence)

| Cell | Config | Sharpe | Max DD | FTMO DD ≤10% |
|---|---|---:|---:|:---:|
| donchian M5 | bare + `entry_on_cross_only`, **ungated** | **+0.087** | 25.7% | ✗ |
| donchian M15 | scale-out + BE-offset, ungated | +0.062 | 20.9% | ✗ |
| mean_reversion M5 | `recross` + **RANGING gate** | +0.035 | **4.8%** | ✓ |
| supertrend M5 | trail-only + **trend gate** | +0.032 | **3.4%** | ✓ |

First cells ever under the FTMO drawdown bar — but Sharpe is an order of
magnitude short of the 0.8 gate and the plan's ~0.3 decision point is still
unmet by every cell. The redesign's two levers so far: signal design
(donchian cross) and regime gating (MR, supertrend). They apply to
*different* strategies — there is no single global switch.

---

## 4. Next steps

1. **OOS check** of the two gated M5 cells (MR[recross]+gate,
   supertrend[none]+gate) on `oos_reserve` (2026-01→2026-05) — cheap, same
   script with `--window-name oos_reserve`.
2. **Walk-forward donchian M5 cross** (ungated) — unchanged priority from
   5.1; still the strongest cell.
3. **Per-strategy regime opt-out config** — prerequisite for any non-experiment
   use of the gate (donchian must stay ungated on a gated account).
4. M15 regime calibration — only if/when M15 cells matter; not blocking.
5. Meta-labeling decision point (Track 5.2): the gated-MR result strengthens
   the case that *admission quality* is where the remaining edge lives —
   `RegimeSnapshot.features` → `_meta_label_admits` seam is the designed
   next rung on the same ladder.

---

## 5. References

- `docs/sprint-artifacts/regime-ablation-2y-m5.md` / `-m15.md` — full tables
- `docs/sprint-artifacts/entry-filter-ab-2y-verdict.md` — anchors (Track 5.1)
- `docs/sprint-artifacts/trailing-ab-2y-verdict.md` — exit tactics
- `configs/firms/ftmo.yaml` — regime calibration (shipped default-OFF)
- `src/regime/actor.py`, `src/strategies/base_strategy.py::_regime_admits` —
  gate mechanics (Epic 15 stories 15.5/15.7)
- `tests/integration/regime/test_regime_actor_ablation_csv.py` — story 15.9
  fixture-level ablation this experiment scales up
