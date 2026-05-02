# Research: Market Regime Classification for Strategy Routing

**Date:** 2026-05-02
**Requested for:** Smart strategy router — Epic 11 (or next epic) — routes among Supertrend, Donchian, ORB, RSI mean-reversion, Bollinger mean-reversion, MA Crossover
**Status:** complete

---

## Question

Which ML / statistical approach is most production-ready for classifying current market regime
(trending-up / trending-down / ranging / high-volatility) on M5/M15 OHLCV bars, given FTMO
auditability requirements and limited training data (2-5 years)?

---

## Executive Summary

**Use a two-layer hybrid: Hidden Markov Model (HMM) as the primary regime detector, plus a
rule-based ADX/volatility gate as a confirmatory layer.** HMM is the most production-proven
approach for FX and gold regime detection, with strong academic backing (outperforms GMM and
clustering per LSEG 2024, MDPI 2024), sub-millisecond inference on a single bar, and a
well-maintained Python library (hmmlearn ≥ 0.3). The ADX gate is not optional — it provides
the auditability that FTMO compliance requires ("ADX=31 + HMM state=1 → trending"). Use 4
regime states matching the strategy inventory. Tree-based ML (XGBoost / LightGBM) on an
engineered feature vector is the recommended Phase 2 upgrade once labeled training data
accumulates. Avoid deep learning (LSTM, Transformer) as a primary approach: overfit risk is
severe at 2-5 year data scales, and black-box outputs are incompatible with FTMO audit
requirements.

---

## Comparison Table

| Approach | Accuracy (FX/gold) | Inference latency | Auditability | Overfit risk | Complexity | Recommended? |
|---|---|---|---|---|---|---|
| Rule-based (ADX + BB width) | Low-Medium | <0.1 ms | Excellent | Minimal | Trivial | Yes — baseline |
| HMM (GaussianHMM, 4-state) | Medium-High | <1 ms | Good (state probs) | Low-Medium | Low | **Yes — primary** |
| Statistical Jump Model | Medium-High | <1 ms | Good | Low | Medium | Phase 2 |
| GMM (Gaussian Mixture) | Medium | <1 ms | Good | Medium | Low | Acceptable alt |
| Clustering (K-Means, DBSCAN) | Low-Medium | <1 ms | Medium | Medium | Low | No — static |
| Tree-based ML (XGBoost/LGBM) | High (if labeled) | <5 ms | Good (SHAP) | Medium-High | Medium | Phase 2 |
| Change-point (ruptures/BOCPD) | — (different task) | 1-50 ms | Medium | Low | Medium | Supplementary |
| Deep learning (LSTM/Transformer) | Potentially high | 5-50 ms | Poor | Very high | High | No |
| Hybrid (HMM + tree model) | High | <5 ms | Good | Medium | Medium | Phase 2 |

---

## Detailed Analysis

### 1. Rule-Based Baseline (ADX + Bollinger Width + EMA slope)

**What it does:** ADX > 25 with +DI > -DI → trending-up; ADX > 25 with -DI > +DI → trending-down;
BB-width percentile (20-period, rolling 100-bar) > 80th → high-volatility; else → ranging.

**Strengths:**
- Zero training data required — works on first 50 bars.
- Fully auditable: every decision is one lookup.
- ADX is already implemented in the project (`src/indicators/adx.py`).
- Latency: ~0.01 ms.

**Weaknesses:**
- Thresholds are hand-tuned and instrument-specific; XAUUSD and EURUSD have very different ADX
  distributions.
- No probabilistic uncertainty — hard transitions are jarring in production.
- Does not separate ranging from high-volatility on the downside.

**When to use:** Always — as a fallback and FTMO audit evidence alongside any ML model.

**Pitfall:** Do not hardcode ADX threshold 25 across instruments. Derive it as the 60th percentile
of realized ADX over the trailing 252 bars. FTMO compliance requires thresholds load from
`configs/ftmo-presets.yaml`, not source code.

---

### 2. Hidden Markov Model (GaussianHMM, 4-state) — Primary Recommendation

**What it does:** Learns latent market states from an observation sequence (feature vector per bar).
Each state has a Gaussian emission model (mean + covariance of features). Viterbi decode gives
current state; `predict_proba` gives posterior confidence per state.

**Strengths:**
- Production-proven: HMM outperforms GMM and clustering (LSEG benchmark 2024, MDPI 2024,
  QuantStart QSTrader integration).
- Regime persistence is built-in via the transition matrix — avoids rapid flickering.
- 4-state model aligns with literature ("four states is optimal for describing market dynamics" —
  State Street Global Advisors 2025 report).
- Inference: `model.predict([feature_vector])` → microseconds.
- Training: converges on 500-2000 bars (3-12 months of M15 data).
- Explainable in audit: log `state_id`, `state_proba`, `feature_vector` per bar.

**Weaknesses:**
- EM training is sensitive to initialization; multiple restarts required.
- HMM state labels are arbitrary post-training — require post-hoc assignment (map state N to
  "trending-up" by correlating with realized directional returns).
- Detection lag: 1-3 bars average before regime probability crosses 0.6 threshold.
- States can "flip" across retraining runs (state 0 in one run ≠ state 0 in the next).

**Library:** `hmmlearn >= 0.3` — MIT license, scikit-learn-compatible API, numpy-backed C extension.
Context7 confirmed: `GaussianHMM(n_components=4, covariance_type="full", n_iter=100)`.

**When to use:** Primary regime detector, trained monthly on rolling 2-year window per instrument.

**Critical pitfall:** Never train on the full history then label the training set as "ground truth."
Use walk-forward: train on T-730 to T-1, classify T. Recalibrate monthly.

---

### 3. Statistical Jump Model (jumpmodels library)

**What it does:** Adds a "jump penalty" on state transitions, making regimes more persistent than
HMM. Directly optimizes a loss that targets strategy performance. Outperforms HMM on equity
indices in Shu & Mulvey (2024), achieving higher Sharpe ratios and lower max drawdown
(US/German/Japanese indices 1990-2023).

**Strengths:**
- Superior persistence vs HMM — fewer spurious state switches.
- scikit-learn API: `.fit()`, `.predict()`, `.predict_proba()`.
- Validated in peer-reviewed finance journals (Annals of Operations Research 2024, Journal of
  Asset Management 2024).
- Feature-selection variant (SparseJM) handles high-dimensional feature sets safely.

**Weaknesses:**
- Newer library (jumpmodels, 146 stars) — less battle-tested in production.
- Slightly more hyperparameters (jump penalty λ requires cross-validation).
- Research focus is equity indices; FX/gold evidence is thinner.

**Library:** `jumpmodels` (GitHub: Yizhan-Oliver-Shu/jump-models, 146 stars, Python ≥ 3.8, MIT).
API: `from jumpmodels.jump import JumpModel`.

**When to use:** Phase 2 — replace HMM with JumpModel if HMM shows excessive state flickering
in production, or once the library accrues more community validation.

---

### 4. GMM (Gaussian Mixture Model)

**What it does:** Fits K Gaussian components to feature vectors. Each component is a regime.
`predict_proba` gives soft membership.

**Strengths:** Simple, fast, well-understood. `sklearn.mixture.GaussianMixture`, MIT-adjacent.

**Weaknesses:**
- Purely static — no temporal state persistence. Each bar is classified independently.
  This causes high-frequency flickering in choppy markets.
- No transition dynamics — cannot distinguish "just entered a trend" from "stable trend."
- LSEG benchmark shows HMM outperforms GMM on out-of-sample data.

**When to use:** Acceptable fast fallback if HMM training fails. Run in parallel as a sanity check.

---

### 5. Tree-Based ML (XGBoost / LightGBM + SHAP) — Phase 2

**What it does:** Supervised classification on an engineered feature vector. Requires labeled
training data (regime labels). Labels are generated by running the HMM on historical data.

**Strengths:**
- When labels are available and features are well-engineered, routinely outperforms HMM.
- SHAP values provide per-bar feature importance — audit-friendly.
- Walk-forward CV with purged/embargo splits (López de Prado methodology) controls leakage.
- A 2026 regime-aware LightGBM study on NASDAQ-100 achieved Sharpe 1.18 in backtest.

**Weaknesses:**
- Label quality bootstraps from HMM — garbage in, garbage out.
- Overfit risk is high without strict walk-forward CV; k-fold on time series leaks future data.
- Requires ~1 year of labeled bars per instrument before useful; 2+ years is safer.

**Key warning from López de Prado:** Features may be important only in specific regimes —
fitting a single tree-based model ignores this; train regime-specific sub-models.

**Libraries:** `lightgbm >= 4.0` (BSD-3), `xgboost >= 2.0` (Apache-2.0), `shap >= 0.46`.

---

### 6. Change-Point Detection (ruptures library)

**What it does:** Detects *when* a structural break occurred, not *what* regime the market is in.
`ruptures.Pelt` (online-capable via C extension) is the standard implementation.

**Strengths:**
- Detects regime transitions faster than HMM in some configurations.
- Useful as a "regime change alert" to trigger model retraining.
- Kernel-CPD (C-accelerated) runs in ~5-50 ms on 500-bar windows.

**Weaknesses:**
- Does not classify *what* regime follows the break.
- Offline algorithms (Dynp) require the full window — cannot run incrementally per bar.
- `ruptures.Pelt` requires specifying a penalty parameter `pen` — sensitive to calibration.

**Library:** `ruptures >= 1.1.9` (BSD-2, High reputation on Context7, 276 code snippets).
API: `rpt.Pelt(model="rbf").fit(signal).predict(pen=3)`.

**When to use:** Supplementary — trigger model retraining when `ruptures` detects a structural
break, rather than doing monthly calendar-based retraining blindly.

---

### 7. Deep Learning (LSTM, Transformer) — Not Recommended as Primary

**Strengths:** Can capture complex non-linear patterns; Transformer attention is interpretable
in theory.

**Weaknesses:**
- At 2-5 year M15 data (~35,000-87,000 bars), overfitting is severe even with dropout.
- Inference (forward pass) can be <100ms on CPU, but model complexity dwarfs what is needed.
- Black-box output fails FTMO audit requirements.
- Training stability requires GPU infrastructure absent from the current stack.

**Verdict:** Do not use as primary. Revisit only if labeled dataset exceeds 10 years per
instrument and a GPU inference node is available.

---

## Recommended Feature Set

These features are confirmed in academic literature (Hurst exponent papers 2024, QuantInsti
regime-detection framework) and are computable from OHLCV bars already present in NautilusTrader:

| Feature | Computation | Regime signal |
|---|---|---|
| `adx_14` | ADX(14) — already in `src/indicators/adx.py` | Trend strength |
| `plus_di_14` | +DI(14) | Trend direction |
| `minus_di_14` | -DI(14) | Trend direction |
| `realized_vol_20` | `std(log(close/close[-1]), 20) * sqrt(periods_per_day)` | Volatility regime |
| `bb_width_pct_20` | `(BB_upper - BB_lower) / BB_mid`, rolling 100-bar percentile | Volatility percentile |
| `autocorr_lag1` | `pd.Series(returns).autocorr(lag=1)` over 50-bar window | Mean-reversion vs trend |
| `hurst_exp_50` | R/S analysis on 50-bar return window via `nolds.hurst_rs()` | Persistence: H>0.5 → trend, H<0.5 → MR |
| `ema_slope_50` | `(EMA(close, 50)[t] - EMA(close, 50)[t-10]) / EMA(close, 50)[t-10]` | Directional bias |
| `atr_ratio_14` | `ATR(14) / EMA(ATR(14), 100)` | Normalized volatility |

**Notes:**
- All features must be computed on a closed-bar-only window — never use the current
  in-progress bar. This prevents lookahead bias.
- Hurst exponent via `nolds >= 0.6.3` (released Nov 2025, actively maintained) — use
  `nolds.hurst_rs(return_series)`.
- HMM input: use all 9 features as a `(1, 9)` observation vector per bar.
- Normalize features to zero-mean unit-variance using a rolling scaler fitted on the
  training window only — never the full history.

---

## Recommended Regime Taxonomy

**Use 4 states**, consistent with academic literature (State Street Global Advisors 2025,
Imperial College London math-finance working paper, multiple MDPI 2024 papers):

| State ID | Label | Strategy candidates |
|---|---|---|
| 0 | `TRENDING_UP` | Supertrend, Donchian breakout, MA Crossover |
| 1 | `TRENDING_DOWN` | Supertrend (short), Donchian breakout (short), MA Crossover (short) |
| 2 | `RANGING` | RSI mean-reversion, Bollinger mean-reversion |
| 3 | `HIGH_VOLATILITY` | ORB (volatility expansion), or sit out with reduced size |

**HMM state-to-label mapping procedure (critical):**
After training, compute the average EMA slope and realized vol for bars belonging to each
state over the training window. Assign labels by: highest slope → TRENDING_UP,
lowest (most negative) slope → TRENDING_DOWN, lowest realized vol → RANGING,
highest realized vol → HIGH_VOLATILITY.

**Do not hardcode state-to-label mapping across retraining runs** — recompute after every
monthly refit.

---

## Implementation Roadmap

### Phase 1 — MVP (1-2 weeks)

1. Add `nolds >= 0.6.3` to `pyproject.toml`. Keep `hmmlearn >= 0.3` out of prod deps
   until Phase 1 complete; use `dev` optional group for training scripts.
2. Implement `RegimeFeatureExtractor` in
   `services/trading-engine/src/strategies/regime_features.py`:
   - Accepts a rolling `deque` of closed bars (max 200 bars).
   - Outputs a frozen dataclass `RegimeFeatures` with the 9 features above.
   - Fully incremental — O(1) update per bar (no recompute of full window except
     Hurst/autocorr, which use a fixed 50-bar window).
3. Implement `RuleBasedRegimeClassifier` in
   `services/trading-engine/src/strategies/regime_classifier.py`:
   - Uses ADX, `plus_di`, `minus_di`, `bb_width_pct_20`, `realized_vol_20`.
   - Returns `RegimeState` enum + `RegimeDecision` frozen dataclass with all feature values
     for FTMO audit logging.
   - Load thresholds from `configs/ftmo-presets.yaml` — never hardcode.
4. Wire classifier into `StrategyDataRouter.route_bar()`: on each bar, classify regime,
   then route bar only to strategies registered for that regime state.
5. Write 80%+ unit tests — include edge cases: insufficient bars (< warmup), all-same
   close prices (zero vol), zero ATR.

### Phase 2 — HMM Integration (3-4 weeks after Phase 1 ships)

1. Add `hmmlearn >= 0.3` to production deps.
2. Create offline training script `scripts/train_regime_hmm.py`:
   - Walk-forward: train on rolling 2-year window, evaluate on next 3 months.
   - Multiple restarts (n_init=10) to escape local optima.
   - Serialize model with `joblib` + metadata: training date range, instrument,
     feature scaler params, state-to-label mapping.
3. Implement `HMMRegimeClassifier` (same interface as `RuleBasedRegimeClassifier`):
   - Load pre-trained model from `configs/hmm_models/{instrument}.pkl`.
   - Call `model.predict_proba([features])` → confidence vector.
   - If `max(proba) < 0.6` → fall back to rule-based classifier.
   - Log state, proba, and all features to `rule_check_log` hypertable.
4. Monthly retraining job (cron / NautilusTrader actor timer):
   - Trigger retraining when `ruptures.Pelt` detects structural break OR monthly calendar.
   - Atomic swap of model file — never hot-swap mid-session.

### Phase 3 — XGBoost Refinement (after 6 months of HMM-labeled production data)

1. Export HMM-generated labels for all historical bars.
2. Train per-instrument XGBoost classifiers with purged walk-forward CV (López de Prado).
3. Use SHAP values per bar — log top-3 feature importances to `rule_check_log` for FTMO.
4. A/B shadow-run XGBoost vs HMM for 1 month before cutover.

---

## Reference Implementations

| Repo | Stars | Last activity | Relevance | License |
|---|---|---|---|---|
| [hmmlearn/hmmlearn](https://github.com/hmmlearn/hmmlearn) | ~3k | Active 2025 | Primary HMM library — GaussianHMM API | BSD-3 |
| [Yizhan-Oliver-Shu/jump-models](https://github.com/Yizhan-Oliver-Shu/jump-models) | 146 | 2024 | Statistical Jump Model, Phase 2 alternative | MIT |
| [deepcharles/ruptures](https://github.com/deepcharles/ruptures) | ~1.5k | Active 2025 | Change-point detection for retraining trigger | BSD-2 |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | ~16k | Active 2024 | Chapter 9: HMM regime detection + RF specialist | Apache-2.0 |
| [LSEG-API-Samples/Article.RD.Python.MarketRegimeDetectionUsingStatisticalAndMLBasedApproaches](https://github.com/LSEG-API-Samples/Article.RD.Python.MarketRegimeDetectionUsingStatisticalAndMLBasedApproaches) | ~50 | 2024 | HMM vs GMM vs clustering benchmark code | Apache-2.0 |

**Note on stars < 500 threshold:** `jump-models` (146 stars) is included because it is backed
by three peer-reviewed 2024 papers and has a scikit-learn-compatible API. It is Phase 2 only.
`hmmlearn` and `ruptures` both clear the 1k+ star bar.

---

## Library Inventory

Add to `services/trading-engine/pyproject.toml`:

```toml
# Phase 1
"nolds>=0.6.3",          # Hurst exponent, actively maintained Nov 2025

# Phase 2 (add to prod deps when HMM integration is ready)
"hmmlearn>=0.3.0",       # GaussianHMM, BSD-3, scikit-learn API
"joblib>=1.4",           # Model serialization (already transitively present via sklearn)
"ruptures>=1.1.9",       # Change-point detection, retraining trigger

# Phase 3 (add when XGBoost refinement begins)
"lightgbm>=4.5",         # Regime classifier, faster than XGBoost
"shap>=0.46",            # SHAP audit trail per bar
```

**Note:** `scikit-learn`, `pandas`, `numpy` are already in project deps.

---

## Pitfalls to Avoid

1. **Lookahead bias in feature engineering.** Rolling Hurst exponent computed with `t=0`
   as the last data point is correct. Never use `pd.rolling(...).apply(func)` without
   verifying `center=False` (the default) — `center=True` leaks future values.

2. **Lookahead in regime labeling for supervised training.** If you label regimes using
   the final realized outcome (e.g., "this was a trend because price went up 2%"), you
   are using future information. Label only from contemporaneous indicators.

3. **HMM state label flipping across retraining.** State 0 in January's model can mean
   the opposite of state 0 in February's model. Always re-derive state-to-label mapping
   post-training via feature statistics, not by assuming state ID is stable.

4. **Standard k-fold cross-validation on time series.** It randomly mixes past and future
   data. Use walk-forward (purged + embargo) CV only. López de Prado's purged CV removes
   observations within an embargo window around each test point to prevent leakage from
   overlapping labels.

5. **Hardcoding regime thresholds.** FTMO compliance rule: all numeric thresholds must
   load from `configs/ftmo-presets.yaml`. A compliance audit that finds `ADX > 25`
   in source code is a violation of the domain rules.

6. **Training HMM on single initialization.** EM for HMM has multiple local optima. Always
   run with `n_init >= 5` and select the model with highest log-likelihood on a held-out
   validation window.

7. **Routing all accounts to the new regime router simultaneously.** Roll out per-account.
   Keep the current `StrategyDataRouter` (symbol-based filter) as the outer layer; the
   regime router is a second filter layer inside.

8. **Inferring regime mid-bar (tick data).** Classify regime only on `on_bar()` — i.e.,
   on closed bars. Never update regime state from tick-level data; the bar boundary is the
   synchronization point.

9. **Not logging regime decisions to `rule_check_log`.** Every regime classification must
   be written to the TimescaleDB audit table before the routing decision is executed —
   same pattern as FTMO rule checks (write audit first, act second).

10. **Over-partitioning into 5+ regimes.** Literature supports 4 states as optimal for
    practical portfolio management. More states → sparser training data per state →
    more fragile emission models. Start at 4.

---

## Existing Project Code

| Path | Relevance |
|---|---|
| `src/strategies/data_router.py` | Current symbol-based router — regime router plugs in here |
| `src/indicators/adx.py` | Full ADX + DI implementation — reuse directly for rule-based classifier |
| `src/indicators/supertrend.py` | Contains ATR logic useful for `atr_ratio_14` feature |
| `src/strategies/registry.py` | Strategy registry — extend to map strategy → regime state |
| `src/backtesting/synthetic_bars.py` | Contains "trending/ranging" synthetic bar generation — useful for unit test fixtures |

No existing regime classifier or Hurst exponent implementation found in the codebase.

---

## Open Questions (need user decision)

1. **Per-instrument models vs shared model?** XAUUSD and EURUSD have structurally different
   volatility profiles. Recommended: one HMM model per instrument-timeframe pair. But this
   doubles training and maintenance burden. Confirm scope.

2. **What to do in HIGH_VOLATILITY regime?** Three options: (a) route to ORB, (b) reduce
   position size on all strategies, (c) go flat (no new entries). Each has different FTMO
   daily-loss implications. User decision required before implementing routing logic.

3. **Regime transition hysteresis.** Should the router require 2 consecutive bars in the
   new regime before switching? This prevents flickering but adds 1-bar lag. Tradeoff is
   user preference.

4. **Monthly retraining schedule.** Is a cron job (external to NautilusTrader) acceptable,
   or does retraining need to happen inside a NautilusTrader Actor? The latter is cleaner
   but more complex.

5. **Minimum bar count before HMM activates.** HMM needs ~500 bars to be reliable
   (~3 months M5 or ~12 months M15). What is the fallback during cold start — rule-based
   only, or suspend routing entirely?

---

## Sources

- [hmmlearn documentation](https://github.com/hmmlearn/hmmlearn) — Context7 `/hmmlearn/hmmlearn`
- [ruptures documentation](https://github.com/deepcharles/ruptures) — Context7 `/deepcharles/ruptures`
- [jump-models GitHub](https://github.com/Yizhan-Oliver-Shu/jump-models) — 146 stars, MIT, 2024
- [Shu & Mulvey 2024 — Downside Risk Reduction Using Regime-Switching Signals](https://arxiv.org/abs/2402.05272)
- [LSEG — Market Regime Detection Using Statistical and ML Based Approaches](https://developers.lseg.com/en/article-catalog/article/market-regime-detection)
- [QuantInsti — Regime-Specific Trading with HMM and Random Forest](https://blog.quantinsti.com/regime-adaptive-trading-python/)
- [Regime-Aware LightGBM Framework, MDPI Electronics 2025](https://www.mdpi.com/2079-9292/15/6/1334)
- [State Street Global Advisors — Decoding Market Regimes with ML, 2025](https://www.ssga.com/library-content/assets/pdf/global/pc/2025/decoding-market-regimes-with-machine-learning.pdf)
- [nolds PyPI — Hurst exponent, last release Nov 2025](https://pypi.org/project/nolds/)
- [Hurst Exponent Applications from Regime Analysis, Harbourfront 2024](https://blog.harbourfronts.com/2024/12/01/hurst-exponent-applications-from-regime-analysis-to-arbitrage/)
- [López de Prado, Advances in Financial Machine Learning — purged CV, feature importance](https://www.amazon.com/Advances-Financial-Machine-Learning-Marcos/dp/1119482089)
- [A forest of opinions: ensemble-HMM voting for regime detection, 2025](https://www.aimspress.com/article/id/69045d2fba35de34708adb5d)
- [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading)
