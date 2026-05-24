---
name: meta-labeling
description: Meta-labeling / Corrective-AI patterns for the Sandboxed signal-quality work — triple-barrier labeling, time-series-correct data prep (purged/embargoed CV, no-shuffle, no-scale), LightGBM + calibration, and the MetaLabelGate integration seam. Use when building or reviewing the ML layer that gates primary-strategy trades. Knowledge prep for the future meta-label epic (defer-created after Epic 15 + 16).
origin: Sandboxed
---

# Meta-Labeling / Corrective AI

Patterns for the secondary ML layer that decides **take/skip + size** of a primary
strategy's candidate trades (López de Prado "meta-labeling"; Predictnow.ai "Corrective AI").
The primary strategy (Supertrend, Donchian, …) decides the **side**; the model learns the
**Probability-of-Profit (PoP)** and gates on it. It only ever *removes* trades — FTMO-friendly.

> Full background: `docs/research/meta-labeling-corrective-ai.md` (technique + libs + seam),
> `docs/research/ml-data-prep-and-training.md` (data-prep + training methodology). This skill is
> the actionable condensation. Knowledge prep — the meta-label epic is created only after Epic 15
> (RegimeActor feature stream) + Epic 16 (data) complete.

## When to activate

- Building/reviewing the meta-label model: feature matrix → labels → train → gate.
- Any supervised ML on backtest trade history in this repo.
- Reviewing for the classic time-series ML traps (leakage, look-ahead, wrong metric).

## The 8 non-negotiable rules (time-series + FTMO)

These are where generic-ML tutorials (incl. the book's Ch.4) go **wrong** for finance. Enforce them.

| # | Rule | Why |
|---|---|---|
| 1 | **No `shuffle=True`, no random k-fold.** Use chronological holdout + **purged + embargoed CV**. | Shuffling/ random folds train on the future, test on the past → look-ahead leakage. Overlapping triple-barrier labels leak across adjacent rows. |
| 2 | **Fit scaler/imputer inside the CV fold only** — better, **no scaler at all** (LightGBM is scale-invariant). | Fitting on full data before split leaks test statistics into train. |
| 3 | **Don't impute missing feature rows — drop them.** | A missing regime = "no confirmed regime" (information), not a value to fill. |
| 4 | **Don't globally remove "outlier" bars.** | A vol spike is often the signal; let the `HIGH_VOLATILITY` regime gate it; handle bad ticks at the data layer (Epic 16). |
| 5 | **Evaluate by OOS PSR + Sharpe uplift, never accuracy.** | In-sample accuracy is meaningless for trading; accuracy≈1.0 ⇒ overfit. |
| 6 | **Never feed raw price levels** (non-stationary). | Use `RegimeFeatures` (already stationary by design); fractional-diff (López de Prado) if a level is ever needed. |
| 7 | **Keep the feature set small + interpretable; skip PCA at ~8 features.** | Small trade counts punish dimensionality; FTMO audit needs explainability. |
| 8 | **The gate may only SKIP entries, never add or block exits.** | `_close_position`/scale-out must always run (close risk in HIGH_VOL); gate sits at entry-only seams. |

## Libraries (licence-vetted, see research doc)

```bash
uv add "lightgbm>=4.0" "scikit-learn>=1.4" "mlfinpy>=0.1.2" "skfolio>=0.20"
```
- `mlfinpy` (MIT) — triple-barrier labels. `skfolio` (BSD-3) — `CombinatorialPurgedCV`.
- `lightgbm` + `sklearn` — the classifier + `CalibratedClassifierCV`. **Avoid** `mlfinlab` (commercial).

## Labeling — triple-barrier from backtest trades

Canonical label = trade outcome (`pnl > 0`), fee-inclusive, from `BacktestResult.trades`:

```python
def label_trades(trades: list[TradeRecord]) -> list[int]:
    # 1 = the primary strategy's trade was profitable; 0 = not. pnl already
    # encodes side + fees, so this is the unambiguous meta-label target.
    return [1 if t.pnl > 0 else 0 for t in trades]
```
(`mlfinpy.get_bins()` only as a cross-check — don't re-simulate barriers.)

## Feature matrix

From the `RegimeActor` feature stream (Epic 15 `feature_recorder`) at each trade's `entry_ts`,
**never recomputed** (avoids look-ahead). Columns (stable order — train ≡ inference):

```python
FEATURE_COLUMNS = [
    "adx", "plus_di", "minus_di", "bb_width_pct", "realized_vol", "ema_slope",
    "hour_of_day", "day_of_week",
]
```
Prune correlated pairs (ADX↔±DI, bb_width↔realized_vol) via a |corr|>0.9 check; confirm with
LightGBM `feature_importances_`; drop dead features.

## Train + calibrate + validate

```python
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from skfolio.model_selection import CombinatorialPurgedCV

clf = CalibratedClassifierCV(
    LGBMClassifier(num_leaves=8, min_child_samples=30,
                   class_weight="balanced", n_estimators=300),
    method="isotonic",
)
# CV groups by the label's exit_ts so overlapping labels are PURGED + embargoed.
cv = CombinatorialPurgedCV(...)  # groups=label_end_times
# Report OOS PSR + Sharpe uplift on surviving trades — NOT accuracy.
```
Sample-size floor: < ~400 labeled trades total (or <150/fold) ⇒ unreliable. Pool symbols
(XAUUSD+EURUSD+…) to clear it before trusting the model.

## Integration seam (the gate)

The successor to the (removed) `RegimeAwareRouter` seam: gate lives in `BaseStrategy` at the
**entry-only** order seam, composing with the regime allow-list:

```python
def _admit_entry(self, signal, features) -> bool:
    if not self._regime_admits(signal):      # regime allow-list + HIGH_VOL kill-switch
        return False
    if self._meta_gate is not None and not self._meta_gate.should_take(features, signal):
        return False                         # meta-label PoP < threshold (e.g. 0.55)
    return True
```
`MetaLabelModel.predict_pop(features)` reads the **same** `RegimeFeatures` the actor published
(no recompute). Synchronous, <0.3ms. Default-off (no model ⇒ no gate).

## Spike acceptance (go/no-go)

OOS Sharpe(gated) > ungated in ≥3/5 folds · OOS **PSR > 0.90** · MaxDD not worse · trade-count
reduction < 50%. Kill if sample floor unmet or PSR ≤ 0.90.

## Out of scope / deferred
Model registry, retraining cadence, drift monitoring, continuous PoP→size sigmoid sizing,
deep learning (CNN/Chronos — data-hungry, black-box, fails the explainability/sample bar).

## References
- `docs/research/meta-labeling-corrective-ai.md`, `docs/research/ml-data-prep-and-training.md`
- López de Prado, *Advances in Financial Machine Learning* (2018) — ch.3 (labeling/meta-labeling, purged CV), pp.79-84 (fractional differentiation)
- Companion epics: `docs/epic-15-context.md` (feature stream), `docs/epic-16-context.md` (data)
