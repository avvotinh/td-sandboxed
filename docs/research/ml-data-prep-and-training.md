# Research: ML Data Preparation & Model Training — distilled for our pipeline

**Date:** 2026-05-24
**Source:** *Hands-On AI Trading with Python* — Part II (Ch.3 Problem Definition, Ch.4
Dataset Preparation, Ch.5 Model Choice/Training/Application), plus the López de Prado
references the book builds on.
**Companions:** `docs/research/meta-labeling-corrective-ai.md` (the technique), `docs/epic-15-context.md`
(the `RegimeActor` that will emit the feature stream), `docs/epic-16-context.md` (the OANDA data being fetched).
**Purpose:** turn the book's generic ML pipeline into an actionable, *time-series-correct* recipe for
our meta-labeling / signal-quality work. The book is QuantConnect-flavoured and, in places,
**generic-ML-correct but time-series-WRONG** — those traps are the highest-value content here.

---

## Tóm tắt Tiếng Việt (Executive Summary)

Sách trình bày pipeline ML 3 bước: (1) định nghĩa bài toán, (2) **chuẩn bị dataset**, (3) **chọn +
train model**. Phần "chuẩn bị data" (Ch.4) gồm: xử lý missing (drop / impute mean·KNN·MICE), outlier
(z-score / IQR → remove·log·cap), **stationarity** (ADF test + differencing; finance dùng **fractional
differentiation của López de Prado** để giữ memory), feature selection (correlation > 0.9 thì prune,
RF feature-importance, RFE, PCA), và **chia train/test/val**.

⚠️ **Bẫy lớn nhất:** mục splitting của Ch.4 dùng `train_test_split(shuffle=True)` + **k-fold thường** —
**LEAK tương lai vào quá khứ** với dữ liệu time-series. Hệ thống mình **KHÔNG được** dùng cách này;
phải dùng **purged + embargoed walk-forward CV** (đã chốt `skfolio.CombinatorialPurgedCV` trong doc
meta-labeling). Sách chỉ nói purged CV ở chương López de Prado, không nói ở mục splitting cơ bản.

Hai điểm thuận lợi cho mình: (a) meta-model dùng **LightGBM (cây)** → **không cần normalize/standardize**
(sách xác nhận tree-based "not required"); (b) **RegimeFeatures của Epic 11 hầu hết đã stationary** sẵn
(ADX, BB-width percentile, realized vol, EMA slope là oscillator/percentile/đạo hàm) — **tuyệt đối không
feed giá thô** (non-stationary). Đánh giá model dùng **PSR / Sharpe uplift**, KHÔNG dùng accuracy (sách
cũng cảnh báo accuracy train-test = 1.0 là dấu hiệu overfit).

---

## 0. The book's 3-step ML pipeline (Ch.3–5) mapped to us

| Book step | Book content | Our mapping |
|---|---|---|
| **1. Problem Definition** (Ch.3) | What to predict, horizon, label | Meta-label: predict **Probability-of-Profit** of a primary strategy's candidate trade (take/skip). Side from strategy; size/skip from the model. |
| **2. Dataset Preparation** (Ch.4) | Collect → EDA → clean → stationarity → feature-select → split | Source = Epic 16 OANDA bars; features = Epic 15 `RegimeActor`'s `RegimeFeatures` per bar + time-of-day; labels = triple-barrier on backtest `TradeRecord`s. |
| **3. Model Choice + Training** (Ch.5) | Regression / classification / clustering / LLM catalog | Binary **classification** → LightGBM + isotonic calibration (per meta-label doc). |

---

## Part A — Data Preparation (Chapter 4), step-by-step, with our adaptation

### A1. Data Collection & EDA
- **Book:** gather price/volume + macro/alt data from reliable providers; EDA via pandas + Sweetviz
  (`sv.analyze`, `compare_intra`) for automated profiling.
- **For us:** data is Epic 16 OANDA M5/M15/H1/H4 Parquet (already fingerprinted + gap-audited). EDA is
  cheap and worth doing once on the assembled feature matrix (Sweetviz HTML, or `df.describe()` +
  correlation heatmap) to eyeball feature distributions and class balance before training. No alt/macro
  data this round (spread/news deferred — meta-label doc R5).

### A2. Handling missing data
- **Book:** identify (`df.isnull().sum()`); then **remove** (`dropna`) or **impute** —
  mean/median (`SimpleImputer`), **KNN** (`KNNImputer`), or **MICE** (`IterativeImputer`).
- **For us:** mostly **non-issue by construction**. `FeatureExtractor` (`regime/features.py`) emits
  `None` during warmup (those bars are simply absent from the training set, not NaN) and
  `RegimeFeatures.__post_init__` **rejects NaN at construction** — so a feature row either exists clean
  or doesn't exist. Do **not** impute feature rows: a missing regime is "no confirmed regime," which is
  information, not a value to fill. Only place imputation could appear is if we later join external data
  (macro/spread) — then forward-fill point-in-time (never backfill → look-ahead).

### A3. Handling outliers
- **Book:** detect via box-plot / **z-score (>|2| or |3|)** / **IQR (1.5×)**; handle by **remove**,
  **log-transform**, or **cap/floor**.
- **For us:** be careful — in trading, an "outlier" bar (flash spike, FOMC) is often the *signal*, not
  noise. Two stances:
  - Feature outliers (e.g. a realized-vol spike): **do not remove the row** — that's exactly when the
    `HIGH_VOLATILITY` regime kill-switch should fire. Optionally **cap** extreme feature values to keep a
    tree split from over-weighting one bar, but tree models are robust to monotone outliers anyway.
  - Price-bar outliers (bad ticks): handle at the **data layer** (Epic 16 gap/quality gate 16.7), not in
    the feature pipeline. Log-transform of price is moot for us — we never feed raw price (see A6).

### A4. Feature engineering
- **Book:** create new features (rolling MAs, interaction terms) that better represent the problem.
- **For us:** the feature set is *already engineered* — `RegimeFeatures` (ADX, +DI/−DI, BB-width pct,
  realized vol, EMA slope) are domain indicators. Additions for meta-labeling: **time-of-day**,
  **day-of-week** (session/seasonality — cheap, the book's EURUSD Corrective-AI example exploits exactly
  intraday seasonality), and later **regime state** itself (categorical) + **bars-in-regime**. Keep the
  set small (~8) — small trade counts (meta-label doc R2) punish high dimensionality.

### A5. Normalization vs Standardization — and what OUR model needs
- **Book:** Normalization = min-max → [0,1] (good for NN/KNN, no distribution assumption);
  Standardization = z-score, mean 0 / std 1 (essential for **SVM, LASSO/Ridge, PCA, logistic, NN**;
  Ch.5 marks "Required" per model). Fit the scaler on **train only**, then transform test (the book is
  sloppy here — see A8 trap).
- **For us:** the chosen meta-model is **LightGBM (gradient-boosted trees)**. The book's Ch.5 explicitly
  marks tree/RF models **"Normalization/Standardization: Not required"** — splits are scale-invariant.
  **So we skip scaling entirely for the meta-model.** This removes a whole class of train/test-leakage
  bugs (scaler fit on full data). If we ever try logistic/SVM as a baseline, standardize **inside the CV
  fold** (fit on fold-train only).

### A6. Stationarity — the time-series core (and where our feature design pays off)
- **Book:** non-stationary series break ML pattern-finding. Test with **ADF** (`adfuller`; stat < critical
  ⇒ reject unit root ⇒ stationary). Achieve via **differencing / detrending / log**. **In finance, use
  López de Prado's fractional differentiation** (FFD, `get_weights_ffd` / `frac_diff_ffd`) to make a
  series stationary *while preserving memory* — integer differencing (returns) destroys long-memory
  signal; fractional `d∈(0,1)` keeps it.
- **For us — audit each feature:**
  | Feature | Stationary? | Action |
  |---|---|---|
  | ADX, ±DI | Yes (bounded 0–100) | use as-is |
  | BB-width **percentile** | Yes (percentile rank) | use as-is |
  | realized vol | ~stationary (bounded, mean-reverting) | use as-is |
  | EMA **slope** | ~stationary (a derivative, not a level) | use as-is; sanity-check ADF on the assembled column |
  | raw price / EMA level | **NO — non-stationary** | **never feed**; if ever needed, use returns or FFD |
  - **Takeaway:** Epic 11's feature design is already mostly stationary by construction (oscillators /
    percentiles / slopes). This is a real advantage — we sidestep most of the book's stationarity work.
    The one rule to enforce: **no raw price levels as features.** If a future feature is a price level,
    run ADF and apply FFD (`d` tuned to the smallest value that passes ADF) rather than plain returns.

### A7. Feature selection (for a small, correlated set)
- **Book:** (1) **correlation analysis** — drop features with |corr| > 0.9 to each other; (2) **RF feature
  importance**; (3) **RFE** (recursive elimination, after de-correlating); (4) **PCA** (standardize first;
  keep top-K components ~90% variance).
- **For us:** with ~8 features, do the cheap, interpretable ones:
  - **Correlation prune:** ADX vs ±DI, and BB-width vs realized-vol, are likely correlated — drop the
    redundant one (keep the more interpretable / less noisy).
  - **RF/LightGBM importance:** read `feature_importances_` after a first fit to see what carries signal;
    drop near-zero contributors (the book's example drops a 1.5%-importance feature).
  - **Skip PCA:** at ~8 features PCA buys little and destroys interpretability (and we want explainability
    for FTMO audit — the book's Corrective-AI chapter stresses explainability over deep black boxes).

### A8. ⚠️ Splitting — THE trap; do NOT follow Ch.4 verbatim
- **Book (Ch.4):** `train_test_split(..., shuffle=True)` (default) at 70–80/20–30, optional 60/20/20
  with a validation set; for robustness use **k-fold cross-validation** (`cross_val_score`, random folds).
  It even notes a perfect train-test accuracy "indicates potential overfitting."
- **The trap:** `shuffle=True` and random k-fold **randomly mix bars across time**, so the model trains on
  future bars and tests on past ones → **look-ahead leakage**. Worse, overlapping labels (triple-barrier
  windows that span multiple bars) leak a test label's outcome into adjacent training rows. The book
  presents this generic-ML splitting **without the time-series caveat** in Ch.4 (it only introduces
  purged CV later, in the López-de-Prado-based meta-labeling / CPO material).
- **For us (mandatory):**
  - **Chronological split only** for the holdout (train = earlier window, test = later). Our Epic 16
    datasets already define `in_sample` (train) + held-out `oos_reserve` (final check).
  - **Purged + embargoed CV** for model selection — `skfolio.model_selection.CombinatorialPurgedCV`
    (meta-label doc), grouping by the label's `exit_ts` so overlapping-label leakage is purged and an
    embargo gap separates train/test folds. This *replaces* the book's k-fold.
  - **Never `shuffle=True`** on bar/feature data. **Never** fit a scaler/imputer on the full dataset
    before splitting (fit inside the fold).

---

## Part B — Model Choice & Training (Chapter 5)

### B1. Taxonomy (Ch.5 intro)
- **Supervised** (labeled): regression (continuous) + classification (labels). Algos: linear/poly/LASSO/
  Ridge regression, decision tree, SVM, logistic, random forest, Gaussian NB, CNN.
- **Unsupervised** (unlabeled): clustering (k-means, OPTICS) + dimensionality reduction (PCA).
- **Semi-supervised:** LLMs (FinBERT, OpenAI, Chronos).
- **Reinforcement learning:** separate paradigm (book Ch.7 hedging) — *out of scope for us* (the regime
  doc already rejected RL: non-deterministic, fails FTMO audit/consistency).

### B2. The book's per-model template
Each model is presented as: **Description / Key Use Cases in Finance / Normalization-Standardization
Required / Python libs / worked example / performance**. Useful as a lookup for "does this model need
scaling" and "what's it good for."

### B3. Which models map to meta-labeling (our classification task)
- **Random Forest / gradient-boosted trees** (Ch.5 "Multiclass Random Forest", uses `lightgbm`): ensemble
  (bagging/boosting/stacking), robust to outliers, **no scaling needed**, gives feature importance,
  explainable. → **our choice (LightGBM)**, matching the meta-label doc.
- **Logistic regression:** classic Probability-of-Profit baseline; needs standardization; very
  interpretable. Good sanity-check baseline.
- **Gaussian Naive Bayes / CNN:** book covers them; CNN (pattern/“head-shoulders”) is overkill + data-
  hungry for our small sample — defer.
- **HMM / Markov-switching:** book uses these for **regime detection** (Ch.6 Ex.4) — relevant to a
  *future* upgrade of our rule-based classifier (Epic 11 Phase 2), **not** the meta-label model.

### B4. Training discipline (synthesis with the book's overfitting warnings)
- Aggressive regularization on small samples (LightGBM `num_leaves` small, `min_child_samples` high,
  `class_weight="balanced"`) — meta-label doc.
- **Calibrate** probabilities (`CalibratedClassifierCV`, isotonic) so the PoP threshold (0.55) is
  meaningful.
- **Evaluate with PSR / Sharpe uplift on OOS folds, not accuracy.** The book itself flags accuracy=1.0 as
  an overfit smell; for trading, in-sample accuracy is nearly meaningless — the gate is out-of-sample
  risk-adjusted return (meta-label doc decision criteria).

---

## Part C — Consolidated traps & corrections (the value-add)

| # | Book (generic) | Our correction (time-series / FTMO) |
|---|---|---|
| C1 | `train_test_split(shuffle=True)` + random k-fold | **Chronological holdout + purged/embargoed CV** (skfolio); never shuffle bars |
| C2 | Fit scaler/imputer, then split | Fit **inside the fold**, train-only; better yet, **no scaler** (LightGBM) |
| C3 | Impute missing feature rows | Don't — a missing regime = "no confirmed regime" (info); drop, don't fill |
| C4 | Remove/transform outliers globally | Outlier bars are often the signal; handle bad ticks at data layer, let HIGH_VOLATILITY regime gate the rest |
| C5 | Accuracy as the metric | **PSR / Sharpe uplift OOS**; accuracy=1.0 ⇒ overfit |
| C6 | Feed prices / raw levels | **Never** — non-stationary; use stationary `RegimeFeatures`, FFD if a level is ever needed |
| C7 | PCA to reduce dims | Skip at ~8 features; keep interpretability for FTMO audit |
| C8 | Deep learning (CNN/Chronos) | Defer — data-hungry, black-box, fails the explainability/sample-size bar |

---

## Part D — Concrete checklist for the meta-label data pipeline (when we build it)

1. **Assemble feature matrix** from `RegimeActor` per-bar features (Epic 15 `feature_recorder`) + time-of-
   day/day-of-week, keyed by bar `ts` — recorded natively in backtest (no recompute, no look-ahead).
2. **Label** via triple-barrier on backtest `TradeRecord`s (`pnl > 0` canonical; meta-label doc).
3. **EDA once**: distributions + class balance + correlation heatmap; prune |corr|>0.9.
4. **No scaling** (LightGBM); **no imputation** (drop incomplete rows); **no shuffle**.
5. **Stationarity sanity**: ADF on each assembled feature column; confirm all pass (they should by design);
   FFD any that don't.
6. **Split**: `in_sample` for purged/embargoed CV model-selection; `oos_reserve` touched **once** at the end.
7. **Train** LightGBM + isotonic calibration, regularized; read feature importance, drop dead features.
8. **Evaluate** OOS by **PSR + Sharpe uplift vs ungated**, trade-count floor, max-DD not worsened
   (meta-label doc go/no-go).

---

## Sources
- *Hands-On AI Trading with Python*, Ch.3 (p.95–98), Ch.4 (p.99–148: collection/EDA/missing/outliers/
  feature-eng/normalization/standardization/stationarity/feature-selection/splitting), Ch.5 (p.149–227:
  model catalog incl. classification & clustering).
- M. López de Prado, *Advances in Financial Machine Learning* (2018) — fractional differentiation
  (pp.79–84), purged/embargoed CV, triple-barrier & meta-labeling (referenced throughout the book).
- Cross-refs: `docs/research/meta-labeling-corrective-ai.md`, `docs/epic-15-context.md`, `docs/epic-16-context.md`.
