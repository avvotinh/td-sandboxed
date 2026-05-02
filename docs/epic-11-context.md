# Epic 11: Market Regime Classifier (Phase 1) — Technical Context

**Created:** 2026-05-02
**Last updated:** 2026-05-02
**Status:** **Backlog** — 7 stories drafted, none in progress
**Epic:** 11 of 11+
**Stories:** 7 (11.1 – 11.7)
**Predecessor:** Epic 10 (Operational Hardening) — closed 2026-05-02 (head `8f42b5c`)
**Source research:** `docs/research/regime-classifier.md`, `docs/research/regime-classifier-architecture.md`

---

## Overview

### Problem Statement

Sau khi Epic 10 đóng (operational hardening + live trading readiness), engine đã chạy được nhiều strategies song song trên 1 instrument, nhưng **tất cả strategies nhận mọi bar bất kể market regime**. Cụ thể, 6 strategies hiện tại:

- **Trend-following**: Supertrend, Donchian breakout, MA Crossover
- **Mean-reversion**: RSI MR, Bollinger MR
- **Volatility breakout**: ORB

…đều đăng ký bar callback chung và mỗi cái tự quyết signal. Hậu quả:

1. **Trend strategies trade trong ranging market** → false breakouts, whipsaw, vi phạm consistency rule của FTMO/The5ers.
2. **Mean-reversion trade trong strong trend** → "catching falling knife", drawdown lớn.
3. **Mọi strategy trade trong high-volatility shock** (CHF flash, FOMC surprise) → daily loss limit dễ violation.

Manual tuning per-strategy không bền vững với 6 strategies × N instruments × M timeframes. Cần một **regime classifier** đứng trước bar router để phân loại market state và route bar chỉ tới strategies phù hợp.

### Solution

Phase 1 ship một **rule-based regime classifier** (4 states) đặt giữa `RedisAdapter` và `StrategyDataRouter`. Phase 2 (deferred) sẽ upgrade lên Hidden Markov Model. Phase 3 (deferred) lên XGBoost + SHAP.

**Decision tree**:

```
Bar arrives → FeatureExtractor (rolling 200 bars)
            → RuleBasedRegimeClassifier.decide(features)
            → HysteresisFilter (2-bar confirmation)
            → AuditLogger.log(decision)        ← FTMO compliance gate
            → if HIGH_VOLATILITY: drop bar     ← global kill-switch
              elif state in strategy.allowed_regimes: route
              else: drop
```

**4 regime states** (academic consensus per State Street 2025, Imperial College working paper):

| State | Routes to |
|---|---|
| `TRENDING_UP` | Supertrend, Donchian, MA Crossover (long) |
| `TRENDING_DOWN` | Supertrend, Donchian, MA Crossover (short) |
| `RANGING` | RSI MR, Bollinger MR |
| `HIGH_VOLATILITY` | **None** — global kill-switch |

### Scope (Phase 1 MVP)

**In Scope:**

- 3 indicators mới (BB width %, realized vol, EMA slope) + ADX reuse từ `src/indicators/adx.py`
- `RegimeFeatures` (9 fields) + `FeatureExtractor` rolling 200-bar window
- `RuleBasedRegimeClassifier` pure decide function với threshold loaded từ YAML
- `HysteresisFilter` 2-bar confirmation per `BarType`
- `RegimeAuditAdapter` ghi `audit_logs` hypertable (event_type=`regime_decision`) qua existing `AuditLogger`
- `register_strategy(regimes=[...])` decorator extension; backwards compat (missing kwarg = always-allow)
- `RegimeAwareRouter` wraps `StrategyDataRouter` (drop-in compatible)
- Feature flag `regime_classifier.enabled: false` mặc định → ship được mà không thay đổi production behavior
- XAUUSD M5 + M15 support, thresholds ở `configs/firms/ftmo.yaml`
- E2E tests với 4 CSV fixtures (trending up/ranging/high_vol/transition)

**Out of Scope (defer Phase 2+):**

- HMM (Hidden Markov Model) primary classifier — `hmmlearn>=0.3`, walk-forward training, joblib serialization
- Hurst exponent feature (`nolds>=0.6.3`) — Phase 1 không cần (4 features đã đủ phân loại)
- `ruptures` change-point detection cho retraining trigger
- Redis hysteresis state persistence (Phase 1 = process-local, accept first-2-bar flicker post-restart)
- XGBoost + SHAP refinement (Phase 3, gate sau 6 tháng HMM-labeled production data)
- Multi-instrument beyond XAUUSD (FX majors, indices)
- the5ers.yaml regime config block
- Per-account regime overrides
- ORB regime mapping (Phase 1 = `regimes=[]`, wires lại ở Phase 2)

---

## Architectural Decisions

### 1. Rule-based Phase 1, HMM Phase 2

**Why:**
- Phase 1 không cần training data — works on first 50 bars (warmup window).
- Fully auditable: mỗi quyết định là một lookup → pass FTMO compliance.
- ADX đã có sẵn (`src/indicators/adx.py`) → reuse, không duplicate.
- Phase 2 (HMM) cần infra training pipeline + walk-forward validation + state-label mapping post-fit — đáng làm trong epic riêng.

**Rejected alternatives:**
- Direct deep learning (LSTM/Transformer): overfit nặng ở 2-5 năm data, black-box → fail FTMO audit.
- Reinforcement Learning: unstable, không deterministic, không pass FTMO consistency rule.
- K-Means / DBSCAN clustering: không có temporal persistence, flicker nặng.

### 2. 4-state taxonomy (không 3 hoặc 5)

**Why:**
- Academic consensus: State Street Global Advisors 2025, Imperial College working paper, MDPI 2024 multiple papers.
- Map 1:1 với 6 strategies hiện có — no orphan strategy, no unused state.
- 5+ states → sparser data per state → fragile thresholds.

### 3. Hysteresis 2-bar confirmation

**Why:**
- Single-bar regime switch flicker khi market hovering near threshold.
- 2 bars đủ chống flicker ngắn hạn, không quá chậm (chỉ 1 bar lag).
- 3+ bars sẽ miss regime change đầu phiên (London open).

### 4. HIGH_VOLATILITY = global kill-switch

**Why:**
- FTMO daily loss limit 5% — high-vol shock có thể violate trong 1 bar.
- An toàn nhất cho Phase 1 (chưa có volatility-targeted strategy production-ready).
- Strategies registered without `regimes=` (always-allow) **vẫn bị block** trong HIGH_VOL — kill-switch phải toàn diện.

### 5. Per-`BarType` classifier instances (không per-account)

**Why:**
- Features là pure function của market data, không phụ thuộc account state.
- Multiple accounts trade cùng XAUUSD M5 → 1 classifier shared, tiết kiệm CPU.
- M5 + M15 đồng thời → 2 instances (key trên `bar_type` string).
- Account binding (1 strategy per account) **không thay đổi**.

### 6. Audit-before-routing pattern

**Why:**
- Match existing `RuleEngine` precedent (`src/engine/...`): write audit before allow/block decision.
- FTMO compliance: mọi trading decision phải có audit trail.
- Volume manageable: ~288 entries/day per (symbol, timeframe) trên M5 — well within `AuditDBWriter` batch capacity (100/60s).

### 7. Decorator-based strategy → regime mapping

**Why chosen:** `@register_strategy("supertrend", regimes=[TRENDING_UP, TRENDING_DOWN])`

- Smallest blast radius — strategies không khai báo `regimes=` continue working unchanged.
- Regime declaration ở cùng nơi với strategy class → cohesion cao.

**Why not YAML field per strategy:** Forces config edits cho all 6 strategies, decouples regime constraint khỏi code.
**Why not shared lookup table:** Bad cohesion — single place phải biết về mọi strategy.

### 8. Feature flag `enabled: false` default

**Why:**
- Ship được Phase 1 without changing production behavior — opt-in rollout.
- Shadow mode possible: `enabled: true` + no strategies declaring `regimes=` → mọi bar được audit log nhưng routing y hệt cũ.
- Per-firm enable: FTMO bật, the5ers tắt → independent rollout.

---

## Story Breakdown

| # | Story | Effort | Phase | Status |
|---|---|---|---|---|
| 11.1 | Indicators (BB width %, realized vol, EMA slope) + RegimeFeatures + FeatureExtractor | L | 11.A Foundation | Backlog |
| 11.2 | Config schema (RegimeConfig pydantic + ftmo.yaml block) | M | 11.A Foundation | Backlog |
| 11.3 | RuleBasedRegimeClassifier (pure decide) + RegimeDecision dataclass | M | 11.B Classifier core | Backlog |
| 11.4 | HysteresisFilter (2-bar confirmation, per-BarType state) | M | 11.B Classifier core | Backlog |
| 11.5 | RegimeAuditAdapter (security-gate story) | M | 11.C Audit + routing | Backlog |
| 11.6 | register_strategy(regimes=) decorator extension | S | 11.C Audit + routing | Backlog |
| 11.7 | RegimeAwareRouter + integration + 6 strategy decorator updates | XL | 11.D Integration | Backlog |

**Total effort:** ~17 effort units (1 S, 4 M, 1 L, 1 XL); estimated 5–7 working days sequential, 3–4 days với 11.1∥11.2 và 11.5∥11.6.

**Per-story details:** Story 11.7 has full doc at `docs/sprint-artifacts/11-7-regime-aware-router-integration.md` (XL stories only per Lightweight docs Option C). Other stories tracked in this context doc + sprint-status.yaml comments.

---

## Risks & Coordination Notes

- **R1**: Story 11.5 depends on `AuditWriter` shipped in 10.3 (commit `4e0c76d`). Public API: `log_async` / `log_sync`. Verify before starting.
- **R2**: Story 11.6 changes `register_strategy` signature. Backwards compat enforced via test (no positional `regimes=` arg required).
- **R3**: Story 11.7 modifies all 6 strategy files (one-line `regimes=[...]` add per file). Inert until `enabled: true` — safe to land.
- **R4**: Hysteresis state on restart **not persisted** (Phase 2 add). First 2 bars post-restart may flicker. Document in operational runbook.

---

## Phase 2 Roadmap (preview, NOT in scope)

Sau khi Phase 1 ổn (~1 tháng production validation):

1. Add `hmmlearn>=0.3`, `joblib>=1.4`, `ruptures>=1.1.9`, `nolds>=0.6.3` deps.
2. Offline training script `scripts/train_regime_hmm.py` — walk-forward, n_init≥5, joblib serialize per-instrument models.
3. `HMMRegimeClassifier` (same interface as `RuleBasedRegimeClassifier`) — fall back to rule-based if `max(proba) < 0.6`.
4. Monthly retraining (cron + ruptures structural-break trigger).
5. Hurst exponent feature → 9-feature vector (vs 4 trong Phase 1).
6. Redis hysteresis state persistence (`regime:{bar_type}:state`).

Reference: `docs/research/regime-classifier.md` §Phase 2 + §Phase 3.
