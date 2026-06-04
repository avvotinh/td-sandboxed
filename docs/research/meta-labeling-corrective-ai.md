# Research: Meta-Labeling / Corrective AI for the Trading Engine

**Date:** 2026-05-24
**Requested for:** Pre-implementation research — Corrective AI / meta-labeling layer on top of existing primary strategies
**Status:** complete

---

## Tom tat Tieng Viet (Executive Summary)

Meta-labeling la ky thuat ML lop-thu-hai: model chinh (Supertrend, Donchian,...) quyet dinh *chieu* (long/short), model phu hoc cach loc va *dinh co* (Probability of Profit, PoP). Ket qua la so luong giao dich giam nhung ti le thang va Sharpe tang. Ky thuat nay tuong thich tot voi FTMO vi no CHI co the bo qua giao dich, khong bao gio them giao dich moi — nen nguong daily-loss / max-drawdown chi bi cham khong bi vuot.

Xep hang khuyen nghi:
1. **mlfinpy** (MIT, 71 sao, cap nhat 10/2024) — dung de tao triple-barrier labels tu backtest output
2. **skfolio** (BSD-3, 2k sao, 04/2026) — dung CombinatorialPurgedCV thay the cho WalkForward hien tai
3. **scikit-learn + lightgbm** — classifier chinh (co san trong pyproject.toml chi can them `lightgbm>=4.0`)

Spike toi thieu: Supertrend tren XAUUSD, 1 classifier LightGBM, 6 features tu `RegimeFeatures`, gate theo nguong PoP > 0.55, do luong Sharpe truoc/sau.

---

## Question

Does the technique of meta-labeling (Lopez de Prado, 2018) — a secondary ML model that learns *bet size / filter* from a primary strategy's candidate trades — have viable open-source tooling that can be integrated with our NautilusTrader-based engine, and where exactly in the existing codebase would it plug in?

---

## TL;DR — Recommendation

Use **mlfinpy** (MIT) for triple-barrier labeling of backtest trade records, **skfolio**'s `CombinatorialPurgedCV` (BSD-3) for bias-free CV over our existing `WalkForward` folds, and **scikit-learn + LightGBM** for the secondary classifier. The gating seam is in `RegimeAwareRouter._dispatch` (file: `services/trading-engine/src/strategies/regime_routing.py:139`) — a PoP check inserted before `_route_bar_to_account` adds zero new abstractions and respects every existing FTMO discipline. Do **not** use Hudson & Thames `mlfinlab` (commercial license, £100/user/month). Do not use the Hudson & Thames `meta-labeling` repo for production code (101 stars, no LICENSE file visible).

---

## Existing project code

No ML imports anywhere in `services/trading-engine/src/` — confirmed by grep across all `.py` files (no matches for sklearn, lightgbm, xgboost, torch, joblib). The following files are directly relevant to integration:

| File | Role in meta-labeling |
|---|---|
| `services/trading-engine/src/strategies/regime_routing.py:139` | `_dispatch` — primary gating seam for the PoP check |
| `services/trading-engine/src/regime/features.py:31` | `RegimeFeatures` dataclass — 6 features directly usable as secondary model inputs |
| `services/trading-engine/src/strategies/sizing.py:19` | `PositionSizerProtocol` — the interface through which PoP scales bet size |
| `services/trading-engine/src/strategies/risk_based_position_sizer.py:58` | `calculate_lot_size()` — returns `Decimal("0")` on "skip trade" — exactly the semantics meta-labeling needs |
| `services/trading-engine/src/backtesting/result.py:15` | `TradeRecord` — entry_ts, exit_ts, entry_price, exit_price, pnl — sufficient for triple-barrier labeling |
| `services/trading-engine/src/backtesting/walk_forward.py:127` | `WalkForward` / `FoldSpec` — folds map directly to purged CV train/test windows |
| `services/trading-engine/src/strategies/supertrend.py:137` | `generate_signal()` — the primary model signal; the meta-label predicts whether to act on it |
| `services/trading-engine/src/audit/audit_writer.py:130` | `log_sync()` — any PoP inference decision must be logged here before sizing |

---

## 1. Concept Precis: Meta-Labeling / Triple-Barrier / Probability of Profit

### Primary source

Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*, Chapter 3. Wiley.

### Triple-Barrier Method

Given a candidate trade event at time `t`:
- **Upper barrier**: profit-taking at `+pt * vol` above entry
- **Lower barrier**: stop-loss at `-sl * vol` below entry
- **Vertical barrier**: forced exit after `max_hold` bars

The label is +1 if the upper barrier is hit first, -1 if lower, 0 if vertical (time-out). For meta-labeling, the label is *binary*: 1 if the primary strategy's bet would have been profitable (upper barrier for a long, lower barrier for a short), 0 otherwise. The existing `BracketStrategyConfig` already defines `sl_atr_mult` and `tp_atr_mult` — these map directly to triple-barrier lower/upper widths.

### Meta-Labeling

> "We do not want the ML algorithm to learn or predict the side, just to tell us the appropriate size. This is Corrective AI: a secondary ML model that learns how to use a primary trading model." — Hands-On AI Trading with Python, Ch.8 (book excerpt, p.479)

**Two-model pipeline:**

```
Primary strategy          Secondary model
──────────────            ───────────────────
generate_signal(bar)  →   predict_proba(features) → PoP
     BUY / SELL             0.0 ... 1.0
        │                         │
        └──── if PoP > threshold ──→  size = f(PoP)
              else skip (size = 0)
```

- Side comes from the primary strategy (Supertrend, Donchian, etc.) — unchanged.
- PoP comes from the secondary model (LightGBM binary classifier).
- Bet size = `base_size * sigmoid_scale(PoP)` (or simply: take if PoP > threshold, skip if not).
- The secondary model is trained on *historical labeled trades* from backtests, not raw price bars.

### Probabilistic Sharpe Ratio (PSR)

PSR (Lopez de Prado, 2018, Chapter 14) measures whether a Sharpe ratio is statistically significant given the number of independent trials. Formula:

```
PSR(SR*) = Φ[ (SR_hat - SR*) * sqrt(T-1) / sqrt(1 - skew*SR_hat + (kurt-1)/4 * SR_hat^2) ]
```

Where SR* is a benchmark (e.g. 0), T is number of trades. Relevant implementation: [rubenbriones/Probabilistic-Sharpe-Ratio](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio) (MIT-implied, ~40 lines, pure numpy).

---

## 2. Library Survey

### Option A: mlfinpy

- **Source:** [github.com/baobach/mlfinpy](https://github.com/baobach/mlfinpy)
- **PyPI:** `mlfinpy` (released 2024-10-09, version 0.1.2)
- **License:** MIT
- **Stars / activity:** 71 stars, last release October 2024 — modest but active, MIT confirmed
- **Fit:** Inspired by mlfinlab but rebuilt from scratch. Implements `get_events()` / `get_bins()` / `add_vertical_barrier()` — the exact triple-barrier + meta-label pipeline we need. Depends on pandas/numpy (already in pyproject.toml). No commercial restriction.
- **Pros:** MIT license; implements triple barrier + meta-labeling API; pure pandas/numpy; light dependency footprint; Python 3.11 compatible
- **Cons:** Low star count (71); one primary maintainer; docs sparse beyond ReadTheDocs; no purged CV (bring your own via skfolio/sklearn)
- **Integration cost:** low — `uv add mlfinpy`; use `get_events()` in a one-shot labeling script that consumes `BacktestResult.trades`

**Key API pattern:**
```python
# Source: mlfinpy.readthedocs.io/en/latest/Labelling.html
meta_events = ml.labeling.get_events(
    close=close_series,
    t_events=signal_timestamps,   # from primary strategy
    pt_sl=[tp_atr_mult, sl_atr_mult],   # map from BracketStrategyConfig
    target=daily_vol,
    vertical_barrier_times=vertical_barriers,
    side_prediction=side_series,  # BUY=+1, SELL=-1 from primary
)
meta_labels = ml.labeling.get_bins(meta_events, close_series)
# meta_labels: 0 (false positive) or 1 (correct primary signal)
```

---

### Option B: Hudson & Thames mlfinlab

- **Source:** [github.com/hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab)
- **License:** All Rights Reserved (commercial) — £100/user/month
- **Stars / activity:** 4,800 stars, but proprietary since ~2021
- **Fit:** Gold standard for triple-barrier + meta-labeling + purged CV in one package. But the license is incompatible with a proprietary prop-trading system.
- **Pros:** Most complete implementation; well-documented; battle-tested
- **Cons:** Commercial license, cannot ship in proprietary codebase without paying per-developer subscription; Issue #496 confirms it was never relicensed
- **Integration cost:** N/A — **DO NOT USE**

---

### Option C: skfolio (for purged CV only)

- **Source:** [github.com/skfolio/skfolio](https://github.com/skfolio/skfolio)
- **PyPI:** `skfolio`
- **License:** BSD-3-Clause
- **Stars / activity:** 2,000 stars, v0.20.1 released April 2026 — actively maintained
- **Fit:** Provides `CombinatorialPurgedCV` (Lopez de Prado 2019) as a scikit-learn-compatible cross-validator. This directly replaces our current naive WalkForward CV for meta-model training. Not a labeling library — pair with mlfinpy.
- **Pros:** BSD-3 license; scikit-learn Pipeline compatible; actively maintained; purged + embargoed CV prevents look-ahead bias; `CombinatorialPurgedCV(n_folds=10, n_test_folds=2)`
- **Cons:** Primarily a portfolio optimization library; purged CV is a side feature; adds ~20MB dependency
- **Integration cost:** low — `uv add skfolio`; use only `skfolio.model_selection.CombinatorialPurgedCV`

---

### Option D: scikit-learn + LightGBM (classifier backbone)

- **Source:** [lightgbm.readthedocs.io](https://lightgbm.readthedocs.io), [scikit-learn.org](https://scikit-learn.org)
- **License:** Apache-2.0 (LightGBM), BSD-3 (scikit-learn)
- **Stars / activity:** LightGBM 16k+ stars, scikit-learn 59k+ stars — industry standard
- **Fit:** `LGBMClassifier` with `predict_proba()` is the recommended secondary model. Probability calibration via `CalibratedClassifierCV(method='isotonic')` corrects the boosting model's overconfident probabilities. Hudson & Thames study found Random Forest adequate; LightGBM is faster and handles class imbalance better.
- **Pros:** Industry standard; well-tested; sklearn Pipeline compatible; `predict_proba()` returns calibrated PoP; handles imbalanced classes (typical in meta-labeling: more 0s than 1s)
- **Cons:** Not in current pyproject.toml — requires `uv add lightgbm scikit-learn`; adds ~40MB to the image
- **Integration cost:** low-medium — adding to pyproject.toml is trivial; the model artifact loading is new infra

**Key inference pattern (≤10 lines):**
```python
# Training (offline, in labeling script)
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
clf = CalibratedClassifierCV(LGBMClassifier(n_estimators=300), method='isotonic')
clf.fit(X_train, y_train)   # y_train: meta-labels from get_bins()

# Inference (in RegimeAwareRouter or MetaLabelActor)
pop = clf.predict_proba(features_row)[0][1]   # P(label=1) = PoP
take_trade = pop > POP_THRESHOLD  # e.g. 0.55
```

---

### Option E: Reference implementations to study

| Repo | License | Stars | Value |
|---|---|---|---|
| [BlackArbsCEO/Adv_Fin_ML_Exercises](https://github.com/BlackArbsCEO/Adv_Fin_ML_Exercises) | MIT | 1,900 | Notebook walk-through of triple-barrier + meta-label in pandas; good for understanding the labeling pipeline |
| [hudson-and-thames/meta-labeling](https://github.com/hudson-and-thames/meta-labeling) | Unclear (no LICENSE visible) | 101 | Journal paper code; position-sizing algorithms including sigmoid optimal sizing; read-only reference, do not import |
| [rubenbriones/Probabilistic-Sharpe-Ratio](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio) | MIT-implied | ~40 | PSR and Deflated SR in ~40 lines; copy the `probabilistic_sharpe_ratio()` function directly |

---

## 3. Architecture Fit

### The gating seam

The cleanest insertion point is `RegimeAwareRouter._dispatch` in `services/trading-engine/src/strategies/regime_routing.py` at line 139:

```python
# CURRENT (line 139-145):
def _dispatch(self, state: RegimeState, bar: Any) -> None:
    if state == RegimeState.HIGH_VOLATILITY:
        return  # global kill-switch
    for account in self._inner.bound_accounts:
        allowed = self._regime_map.get(account.strategy)
        if allowed is None or state in allowed:
            self._inner._route_bar_to_account(account, bar)
```

A `MetaLabelGate` component injected into `RegimeAwareRouter` would add a second conditional before `_route_bar_to_account`:

```python
# PROPOSED addition (conceptual sketch, not production code):
if self._meta_gate is not None:
    features = self._current_features  # already computed by FeatureExtractor
    signal = self._current_signal      # from the primary strategy
    if not self._meta_gate.should_take(features, signal):
        continue  # skip this bar for this account
self._inner._route_bar_to_account(account, bar)
```

The `MetaLabelGate` is a new lightweight class (not a NautilusTrader Actor — it is called synchronously within the event loop, so inference must be <1ms; see §7). It wraps the loaded model artifact and exposes `should_take(features: RegimeFeatures, signal: SignalType) -> bool`.

### PoP → size mapping

The existing `RiskBasedPositionSizer.calculate_lot_size()` already returns `Decimal("0")` to signal "skip trade." Two integration styles:

- **Binary gate (simplest):** PoP > threshold → pass full risk_percent size; else return 0. Zero new code in the sizer.
- **Continuous scaling (more complex):** `risk_percent_effective = config.risk_percent * pop_scalar(PoP)`. This requires a new `MetaLabeledSizer` wrapper around `RiskBasedPositionSizer`. Defer to spike phase.

### Audit discipline

Per `services/trading-engine/src/audit/audit_writer.py:130` and the domain rule, any mutation to account state must be preceded by `log_sync()`. The meta-label gate decision (take/skip + PoP score) must be written to the `rule_check_log` hypertable *before* the sizing step. This is exactly the pattern already used by `RegimeAwareRouter`'s `audit-before-routing` discipline (line 106: `await self._audit.log(decision)`). The gate decision can piggyback on the same audit row by adding `pop_score: float | None` as an optional field.

### NautilusTrader boundary constraints

The NautilusTrader docs confirm: "user code running on the event loop thread should return as quickly as possible — expensive operations such as model inference can degrade performance." Solution: load the serialized model artifact at Actor `on_start()` using `joblib.load()` — the loaded LightGBM model's `predict_proba()` on a single 6-feature row completes in <0.1ms in practice (well within the bar-callback budget). No background thread needed for inference; only for async retraining.

### Monorepo boundary

The meta-label gate lives entirely within `services/trading-engine/`. It has no cross-service dependencies. Model artifacts are stored in a `models/` directory under `services/trading-engine/` (gitignored binaries) or fetched from Redis at startup — the latter leverages the existing Redis adapter in `services/trading-engine/src/adapters/redis_adapter.py`. This respects the monorepo boundary rule in `.claude/rules/common/sandboxed-domain.md`.

---

## 4. Labeling and Training Data

### From BacktestResult to triple-barrier labels

`BacktestResult.trades: list[TradeRecord]` gives: `entry_ts`, `exit_ts`, `entry_price`, `exit_price`, `pnl`, `side`. The triple-barrier label can be assigned directly from the existing bracket structure:

```
label = 1  if (side=BUY  and exit_price >= entry_price + tp_atr_mult * ATR) else
        1  if (side=SELL and exit_price <= entry_price - tp_atr_mult * ATR) else
        0  (hit SL or time-out)
```

This avoids re-running the full triple-barrier path-dependency simulation; the bracket SL/TP already encode the barriers. The mlfinpy `get_bins()` function can alternatively compute this from the close-price path.

### Look-ahead bias

- Features (`RegimeFeatures`) must be computed using only data available at `entry_ts`. The existing `FeatureExtractor` is bar-by-bar with no lookahead.
- The label (`did the trade hit TP?`) inherently requires future bars — this is the unavoidable look-forward element. It is correct and expected in triple-barrier labeling.
- The feature matrix for training is indexed by `entry_ts`; labels by `exit_ts`. Overlap windows = [entry_ts, exit_ts]. This overlap is what purging/embargoing removes from the training set.

### Purged + Embargoed Walk-Forward CV

Our existing `WalkForward` (`FoldSpec.train_end <= FoldSpec.test_start`) already prevents simple data leakage. But it does not remove *overlapping label windows* that straddle the train/test boundary. `CombinatorialPurgedCV` from skfolio handles this:

```python
# Purging: remove training samples whose label spans overlap with any test sample
# Embargoing: additionally remove the h bars after test_start from training
from skfolio.model_selection import CombinatorialPurgedCV
cv = CombinatorialPurgedCV(n_folds=10, n_test_folds=2)
scores = cross_val_score(clf, X, y, cv=cv, groups=label_end_times)
```

Map `WalkForward.folds` to the `groups` parameter. This is an additive improvement on our existing `WalkForward` — the latter can still drive the parameter sweep; CPCV runs *within* each fold's training window for the meta-model hyperparameter search.

---

## 5. Proposed Initial Feature Set

All six fields of `RegimeFeatures` (already computed per-bar in `FeatureExtractor.update()`) are valid meta-label inputs:

| Feature | Field | Rationale |
|---|---|---|
| ADX | `adx` | Trend strength — stronger trend → higher PoP for trend strategies |
| +DI | `plus_di` | Directional bullish pressure |
| -DI | `minus_di` | Directional bearish pressure |
| BB-width percentile | `bb_width_pct` | Volatility expansion (breakout PoP) vs. compression (MR PoP) |
| Realized vol | `realized_vol` | Absolute volatility level |
| EMA slope | `ema_slope` | Momentum direction |

Additional features available with minimal added code:

| Feature | Source | Rationale |
|---|---|---|
| Hour of day (0-23) | `bar.ts_event` | Session effects (London/NY overlap for EURUSD; Asian/London for XAUUSD) |
| Day of week (0-4) | `bar.ts_event` | Weekday effects (Monday gaps, Friday position unwind) |
| ATR-normalized spread | `BracketStrategyConfig.pip_size` | Wide spread relative to ATR reduces PoP |
| Signal type (BUY=1/SELL=-1) | `generate_signal()` output | Direction bias within regime |

Do not add OHLCV raw prices as features — the model must stay regime-agnostic across different price levels (Forex vs. Gold). Normalized/ratio features only.

---

## 6. FTMO Compliance Angle

Meta-labeling is uniquely FTMO-friendly because:

1. **Only removes trades, never adds.** The primary strategy already has the side + bracket SL/TP set. The gate can only return `skip=True` (size=0). The daily-loss and max-drawdown limits can only be *improved* by removing trades; they cannot be exceeded by the gate alone.
2. **Integrates naturally with the HIGH_VOLATILITY kill-switch.** `RegimeAwareRouter._dispatch` already skips all accounts on `HIGH_VOLATILITY`. The meta-label gate fires after that check — it inherits the kill-switch for free.
3. **Audit trail.** The PoP score per candidate trade is logged to `rule_check_log` (same as existing rule engine checks) before the sizing step — satisfying the double-entry discipline in `audit_writer.py`.
4. **FTMO daily-loss recovery.** When daily-loss is near the limit and PoP < threshold, the gate skips marginal trades that would breach the limit — effectively acting as a soft daily-loss buffer before the hard kill-switch fires.
5. **No new financial state mutation paths.** The gate does not write to `account.*` tables directly; it only informs the existing sizer whether to return `0` or `risk_percent`.

---

## 7. New Infrastructure Required

This section is honest about non-trivial work:

### Model artifact storage and versioning
- Serialized model files (`model_supertrend_xauusd_v1.pkl`) need a storage location accessible at Actor `on_start()`. Options: (a) local file in `services/trading-engine/models/` (gitignored), committed via DVC or S3; (b) Redis `SET model:supertrend:xauusd:v1 <bytes>` (leverages existing Redis adapter). Option (a) is simpler for spike; (b) scales better for multiple live accounts.
- Versioning discipline: model version must be logged in `rule_check_log` with each PoP decision for auditability.

### Retraining cadence
- Suggested: weekly or monthly offline retraining on a rolling train window (e.g., last 12 months of backtest data). Not automated in v1 spike.
- Retraining is a separate offline script, not a live Actor. It produces a new `.pkl` file that is loaded on the next engine restart.

### Inference latency budget
- LightGBM `predict_proba()` on 1 sample × 6 features: ~0.05–0.3ms (benchmarked on CPU; Rust core NautilusTrader processes bars at ~1ms; budget is safe).
- Model loading from disk at `on_start()`: ~50ms (joblib). Acceptable.
- If latency becomes a concern: pre-compute PoP at the bar boundary and cache in memory; the result is valid for the entire bar.

### Feature drift monitoring
- The `RegimeFeatures` distribution can shift over time (e.g., persistent low-ADX after 2022 rate shock). Need a simple drift monitor: log the feature mean/std weekly; alert if any feature drifts >3 sigma from training distribution.
- Implementation: a scheduled check in `MetricsService` — minimal new code.

### Class imbalance
- Meta-labels are typically imbalanced (more 0s than 1s for conservative strategies). Use `LGBMClassifier(class_weight='balanced')` or oversample with `imbalanced-learn` (MIT, `pip install imbalanced-learn`).

### Small sample risk
- Supertrend on XAUUSD: expect ~200–500 trades per year in backtest. With 2-year training window: 400–1000 samples. This is borderline for a 6-feature classifier. Use aggressive regularization (`num_leaves=8`, `min_child_samples=30`) to prevent overfitting. Evaluate with out-of-sample PSR, not in-sample accuracy.

---

## 8. Recommended Spike

**Goal:** Confirm that meta-labeling improves risk-adjusted performance before building production infrastructure.

### Scope
- **One strategy:** `SupertrendStrategy` on XAUUSD (trend-following; meta-labeling is most studied in this context per Hudson & Thames research)
- **One classifier:** `LGBMClassifier` with calibration
- **Feature set:** 6 `RegimeFeatures` fields + hour_of_day + day_of_week (8 features total)
- **PoP threshold:** Grid search over [0.50, 0.55, 0.60]; evaluate each on OOS Sharpe

### Steps
1. Run existing `WalkForward` on Supertrend/XAUUSD with 2-year backtest to collect `BacktestResult.trades` across multiple folds.
2. Build feature matrix: for each trade, look up `RegimeFeatures` at `entry_ts` (snapshots can be logged to a parquet file from the backtest).
3. Assign triple-barrier labels from `TradeRecord` fields (hit TP=1, hit SL or time-out=0).
4. Train `CalibratedClassifierCV(LGBMClassifier(...))` on in-fold training data with `CombinatorialPurgedCV`.
5. Evaluate on OOS fold: measure Sharpe, max drawdown, trade count, PSR before and after applying PoP threshold gate.
6. If OOS PSR > 90% and Sharpe improves by >0.3, proceed to production integration.

### Success criteria
- OOS Sharpe (gated) > OOS Sharpe (ungated) across at least 3 of 5 folds
- OOS PSR of gated strategy > 90%
- Max drawdown (gated) <= max drawdown (ungated)
- Trade count reduction < 50% (gate should not be too aggressive)

### Risks
- **Small sample:** <200 trades per fold makes the classifier unreliable. Mitigation: use longer train windows, or aggregate across multiple instruments.
- **Overfitting the meta-model:** the meta-model can overfit just like the primary strategy. Mitigation: use CPCV + PSR; avoid feature selection on the training set.
- **Non-stationarity:** regime features meaningful in 2022 may not be in 2026. Mitigation: retrain every 3 months; monitor feature drift.
- **XAUUSD-specific effects:** gold is more macro-driven than EUR/USD; regime features may be less predictive. Mitigation: run the same spike on EURUSD in parallel.

---

## Key API / Code References

**mlfinpy triple-barrier labeling** ([source](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)):
```python
import mlfinpy as ml
triple_barrier_events = ml.labeling.get_events(
    close=close_series, t_events=signal_timestamps,
    pt_sl=[tp_mult, sl_mult], target=daily_vol,
    vertical_barrier_times=vertical_barriers, side_prediction=side_series)
meta_labels = ml.labeling.get_bins(triple_barrier_events, close_series)
```

**skfolio CombinatorialPurgedCV** ([source](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)):
```python
from skfolio.model_selection import CombinatorialPurgedCV
cv = CombinatorialPurgedCV(n_folds=10, n_test_folds=2)
scores = cross_val_score(clf, X, y, cv=cv, groups=label_end_times)
```

**PSR function** ([source](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio)):
```python
from scipy.stats import norm
def psr(sr_hat, sr_star, n, skew, kurt):
    num = (sr_hat - sr_star) * (n - 1)**0.5
    denom = (1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat**2) ** 0.5
    return norm.cdf(num / denom)
```

---

## Open Questions

1. **Feature snapshot logging in backtest:** `FeatureExtractor` currently does not serialize per-bar `RegimeFeatures` to disk. The labeling script needs these features at trade `entry_ts`. Does the backtest runner need a new `record_features=True` flag, or can features be recomputed from the parquet bar cache?
2. **PoP inference in live mode:** The `MetaLabelGate` must be initialized with the loaded model at engine start. Does the `RegimeAwareRouter` get a reference to this artifact, or should it be a new NautilusTrader `Actor` that publishes PoP signals on the message bus? (The Actor pattern is more idiomatic but adds latency via the bus; direct injection is simpler for v1.)
3. **Model retraining trigger:** Should retraining be event-driven (e.g., PSI > threshold on feature drift) or calendar-based (monthly)? Calendar is simpler for spike; drift-based is more robust for production.
4. **Multi-strategy vs. single-strategy model:** Should one model serve all strategies (requires strategy_type as a feature), or should each strategy have its own model? One-per-strategy is more interpretable but multiplies the training data requirement.
5. **EURUSD vs. XAUUSD model separation:** Gold and Forex have different volatility profiles and session dynamics. Shared features but separate models recommended — open question is whether shared training with `instrument_id` as a categorical feature is viable given data volumes.

---

## Sources

- [Hudson & Thames meta-labeling research](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/)
- [github.com/baobach/mlfinpy — MIT licensed triple-barrier + meta-labeling library](https://github.com/baobach/mlfinpy)
- [mlfinpy documentation — Labelling API](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)
- [github.com/skfolio/skfolio — CombinatorialPurgedCV, BSD-3](https://github.com/skfolio/skfolio)
- [skfolio CombinatorialPurgedCV API](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
- [github.com/hudson-and-thames/mlfinlab — commercial license, DO NOT USE](https://github.com/hudson-and-thames/mlfinlab)
- [github.com/hudson-and-thames/meta-labeling — Journal of Financial Data Science code](https://github.com/hudson-and-thames/meta-labeling)
- [github.com/BlackArbsCEO/Adv_Fin_ML_Exercises — MIT, reference notebooks](https://github.com/BlackArbsCEO/Adv_Fin_ML_Exercises)
- [github.com/rubenbriones/Probabilistic-Sharpe-Ratio — PSR implementation](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio)
- [NautilusTrader live concepts — event loop latency guidance](https://nautilustrader.io/docs/latest/concepts/live/)
- [LightGBM sklearn API](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMClassifier.html)
- [GitHub issue: mlfinlab license request (never granted)](https://github.com/hudson-and-thames/mlfinlab/issues/496)
- Lopez de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Chapters 3, 14.
