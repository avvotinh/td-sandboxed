# Walk-forward donchian M5 — verdict (plan §5.1 requirement)

**Story:** Track 5.1 walk-forward gate (docs/strategy-redesign-plan-2026-07-02.md)
— required before `entry_on_cross_only` could become a production default.
**Date:** 2026-07-09
**Branch:** `main`
**Script:** `services/trading-engine/scripts/run_walk_forward_donchian.py`
(story 12.5 fixed-params harness; rolling train 180d / test 30d / step 30d;
no per-fold tuning — Decision §2)
**Data:** XAUUSD `xauusd-validation` v1.0.0 in_sample 2024-01→2026-01 (2y, M5).
18/18 folds produced metrics; test slices cover 2024-06→2025-12 (the first
6 months are train-only by construction; the plan's original 5y window is
still blocked on the Epic 16 handover gap).
Full tables: `walk-forward-donchian-m5.md`.

---

## Tóm tắt Tiếng Việt

Walk-forward 18 folds (mỗi fold test 1 tháng) cho donchian M5, cả hai biến
thể **FAIL** acceptance Decision §4 một cách dứt khoát:

| Variant | IS Sharpe | Mean OOS | OOS/IS (cần ≥0.7) | CV (cần ≤0.5) |
|---|---:|---:|---:|---:|
| donchian[none] | +0.063 | +0.019 | 0.31 | 12.4 |
| donchian[cross] | +0.087 | **+0.002** | **0.02** | **141** |

**KHÔNG promote `entry_on_cross_only` làm default.** Edge full-window
+0.087 không phải là edge ổn định theo thời gian: 9/18 fold âm, tháng
tốt/xấu của hai biến thể trùng nhau gần hoàn toàn (fold 13 cả hai −0.6;
fold 7/9/10 cả hai dương mạnh) — **regime của tháng quyết định kết quả,
entry semantics chỉ là hiệu ứng bậc hai**. Câu hỏi từ OOS addendum 4.3
("regime-local hay spurious?") giờ có câu trả lời: cái sụp đổ đầu-2026
không phải bất thường — phân phối fold 2024–25 vốn đã là coin-flip quanh 0.

Kết hợp với 4.3: đòn bẩy *signal design* (Track 5) và *regime gating*
(Track 4.3) đều đã đo xong trên 2y XAUUSD — không đòn nào tạo edge OOS
bền. Con đường còn lại theo plan: **Track 5.2 meta-labeling** (chất lượng
admission từng trade — đúng loại lever "học tháng nào nên trade" mà fold
dispersion này chỉ ra), hoặc chấp nhận decision point của plan (không
strategy nào qua ~0.3) và dừng ở nghiên cứu.

---

## Findings

### 1. Both variants fail Decision §4 — comprehensively

Mean OOS Sharpe: none +0.019 (ratio 0.31), cross +0.002 (ratio 0.02) —
against a ≥0.7 bar. CV is off the chart for both (12.4 / 141 vs ≤0.5).
This is not a marginal miss.

### 2. The full-window IS Sharpe was structure, not edge

Full-window cross = +0.087, but the 18 one-month test slices average
+0.002 with std 0.249. The apparent full-window edge comes from a few
strong stretches (2025-01→05 especially: folds 7–10 all positive, up to
+0.367) compounding through, plus the H1-2024 rally months that folds
never test (train-only zone). A strategy whose monthly Sharpe is a
symmetric coin flip around zero can still print a positive 2y line —
that is what happened here.

### 3. Cross vs none is second-order — the month decides, not the entry

Fold-by-fold the two variants are nearly co-moving: catastrophic together
in fold 13 (−0.602/−0.611, Aug 2025), strong together in folds 2/5/7/9/10.
`entry_on_cross_only` still delivers its mechanical goods per fold (fewer
trades, shallower full-window DD 25.7% vs 40.1%) and remains the better
*shape* — but it does not change which months win. Keep the config
default-OFF; keep using it in experiments as the donchian reference shape.

### 4. What this closes and what it opens

* **Closed:** the §5.1 promotion question (NO), and the 4.3 addendum's
  open question — the early-2026 OOS collapse is consistent with the
  in-sample fold distribution, not an anomaly. On current evidence the
  donchian M5 cell has no temporally-stable edge on XAUUSD.
* **Open:** the fold dispersion itself is the signal: months are
  strongly autocorrelated regimes (good months cluster). A per-trade /
  per-period admission layer that learns *when* the strategy works —
  exactly the Track 5.2 meta-labeling design (triple-barrier labels,
  purged CV, `_meta_label_admits`) — is the one unplayed lever. The
  regime gate (4.3) was the rule-based version of this idea and it
  compressed DD but produced no OOS alpha; 5.2 is its learned upgrade.

### Caveats

* 2y in-sample, single instrument (XAUUSD), M5 only; folds test 18 of 24
  months. The plan's 5y walk-forward is still blocked on missing data.
* Fixed-params mode: no per-fold re-tuning, per Decision §2. A tuned
  walk-forward could only look better by fitting — this is the honest
  floor.
* Each fold starts indicators cold (~34 bars ≈ 3h M5 warmup per 1-month
  slice) — identical for both variants, immaterial to the comparison.

---

## Decision

1. `entry_on_cross_only` stays **default-OFF** in production configs.
2. Plan §5.1 is now fully discharged (implement ✓, validate ✗-fail) on
   the 2y data; re-running on 5y when data lands is optional, not
   blocking.
3. Next distinct experiment: **Track 5.2 meta-labeling** — or invoke the
   plan's post-Track-4/5 decision point and pause strategy work. That is
   a roadmap call, not a backtest call.

## References

- `docs/sprint-artifacts/walk-forward-donchian-m5.md` — full fold tables
- `docs/sprint-artifacts/regime-ablation-2y-verdict.md` §5 — OOS addendum
  this answers
- `docs/sprint-artifacts/entry-filter-ab-2y-verdict.md` §2.1 — the IS
  result being tested
- `src/backtesting/dataset/walk_forward_harness.py` — story 12.5 harness
