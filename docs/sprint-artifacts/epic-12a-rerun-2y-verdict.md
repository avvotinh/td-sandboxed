# Phase 12.A re-run — correct sizing, 2y window (Track 4.1 verdict)

**Story:** Track 4.1 (docs/strategy-redesign-plan-2026-07-02.md) — re-run Phase 12.A
with the Track-1 sizing fix + Track-2 roster
**Date:** 2026-07-05
**Branch:** `main` (post PR #5)
**Data:** XAUUSD `xauusd-validation` v1.0.0, in_sample 2024-01→2026-01 (2y),
M5 fingerprint `ca810a6170c12167` — 2026-07-04 handover, verified against the
Epic 16 quality report. **Window limitation: 2 years, not the original 5-year
spec** (H1/H4 + pre-2024 shards missing from the handover; Track 0 still open).

---

## Tóm tắt Tiếng Việt

Chạy lại Phase 12.A với sizing đúng (Track 1) trên đúng window in_sample cũ.
Ba kết luận chính: (1) **Sharpe và thứ hạng giữ nguyên gần như từng số** so với
report 2026-05-12 — claim "Sharpe scale-invariant" được xác nhận bằng số liệu;
(2) **ngoại lệ duy nhất là `ma_crossover`: sụp từ +0.137 (best cũ, M15) xuống
−0.097** khi commission tính đúng per-lot — edge cũ là artifact của fee model
sai, quyết định archive ở Track 2.2 được xác nhận định lượng; (3) **kết luận
FTMO compliance cũ ("không phải ràng buộc") bị ĐẢO NGƯỢC hoàn toàn**: với risk
0.5%/trade thật, mọi strategy đều breach max-DD 10%; bộ ba mean-reversion gần
cháy tài khoản trên M5 (DD 96–99%). Không strategy nào qua filter. Best Sharpe
= donchian M5 +0.063 — vẫn dưới ngưỡng quyết định ~0.3 của plan redesign.

---

## 1. Results (defaults, no scale-out, no regime gating)

### M5 (142,130 bars)

| Strategy | Sharpe | old Sharpe (2026-05) | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|---:|
| donchian_breakout | **+0.063** | +0.065 | 40.1% | 1.034 | 35.4% | 4445 | +18.70 |
| orb *(archived)* | +0.026 | +0.026 | 14.3% | 1.048 | 36.6% | 517 | +17.78 |
| ma_crossover *(archived)* | −0.017 | **+0.030** | 31.8% | 0.975 | 33.8% | 2576 | −7.27 |
| supertrend | −0.106 | −0.106 | 68.2% | 0.921 | 32.9% | 3676 | −18.35 |
| mean_reversion *(new)* | −0.216 | n/a | **97.8%** | 0.886 | 35.9% | 11119 | −8.79 |
| rsi_mean_reversion *(archived)* | −0.251 | −0.246 | 96.5% | 0.864 | 48.1% | 9816 | −9.80 |
| bollinger_mean_reversion *(archived)* | −0.280 | −0.265 | **99.4%** | 0.877 | 36.4% | 12940 | −7.68 |

### M15 (47,377 bars)

| Strategy | Sharpe | old Sharpe (2026-05) | Max DD | PF | Win% | Trades | EV $/trade |
|---|---:|---:|---:|---:|---:|---:|---:|
| donchian_breakout | **+0.031** | +0.032 | 29.6% | 1.015 | 34.4% | 1685 | +5.15 |
| orb *(archived)* | −0.019 | −0.019 | 17.9% | 0.971 | 34.0% | 517 | −10.16 |
| supertrend | −0.028 | −0.028 | 24.0% | 0.969 | 33.7% | 1198 | −9.35 |
| ma_crossover *(archived)* | −0.097 | **+0.137** | 29.9% | 0.894 | 31.1% | 808 | −29.65 |
| rsi_mean_reversion *(archived)* | −0.140 | −0.141 | 48.5% | 0.917 | 48.6% | 3247 | −14.51 |
| mean_reversion *(new)* | −0.153 | n/a | 64.0% | 0.927 | 35.7% | 3836 | −16.04 |
| bollinger_mean_reversion *(archived)* | −0.155 | −0.153 | 70.5% | 0.933 | 36.7% | 4911 | −13.55 |

Decision §2 filter (Sharpe ≥ 0.8, DD ≤ 8%, ≥ 200 trades, 0 breaches):
**0/7 pass on either timeframe** — same gate outcome as 2026-05-12.

---

## 2. Findings

### 2.1 Sharpe scale-invariance confirmed — the old rankings were real

For every strategy whose fee treatment did not change, the re-run reproduces
the 2026-05-12 Sharpe to within ±0.015 (supertrend M5 −0.106 vs −0.106; orb M5
+0.026 vs +0.026; rsi M15 −0.140 vs −0.141; …). The sizing bug scaled the
equity curve but not its shape. All *relative* conclusions of the old verdict
survive; all *absolute* ($, DD%, compliance) conclusions do not.

### 2.2 ma_crossover's edge was a fee artifact — archiving vindicated

The one large mover: `ma_crossover` M15 fell from **+0.137 (old best) to
−0.097**, M5 from +0.030 to −0.017. Track 1 made commission lot-aware
(previously undercharged ~100×). With real costs, the highest-Sharpe signal of
the old universe is a net loser. Track 2.2's "edge đã chứng minh là artifact"
call is now backed by numbers. The old §4.1–4.2 recommendations (relax filter
to admit ma_crossover / wire scale-out into it) are **dead** — do not revive.

### 2.3 FTMO compliance conclusion REVERSED — it is now the binding constraint

Old §3.4 ("max DD under 5.1%, compliance is not the binding constraint") is
void as predicted. At a real 0.5% risk per trade, **every strategy breaches
the 10% max-DD** on both timeframes; the three mean-reversion variants lose
essentially the whole account on M5 (DD 96–99%, 10–13k trades). Compliance,
not Sharpe, is now the first gate any candidate must clear.

### 2.4 The consolidated mean_reversion needs its regime gate to mean anything

`mean_reversion` (BB pierce AND RSI extreme) lands between its archived
parents on both timeframes (M5 −0.216, DD 97.8%). Expected: this baseline runs
**without regime gating** (RegimeActor default-OFF), so a RANGING-only
strategy is being force-fed two years of all-regime XAUUSD. Its standalone
number here is a floor, not an estimate. Track 4.3 (ablation ON vs OFF) is the
experiment that actually evaluates it.

### 2.5 Trade counts are the other lever

The only strategy with a survivable DD is orb (14.3% M5) — also the only one
with a session filter and ~500 trades instead of 2.5–13k. This is consistent
with the Track 3 research direction: the trend-followers' problem is not the
entry sign but the volume of low-quality entries (donchian: 4445 trades, PF
1.034 — barely above water before DD). ADX gating + session windows attack
exactly this.

---

## 3. Next steps

1. **Track 4.3 — regime ablation ON vs OFF** on this same manifest: the
   cheapest experiment that can materially change the picture, especially for
   `mean_reversion` (§2.4). RegimeActor is built (Epic 15), default-OFF.
2. **Track 5.1 — implement ADX ≥ 25 gate + session filter** per
   `docs/research/trend-confirmation-filters-2026-07-05.md` and
   `session-filters-xauusd-fx-2026-07-05.md`, then A/B against this baseline.
   Success criterion per filter: DD compression and PF uplift at materially
   lower trade count — not Sharpe alone.
3. **Track 0 — recover the missing 5y/H1/H4 shards** (or Premium re-fetch).
   Everything above is 2y single-symbol; the plan's decision point (§ decision:
   "no strategy > ~0.3 Sharpe → pivot to meta-labeling") should not be
   finalized on 2y data alone, but note that nothing here is within 5× of it.
4. **Do not run the 12.7b parameter sweep.** Same Decision §2 discipline as
   the old verdict: filter-failing strategies are recorded, not tuned.

---

## 4. References

- `docs/sprint-artifacts/epic-12a-rerun-2y-m5.md` / `epic-12a-rerun-2y-m15.md`
  — full comparison tables (this run)
- `docs/sprint-artifacts/epic-12-phase-12a-final-verdict.md` — 2026-05-12
  verdict (sizing-bug banner applies to all $ figures there)
- `docs/strategy-redesign-plan-2026-07-02.md` — Tracks 0–6 + decision point
- `docs/research/trend-confirmation-filters-2026-07-05.md`,
  `docs/research/session-filters-xauusd-fx-2026-07-05.md` — Track 3 outputs
  feeding Track 5.1
