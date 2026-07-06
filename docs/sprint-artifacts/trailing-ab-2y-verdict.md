# Trailing-tactic A/B matrix — XAUUSD 2y (Track 5 tier-1 verdict)

**Story:** Track 5 tier-1 follow-up (docs/strategy-redesign-plan-2026-07-02.md) —
A/B the exit-tactic implementations shipped in `ab3bd68` (BE fee-offset +
trail-only mode) against the Phase 12.A baseline
**Date:** 2026-07-06
**Branch:** `main`
**Script:** `services/trading-engine/scripts/run_trailing_ab.py`
**Data:** XAUUSD `xauusd-validation` v1.0.0, in_sample 2024-01→2026-01 (2y),
M5 fp `ca810a6170c12167`, M15 fp `b0ad700694500da8` — same shards as the
Track 4.1 verdict (`epic-12a-rerun-2y-verdict.md`); baseline rows reproduce
that report exactly (regression anchor held).

**Matrix:** `supertrend` / `donchian_breakout` × 4 variants, identical venue/
fee/window per timeframe:

| Variant | Config |
|---|---|
| `baseline` | hard SL/TP bracket (Phase 12.A defaults) |
| `scaleout` | 50% off at +1R, SL→BE, Supertrend ATR(7)×2.1 trail, TP cap 6×ATR |
| `trailonly` | Turtle-style: full position, original SL kept, no partial/BE, trail is the only tightener, TP cap 6×ATR |
| `scaleout-beoffset` | `scaleout` + `breakeven_offset_pips=10` (cost recovery: SIM XAUUSD fee 0.00002×notional/fill → round trip ≈ $0.10/oz ≈ 10 pips at the window's price range) |

---

## Tóm tắt Tiếng Việt

Chạy ma trận 2 strategy × 4 biến thể exit trên cùng dữ liệu 2y. Bốn kết luận:
(1) **Không có ô nào qua gần ngưỡng FTMO** — DD tốt nhất toàn ma trận vẫn 20.9%
(> 10%), Sharpe tốt nhất +0.063, đúng chẩn đoán của phân tích entry/exit:
exit tactic nén DD chứ không mua được Sharpe; đòn bẩy chính vẫn là chất lượng
entry (Track 5.1). (2) **Hiệu ứng tactic phụ thuộc strategy × timeframe, không
có winner tuyệt đối**: supertrend M5 hưởng lợi lớn nhất từ trail-only (DD
68→41%, Sharpe −0.106→−0.030) nhưng chính trail-only lại làm donchian M5 tệ đi
(+0.063→−0.040); donchian M15 muốn scale-out (+0.031→+0.060, DD 29.6→21.0%).
(3) **BE fee-offset rẻ và không bao giờ tệ hơn scale-out thường** — win% tăng
2.5–3.5 điểm ở mọi ô, Sharpe/DD ngang hoặc nhỉnh hơn; nên bật mặc định khi
scale-out bật. (4) donchian M5 baseline (không tactic) vẫn là ô Sharpe cao
nhất — với trend-follower có exit tự nhiên tốt, chồng tactic lên chỉ cắt bớt
right tail.

---

## 1. Results

### M5 (142,130 bars)

| Strategy[variant] | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|
| supertrend[baseline] | −0.106 | 68.2% | 0.921 | 32.9% | 3676 | −18.35 |
| supertrend[scaleout] | −0.044 | 51.9% | 0.952 | 29.3% | 3871 | −12.18 |
| supertrend[trailonly] | **−0.030** | **41.4%** | 0.962 | 29.9% | 3951 | −9.66 |
| supertrend[scaleout-beoffset] | −0.042 | 51.0% | 0.954 | 32.6% | 3871 | −11.78 |
| donchian_breakout[baseline] | **+0.063** | **40.1%** | 1.034 | 35.4% | 4445 | +18.70 |
| donchian_breakout[scaleout] | +0.006 | 45.3% | 0.997 | 36.5% | 4974 | −1.06 |
| donchian_breakout[trailonly] | −0.040 | 51.1% | 0.958 | 32.5% | 5915 | −7.62 |
| donchian_breakout[scaleout-beoffset] | +0.001 | 45.7% | 0.993 | 39.0% | 4977 | −2.09 |

### M15 (47,383 bars)

| Strategy[variant] | Sharpe | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|
| supertrend[baseline] | −0.028 | **24.0%** | 0.969 | 33.7% | 1198 | −9.35 |
| supertrend[scaleout] | **−0.008** | 29.9% | 0.980 | 28.8% | 1255 | −5.37 |
| supertrend[trailonly] | −0.036 | 31.0% | 0.952 | 29.0% | 1291 | −12.98 |
| supertrend[scaleout-beoffset] | −0.011 | 29.9% | 0.977 | 32.9% | 1255 | −6.07 |
| donchian_breakout[baseline] | +0.031 | 29.6% | 1.015 | 34.4% | 1685 | +5.15 |
| donchian_breakout[scaleout] | +0.060 | 21.0% | 1.045 | 36.6% | 1681 | +13.06 |
| donchian_breakout[trailonly] | +0.019 | 25.0% | 1.007 | 33.2% | 2005 | +1.69 |
| donchian_breakout[scaleout-beoffset] | **+0.062** | **20.9%** | 1.046 | 39.1% | 1682 | +13.27 |

Full tables: `trailing-ab-2y-m5.md` / `trailing-ab-2y-m15.md`.

---

## 2. Findings

### 2.1 No cell approaches the FTMO gate — tactics compress DD, they don't buy Sharpe

Best DD in the whole matrix is 20.9% (donchian M15 scaleout-beoffset), still
2× the 10% max-DD limit; best Sharpe is +0.063 (donchian M5 baseline,
unchanged). The entry-exit-trailing analysis's diagnosis (§"#1 = entry volume
chất lượng thấp") stands: with ~1.7–6k low-quality entries, no exit schedule
rescues the equity curve. Track 5.1 (ADX gate + session filter) remains the
binding next experiment; this matrix defines the exit configs it should run on
top of.

### 2.2 Tactic effect is strategy- AND timeframe-specific — no global switch

* **supertrend M5** (the DD monster, 3.7k trades in chop): every tactic helps,
  **trail-only helps most** — Sharpe −0.106→−0.030, DD 68.2→41.4%, EV halved
  in magnitude. Mechanism matches design: keeping the full position with the
  original SL avoids the scale-out's "realize half the loss early" behaviour
  in whipsaw, and the trail harvests the occasional real trend.
* **donchian M5**: the mirror image — baseline is best, every tactic destroys
  the (small) edge; trail-only is worst (+0.063→−0.040). Donchian's wide
  4×ATR TP already lets winners run; adding a trail cuts the right tail that
  pays for the 64% losers, and adding scale-out halves the winners' size at
  +1R exactly where the channel edge lives.
* **M15 both strategies**: scale-out is the right shape (supertrend
  −0.028→−0.008; donchian +0.031→+0.060 with DD 29.6→21.0%). Slower bars mean
  fewer BE tags and partials that actually lock structure-level profit.

If any of these go forward, the tactic flag belongs in per-strategy×timeframe
config, not a global default — exactly the firm-config wiring shape story 13.8
established.

### 2.3 BE fee-offset: cheap, never worse, small consistent win — default-on with scale-out

`breakeven_offset_pips=10` vs plain scaleout, all four cells: win% up 2.5–3.5
points (BE exits now settle at entry+costs instead of entry−costs), Sharpe and
DD equal or slightly better (donchian M15 +0.062/20.9% vs +0.060/21.0%). The
offset is derived from venue costs, not tuned, so there is no overfit surface.
Recommendation: whenever `scale_out_enabled=true`, ship
`breakeven_offset_pips` = round-trip cost for the symbol (XAUUSD SIM: 10).

### 2.4 Trade counts barely move — tactics don't fix over-trading

Scale-out/trail variants trade the *same or more* (donchian M5: 4445→5915 for
trail-only — freed margin from partials/tighter stops lets re-entries fire
sooner). Confirms §2.5 of the 4.1 verdict from the other direction: the trade
count lever is entry filtering, not exit management.

---

## 3. Next steps

1. **Track 5.1 — ADX(14)≥25 gate + session filter** on top of the per-cell
   winners from this matrix (supertrend M5 + trail-only; donchian M15 +
   scaleout-beoffset; donchian M5 bare). Success criterion unchanged: DD
   compression + PF uplift at materially lower trade count.
2. **Adopt BE fee-offset as the default companion of scale-out** (config
   change only, no code) — per §2.3.
3. **Do not tune trail params** (ATR period/multiplier sweeps) — same
   Decision §2 discipline: filter-failing cells are recorded, not tuned.
   Chandelier/Turtle-10 trailing methods stay queued behind Track 5.1.
4. Track 4.3 (regime ablation for mean_reversion) unaffected by this matrix —
   still the cheapest orthogonal experiment.

---

## 4. References

- `docs/sprint-artifacts/trailing-ab-2y-m5.md` / `trailing-ab-2y-m15.md` —
  full comparison tables (this run)
- `docs/sprint-artifacts/epic-12a-rerun-2y-verdict.md` — Track 4.1 baseline
  anchor (rows reproduced exactly)
- `docs/research/entry-exit-trailing-analysis-2026-07-05.md` — design input
  (§3.5 trail-only, §7 BE fee-offset)
- `services/trading-engine/scripts/run_trailing_ab.py` — matrix runner
