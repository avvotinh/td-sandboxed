# Epic 17: Meta-Labeling / Signal-Quality Gate — Technical Context

**Created:** 2026-06-04
**Last updated:** 2026-06-04
**Status:** **Contexted** — 18 stories drafted, not started
**Epic:** 17 of 17+
**Stories:** 18 (17.1 – 17.16, with 17.13 split into a/b/c) across 5 phases (P0–P4)
**Predecessor (regime infra):** Epic 15 (RegimeActor Backtest-Live Parity) — closed 2026-05-28
**Predecessor (data):** Epic 16 (Historical Data Acquisition) — closed 2026-05-24
**Source research:** `docs/research/meta-labeling-corrective-ai.md` (methodology) + `docs/research/ml-data-prep-and-training.md` (time-series CV / no-shuffle / no-scale rules)
**Branch:** (to be created) `feat/epic-17-meta-labeling`

> **Numbering note:** This is **Epic 17**. **Epic 14 remains reserved for the mt5-bridge EA / ZMQ
> work**; Epic 15 = RegimeActor parity; Epic 16 = data acquisition. Epic 17 is the
> meta-labeling / signal-quality gate that was deliberately deferred until 15+16 closed (per
> `[[epic-structure-ml-sequencing]]` memory and the spike note in `epic-15-context.md` §"Out of
> Scope"). 15+16 done ⇒ 17 unblocked.

---

## Overview

### Problem Statement

Epic 15 closed the regime-gating gap: `RegimeActor.on_bar`
(`services/trading-engine/src/regime/actor.py`) publishes a `RegimeSnapshot` per `BarType` to a
shared `RegimeStateStore` (`services/trading-engine/src/regime/state_store.py`), and every
strategy self-suppresses entries through `BaseStrategy._regime_admits` wired into
`_go_long` / `_go_short`. The same store runs byte-identically in backtest and live. **What it
does not do is improve signal quality** — it can only reject a bar because of a coarse regime
label, not because the *specific candidate trade* has a low expected value.

That gap is the binding constraint on engine profitability. Six strategies are shipped, but
Phase 12.B (parameter sweep, story 12.7b) is **gated** because none clears the Sharpe ≥ 0.8
filter on default parameters (Epic 13 retrospective + `epic-12-baseline-comparison.md`).
Hyperparameter tuning shifts Sharpe by small amounts; the meta-labeling research
(`meta-labeling-corrective-ai.md` §6) and data-prep research (`ml-data-prep-and-training.md`
Part D) show **meta-labeling can lift OOS Sharpe by 0.3+ without adding a single trade** — it
only learns to *skip* trades the primary strategy would have taken with the lowest
probability of profit. For a prop-firm engine "remove marginal losers" is the right shape
of intervention: strictly reduces daily-loss exposure + max-DD surface, composes additively
with FTMO's hard kill-switches.

Meta-labeling is the right approach (vs. replacing strategies, vs. an RL allocator, vs. a
generative side-predictor) because (1) the existing six rule-based strategies are
**explainable and auditable** — required by FTMO — and meta-labeling keeps the *side*
decision in rule code; (2) the secondary model learns only a **binary calibrated probability**
over an already-engineered, mostly-stationary feature vector (the same `RegimeFeatures` Epic 15
publishes), so the data-prep traps (no shuffle, no scaler-leak, no raw price) are sidestepped by
construction; (3) the integration seam already exists — `_regime_admits` is the exact shape
(`signal → bool`) that `_meta_label_admits` slots next to. The forward-compat `features` field
on `RegimeSnapshot` (`state_store.py`) was carved out in Epic 15 explicitly for this epic.

### Solution

Epic 17 adds a **second admission gate** at the entry-only seam that consumes the *same*
feature vector the regime decision was made on, scores it through a calibrated LightGBM
classifier, and returns `bool` (binary gate, v1). Semantically identical to `_regime_admits` ⇒
inherits all its safety invariants (entry-only, exits never gated, default-OFF parity). The
training pipeline is **offline tooling** under `services/trading-engine/scripts/`; the
inference gate is the only thing that runs in the engine. Backtest and live consume the same
artifact via the same code path — preserving Backtest-Reality Alignment.

```
OFFLINE (tooling — per (firm, strategy, symbol) on a cadence)
─────────────────────────────────────────────────────────────
[OANDA Parquet, Epic 16]    [BacktestRunner, Epic 15+]
        │                            │
        ▼                            ▼
  bar replay  ───► RegimeActor.on_bar ──► RegimeStateStore.publish ──► on_publish hook
                                                                              │
  BacktestResult.trades ─────────────────────────────────────────────► triple-barrier labeller
                                                                              │       │
                                                                              ▼       ▼
                                                                       features.parquet | labels.parquet
                                                                              │
                                                                              ▼
                              CombinatorialPurgedCV(groups=exit_ts) + CalibratedClassifierCV(LGBM, isotonic)
                                                                              │
                                                                              ▼
                                                  models/meta_label/{firm}_{strategy}_{symbol}_vN.joblib (+ .json sidecar)

ONLINE (engine — same code in backtest + live)
─────────────────────────────────────────────
Bar ─► RegimeActor.on_bar ─► RegimeStateStore.publish(snapshot)
   ─► Strategy.on_bar ─► generate_signal ─► _go_long / _go_short
                            └► _regime_admits(signal)        ◄── allow-list + kill-switch
                            └► _meta_label_admits(signal)    ◄── MetaLabelGate(snapshot.features) → bool
                            └► submit bracket ONLY if both admit
                            └► audit kind=meta_label_decision via AuditWriter (telemetry; backtest hook=None ⇒ zero rows)
```

The **semantic inheritance** from Epic 15: meta-label gate runs *after* regime gate, never
overrides a regime suppression, never gates exits, defaults to admit when no artifact wired
(byte-identical OFF parity). New: feature vector is **read from the same `RegimeSnapshot`** the
regime gate just consumed — zero recompute, zero same-bar drift.

### Scope (Epic 17)

**In Scope:**

- `on_publish` callback seam on `RegimeStateStore.publish` (default None ⇒ unchanged) +
  `FeatureRecorder` sink + Parquet flush with dataset fingerprint.
- Triple-barrier labeller as a pure function over `BacktestResult.trades`; vertical barrier =
  `max_holding_bars`; profit/stop barriers = the bracket's existing `tp_atr_mult` / `sl_atr_mult`
  (no path-dependency re-simulation).
- Purged + embargoed CV splitter wrapping `skfolio.model_selection.CombinatorialPurgedCV`
  with `groups=exit_ts` from the labeller.
- LightGBM training CLI (`scripts/train_meta_label.py`) producing `.joblib` + `.json` sidecar
  (feature schema fingerprint, train window, CV metrics, code SHA, dataset fingerprint).
- Isotonic calibration via `sklearn.calibration.CalibratedClassifierCV`.
- `MetaLabelArtifact` loader with fingerprint + feature-order schema guard (raises `ConfigError`
  on mismatch — security rule: fail-loud, never silent default).
- `MetaLabelGate` runtime class (sync `should_take(signal, features) → (bool, float)` — admit + PoP).
- `BaseStrategy._meta_label_admits` + entry-only wiring in `_go_long` / `_go_short` and
  `BracketStrategyMixin._submit_bracket_for_entry` (mirrors Epic 15 15.7 entry seam).
- Backtest wiring: `BacktestRunner.attach_meta_label_gate` (or extend `attach_regime`).
- Live wiring: `AccountNodeSpec` gains a `meta_label_gate` field; `LiveOrchestrator` loads the
  artifact at session start; XOR guard requires regime ON when meta-label ON.
- Audit row kind `meta_label_decision` via existing `AuditWriter` queue (Epic 15 15.11
  primitive); backtest writes zero rows (`audit_to_db=False`).
- A/B evaluation harness comparing Epic 15 baseline vs meta-label ON (PSR, Sharpe, max-DD,
  EV/trade, per-fold breakdown).
- Drift monitor: weekly scheduled per-feature mean/std check vs training distribution stored
  in artifact sidecar; alert-only (no auto-disable in v1).
- Default-OFF byte-identical parity test extending Epic 15 15.9 ablation CSV pattern.
- New deps in `pyproject.toml`: `lightgbm`, `scikit-learn`, `skfolio`, `mlfinpy` (or vetted
  equivalent — see Open Decision #2).

**Out of Scope (defer):**

- Continuous PoP-to-size scaling (`MetaLabeledSizer` wrapping `RiskBasedPositionSizer`) — v1 is
  binary gate only. Tracked as follow-up epic.
- Multi-strategy shared model with `strategy_id` as a feature — defer until per-strategy trade
  volume proves insufficient (the meta-label research 200–500 floor).
- Automatic retraining on drift — v1 is calendar-based manual; no auto-retrain Actor.
- ONNX export for cross-language inference — `joblib` only.
- HMM / ML regime classifier upgrade (Epic 11 Phase 2 territory; orthogonal).
- Live model hot-reload — artifact change requires engine restart in v1.
- Cross-symbol / macro / spread / news features — deferred to a later feature-engineering epic.
- `feature_recorder` backfill from existing Epic 16 shards (one-shot ETL) — decide at 17.4 once
  per-symbol trade counts are measured.

---

## Architectural Decisions

> Full file:line evidence is captured in each story; this section lists the cross-cutting calls.

### 1. Feature recording via `on_publish` hook, NOT a separate Actor
`RegimeStateStore.publish` (`state_store.py`) gains an optional
`on_publish: Callable[[RegimeSnapshot], None] | None = None`. Default `None` ⇒ behaviour
byte-identical to Epic 15 (no overhead, no DI changes). Backtest wires the hook to a
`FeatureRecorder` sink that appends to an in-memory buffer and flushes Parquet on `on_stop`.
A standalone Actor was considered (architect's first-pass design) but rejected because (a)
the publish call is already a SSOT and a hook keeps the seam in one place; (b) hooks make the
default-OFF guarantee trivial (`is None` short-circuit); (c) no same-bar ordering re-proof
needed beyond the 15.4 baseline. Live mode never wires the hook (telemetry only — training
data comes from backtest replays).

### 2. Training is a CLI script, NOT an Actor or service
`scripts/train_meta_label.py` is a one-shot `uv run` invocation (`--firm`, `--strategy`,
`--symbol`, `--window`). Reads features.parquet + labels.parquet, runs CPCV-fitted
`CalibratedClassifierCV(LGBMClassifier(class_weight='balanced'), method='isotonic')`,
persists artifact + sidecar. No long-running process, no Actor lifecycle. Output goes to
`services/trading-engine/models/meta_label/{firm}_{strategy}_{symbol}_v{n}.joblib`
(gitignored; deployment via filesystem copy or future DVC). `joblib` over ONNX because
LightGBM has first-class joblib support, the artifact stays Python-native, and inference is
already ≤1ms.

### 3. `MetaLabelGate` placement: `BaseStrategy._meta_label_admits`, called immediately AFTER `_regime_admits`
Mirrors the Epic 15 entry-only seam contract exactly. In `_go_long` / `_go_short`, after the
existing `if not self._regime_admits(...)` guard, add `if not self._meta_label_admits(signal)`.
The gate is injected as a runtime attribute `self._meta_label_gate: MetaLabelGate | None = None`
(same R8 injection pattern Epic 15 used for `_regime_state`), defaulting to `None` for
byte-identical OFF behaviour. `_meta_label_admits` returns `True` when `_meta_label_gate is
None`; otherwise reads the snapshot already on the store (zero recompute, same-bar) and calls
`gate.should_take(...)`. **Exits NEVER gated** (R-Z4 inherits R-A from Epic 15). Same-bar
ordering: meta-label gate ALWAYS runs after regime gate, never independently — preserves the
single source of truth for suppression sequencing.

### 4. Triple-barrier labeller uses bracket multiples — no re-simulation
`BacktestResult.trades` (`backtesting/result.py` `TradeRecord`) already encodes barrier
outcomes (TP hit, SL hit, time-out). Label = `1` iff `pnl > 0` AND exit was TP-side; `0`
otherwise. Vertical barrier = `max_holding_bars` (new field on `BracketStrategyConfig`,
default = 4 × per-symbol average historical hold). Profit/stop barriers = the bracket's
`tp_atr_mult` / `sl_atr_mult` (NOT hardcoded — FTMO preset discipline applies). ATR taken
from the audited `RegimeFeatures.realized_vol` at `entry_ts` so labeller never recomputes a
feature the regime pipeline already produced. Each label carries `entry_ts`, `exit_ts` for
purging at story 17.5.

### 5. CV: wrap `skfolio.model_selection.CombinatorialPurgedCV`, groups = `exit_ts`
Use `skfolio.CombinatorialPurgedCV(n_folds=10, n_test_folds=2)` with `groups=label_exit_ts`
so overlapping triple-barrier windows are purged from training folds and an embargo gap
separates train/test. The book's naive `train_test_split(shuffle=True)` is **prohibited**
(`ml-data-prep-and-training.md` C1). Final OOS evaluation uses the Epic 16 `oos_reserve`
slice **touched exactly once** (data-prep Part D step 6); CPCV runs inside `in_sample` only.
No scaler fitted (LightGBM is scale-invariant — A5), eliminating an entire leakage class.
Project-owned thin wrapper (`src/ml/cv/purged.py`) exposes only the API we need so a future
skfolio bump doesn't break the surface.

### 6. Default-OFF + byte-identical parity (HARD INVARIANT — R-Z1)
With no artifact configured: `MetaLabelGate` never instantiated, `self._meta_label_gate is
None`, `_meta_label_admits` returns `True`, strategy path **byte-identical** to Epic 15
output. Verified by extending the Epic 15 15.9 ablation CSV (story 17.16): re-runs the same
fixtures with `meta_label_config=None` and asserts `BacktestResult.trades` bit-for-bit equals
the Epic 15 baseline checked in at 15.9 close. Artifact load failure at engine start is
**hard-fail in live, hard-fail in backtest** — Backtest-Reality Alignment forbids the
soft-fail-in-backtest asymmetry (Open Decision #5 below resolves this).

### 7. Artifact cardinality: per-firm × per-strategy × per-symbol, single shared timeframe
One artifact per `(firm_id, strategy_name, instrument_id)`. **Not** per-timeframe: a strategy
is bound to one `bar_type` per account (registry pattern). Per-strategy required because the
feature → PoP mapping is strategy-conditional. Per-symbol because XAUUSD vs EURUSD have
different vol regimes. Per-firm because FTMO vs The5ers have different barrier widths via
`configs/firms/*.yaml`. Initial deployment = 1 firm × 6 strategies × 4 symbols = 24
artifacts. `MetaLabelGate` is constructed per-strategy-instance and holds exactly one model.

### 8. Audit + drift via existing `AuditWriter` queue + `MetricsService` (no new infra)
PoP score + admit/skip decision write one row via the existing `AuditWriter` non-blocking
enqueue (Epic 15 15.11 primitive — same bounded queue, same drainer). Row kind
`meta_label_decision`, fields `(pop_score, threshold, model_version, feature_hash, admitted)`.
No new table — 180d retention from Epic 15 15.3 already applies. Backtest passes
`audit_to_db=False` ⇒ zero rows. Drift detection is a **weekly scheduled job in
`MetricsService`** computing per-feature mean/std vs training distribution stored in the
sidecar; alert-only (no auto-disable in v1).

### 9. Strict ordering inheritance — regime gate BEFORE meta-label gate
Meta-label admission never runs before regime admission. If regime suppresses, meta-label
never executes (short-circuit). This is enforced by code order in `_go_long` / `_go_short`,
not configuration. Rationale: regime kill-switch (HIGH_VOLATILITY) must dominate any
ML-derived signal-quality decision — FTMO domain rule.

---

## Story Breakdown

| # | Story | Effort | Phase | Binding AC / Risk | Status |
|---|---|---|---|---|---|
| 17.1 | `on_publish` callback seam on `RegimeStateStore.publish`: optional `Callable[[RegimeSnapshot], None]`; default `None` ⇒ unchanged. State store is the only file touched in the regime module | S | P0 Feature Recording | **R-Z1** default-OFF parity: hook `None` ⇒ byte-identical to Epic 15; never invoked on live event loop unless explicitly wired | backlog |
| 17.2 | `FeatureRecorder` sink + Parquet flush (`src/ml/feature_recorder.py`): in-memory buffer, schema pinned to `RegimeFeatures` field list, JSON sidecar carrying `(dataset_version, features_fingerprint, row_count, ts_range, code_sha)` mirroring Epic 16 manifest discipline | M | P0 Feature Recording | **R-Z2** look-ahead invariant — features keyed by `entry_ts` only, no recompute, no peek at future bars; fingerprint cross-checked against `RegimeFeatures` field order at load | backlog |
| 17.3 | Backtest wiring of recorder: `BacktestRunner.attach_regime` (15.8 seam) gains optional `feature_recorder` kw; when set, the recorder's `enqueue` is passed as the 17.1 `on_publish` hook. Live path **never** instantiates a recorder (R-Z1) | S | P0 Feature Recording | parity-neutral when recorder None; integration test confirms zero-overhead default | backlog |
| 17.4 | Triple-barrier labeller `src/ml/labeling/triple_barrier.py`: consume `BacktestResult.trades` — label `1` iff bracket TP hit (long: `exit_price ≥ entry + tp_atr_mult × ATR`; short: symmetric), else `0`. `max_holding_bars` config per-symbol; ATR taken from `RegimeFeatures.realized_vol` at `entry_ts` (no recompute) | M | P1 Training Pipeline | label window `[entry_ts, exit_ts]` recorded as the group key for 17.5 purging | backlog |
| 17.5 | CV splitter `src/ml/cv/purged.py`: thin project-owned wrapper over `skfolio.model_selection.CombinatorialPurgedCV` with `groups=exit_ts`, embargo H bars after `test_start`, H configurable per timeframe | M | P1 Training Pipeline | unit test: zero overlap rows survive in train fold; embargo respected; CPCV API surface locked behind own wrapper | backlog |
| 17.6 | LightGBM training CLI `scripts/train_meta_label.py`: load 17.2 features + 17.4 labels, drop NaN warmup rows, fit `LGBMClassifier(class_weight='balanced', num_leaves≤8, min_child_samples=30)` wrapped in `CalibratedClassifierCV(method='isotonic')` inside the 17.5 splitter, persist `.joblib` + sidecar JSON `(feature_order, train_window, cv_metrics, code_sha, dataset_fingerprint, threshold)` | L | P1 Training Pipeline | sidecar dataset fingerprint MUST equal 17.2 fingerprint at load time (refuse to load on mismatch); threshold chosen on CPCV OOS Sharpe peak persisted to sidecar | backlog |
| 17.7 | `MetaLabelArtifact` loader + schema guard `src/ml/artifact.py`: pure `joblib.load` + sidecar validation. Raises `ConfigError` on missing artifact, fingerprint mismatch, feature-order drift. No model code runs at import; lazy-loaded at `on_start` (mirrors 15.6 factory shape) | S | P2 MetaLabelGate Online | model path resolved via `settings.get_secret` / config, never hardcoded; fail-loud on any anomaly | backlog |
| 17.8 | `MetaLabelGate` class `src/ml/meta_label_gate.py`: sync `should_take(signal, features) → tuple[bool, float]` (admit + PoP). Threshold injected from sidecar (overridable by config + audit log of override). Inference target ≤1ms — benchmarked in unit test. Mirrors `RegimeAuditHook` sync-Callable pattern (no Actor, no msgbus) | M | P2 MetaLabelGate Online | **R-Z3** inference fast-path: 6+2 features only, single `predict_proba` call, no pandas DataFrame allocation per bar | backlog |
| 17.9 | `BaseStrategy._meta_label_admits` + entry seam: runtime-attr-injected `_meta_label_gate: MetaLabelGate \| None` next to `_regime_state`; `_meta_label_admits(signal)` returns `True` when gate `None` (R-Z1), else reads `RegimeSnapshot.features` from the store and delegates to `should_take`. Call inserted in `_go_long`, `_go_short`, and `BracketStrategyMixin._submit_bracket_for_entry` — always **after** `_regime_admits` | M | P2 MetaLabelGate Online | **R-Z4** exits never gated (inherits R-A); **R-Z5** ordering — meta-label AFTER regime, never independently. Audit row written before suppression via existing `AuditWriter` | backlog |
| 17.10 | Backtest wiring: `BacktestRunner.attach_meta_label_gate(meta_label_config)` builds gate per `(strategy, symbol)`, injects as runtime attr on each strategy AFTER `add_strategy`. Default-OFF when `meta_label_config` is `None` — byte-identical to Epic 15 closing state | M | P2 MetaLabelGate Online | parity test: 15.9 ablation CSV re-runs with meta-label OFF ⇒ trade counts equal Epic 15 baseline byte-for-byte | backlog |
| 17.11 | Live wiring in `LiveOrchestrator` + `node_factory`: `AccountNodeSpec` gains `meta_label_gate: MetaLabelGate \| None` (mirrors `regime_actor`/`regime_state` from 15.10); `_build_meta_label_components` loads artifact at orchestrator startup using firm-profile config. XOR guard: meta-label ON requires regime ON (gate consumes `RegimeSnapshot.features`) | M | P2 MetaLabelGate Online | **R-Z6** live `on_bar` may not block — artifact loaded once on `on_start`, inference sync ≤1ms | backlog |
| 17.12 | Audit + prediction logging: every `should_take` writes one row via `AuditWriter.enqueue_nowait` (re-uses 15.11 primitive). No new queue, no drainer. Backtest hook=`None` ⇒ zero rows (R-E parity inherited from Epic 15) | S | P2 MetaLabelGate Online | telemetry-not-double-entry: degrade-on-QueueFull, swallow+warn (same contract as `RegimeAuditHook`) | backlog |
| 17.13a | Production training campaign: invoke `scripts/train_meta_label.py` for each of the 24 `(firm, strategy, symbol)` combos pinned by Architectural Decision #7, on Epic 16 in_sample data; reject artifacts failing `n_trades ≥ N_min` (Open Decision #3) or OOS-Sharpe-uplift threshold; deliverable = `docs/sprint-artifacts/epic-17-training-campaign.md` (inventory + per-artifact CV metrics + rejection list). Resolves Open Decisions #2 (mlfinpy vs skfolio) and #3 (`N_min`) in practice | L | P3 Validation & Sweep | per-artifact gate is the **only** way artifacts ship to live (R-Z8). No partial-cardinality deploy: missing artifact ⇒ that `(firm, strategy, symbol)` cell stays default-OFF | backlog |
| 17.13b | Artifact storage layout + versioning runbook: `services/trading-engine/models/meta_label/{firm}_{strategy}_{symbol}_v{n}.joblib` (gitignored); `docs/runbooks/meta-label-artifact-storage.md` covers v1→vN bump procedure, rollback, sidecar fingerprint verification, atomic-deploy convention. DVC integration explicitly deferred to a follow-up | S | P3 Validation & Sweep | filesystem-only in v1 (Architectural Decision #2); Redis blob storage deferred until multi-node live deploy lands | backlog |
| 17.13c | A/B evaluation harness `scripts/evaluate_meta_label.py`: same dataset spec under (a) Epic 15 baseline, (b) meta-label ON (consumes 17.13a artifacts); reports trade count delta, Sharpe, max-DD, **PSR**, EV/trade, per-fold breakdown using the 17.5 splitter. Output: `docs/sprint-artifacts/epic-17-validation-report.md` | M | P3 Validation & Sweep | go/no-go: OOS Sharpe (gated) > baseline in ≥3/5 folds, **PSR > 0.90**, max-DD not worsened, trade-count reduction < 50% | backlog |
| 17.14 | Drift monitor `src/ml/drift_monitor.py` + scheduled `MetricsService` check: weekly compute per-feature mean/std from live inference log; alert via existing notification path if any feature drifts >3σ from training distribution recorded in 17.6 sidecar | S | P3 Validation & Sweep | drift signal is observability only — never auto-disables the gate (operator decides) | backlog |
| 17.15 | Documentation: `docs/runbooks/meta-label-training-and-rollout.md` (training cadence, threshold tuning, artifact storage, rollback) + `docs/architecture.md` update wiring `MetaLabelGate` into the diagram next to `RegimeActor` | S | P4 Cleanup | mirrors Epic 16's quality-report doc discipline | backlog |
| 17.16 | Default-OFF parity regression test `tests/integration/ml/test_meta_label_default_off_parity.py`: runs Epic 15 ablation CSV with `meta_label_config=None`, asserts byte-identical `BacktestResult.trades` vs Epic 15 baseline checked in at 15.9. CI tripwire if anything in 17.1–17.12 leaks runtime behaviour | S | P4 Cleanup | **R-Z1** hard invariant — failure blocks merge | backlog |

**Total effort:** ~7.75–8.25 working days (P0 ~1d, P1 ~2.5d, P2 ~2.5–3d, P3 ~2d, P4 ~0.5d).
Phases are independently mergeable: P0 ships a recorder behind a feature flag with zero runtime
risk; P1 is offline-only (no engine touch); P2 wires the gate default-OFF; P3 trains + validates;
P4 documents and pins parity. P0–P1 deliver a labeled training corpus even if the gate is never
enabled — a standalone deliverable for the research track. **The P3 training campaign (17.13a)
is the only story that produces shippable model artifacts**; without it, the gate is a tool
without a trained model and stays default-OFF in production.

**Test fate:**
- *Reused unchanged:* `tests/unit/regime/{features,classifier,hysteresis,decision,audit,actor}.py`,
  `tests/unit/strategies/test_base_strategy_regime_gate.py`, `tests/integration/regime/test_regime_actor_ablation_csv.py`
  (becomes the byte-identical parity oracle at 17.16). Epic 15's 15.9 ablation CSV stays as is —
  17.16 references it without modification.
- *Touched minimally:* `tests/unit/regime/test_state_store.py` gains a single case for the
  `on_publish` parameter (17.1).
- *Written new:* `test_feature_recorder.py` (17.2), `test_triple_barrier.py` (17.4),
  `test_purged_cv.py` (17.5 zero-overlap invariant), `test_train_meta_label.py` (17.6 CLI
  integration), `test_artifact_loader.py` (17.7 fingerprint mismatch raises),
  `test_meta_label_gate.py` (17.8 ≤1ms inference benchmark + threshold semantics + None-features
  short-circuit), `test_base_strategy_meta_label_gate.py` (17.9 mirror of 15.7's 18-test entry-seam
  coverage — exits never gated, default-OFF passthrough, regime-before-meta ordering),
  `test_live_orchestrator_meta_label.py` (17.11), `test_meta_label_default_off_parity.py` (17.16).

**Open decisions carried into implementation:**

1. **`mlfinpy` vs `skfolio` vs hand-rolled** for CPCV: skfolio is currently the most maintained
   (MIT, active 2025). `mlfinpy` is the AFML reference (BSD-3) but mostly unmaintained.
   Recommendation: wrap `skfolio.CombinatorialPurgedCV` behind a thin own-interface in 17.5 so
   a future swap is one-file. Confirm at 17.5 spike (verify skfolio handles overlapping
   `groups=exit_ts` semantics we need).
2. **Threshold sourcing:** persist in artifact sidecar (chosen on CPCV OOS Sharpe peak), allow
   per-deployment config override with audit log of the override. Recommendation: hardcoded in
   sidecar, override path writes an audit row. Resolve at 17.6 design.
3. **Class-imbalance handling:** `LGBMClassifier(class_weight='balanced')` vs SMOTE
   oversampling. Class weight is simpler and avoids synthetic samples leaking through CPCV
   groups — preferred but needs spike confirmation on per-strategy trade counts. Resolve at
   17.6 first training run.
4. **Recorder backfill vs forward-only:** 17.1–17.3 produce features only from new backtests.
   Whether to backfill from Epic 16 shards in a one-shot script (faster training data) or wait
   for organic accumulation is decided at 17.4 once trades-per-symbol-per-year is measured
   against the 200–500 floor.
5. **Schema-hash mismatch policy at engine start:** hard-fail (refuse to start) in both
   backtest AND live to preserve Backtest-Reality Alignment. The architect's first-pass
   asymmetric proposal (hard-fail live, soft-fail backtest) was rejected here — both paths
   fail loudly. Final answer pinned for implementer.

**Per-story detail:** the full task breakdown with file:line seams lives inline in the table
above. XL/complex stories (17.6 training CLI, 17.9 entry seam, 17.11 live wiring) get a
dedicated `docs/sprint-artifacts/17-N-*.md` at draft time per the lightweight-docs convention.

---

## Risk Register

| ID | Risk | Mitigation |
|---|---|---|
| R-Z1 | Default-OFF parity breaks | Story 17.16 CI tripwire — byte-identical `BacktestResult.trades` vs Epic 15 baseline |
| R-Z2 | Look-ahead bias in features | Features keyed by `entry_ts` only; recorder never reads ahead; CPCV embargo |
| R-Z3 | Inference latency on hot path | ≤1ms benchmark in `test_meta_label_gate.py`; no DataFrame per bar |
| R-Z4 | Exits accidentally gated | Mirror Epic 15 R-A test coverage — explicit asserts at 17.9 |
| R-Z5 | Meta-label ordering inverted (runs before regime) | Code-order enforcement in `_go_long`/`_go_short`; 17.9 test pins ordering |
| R-Z6 | Live `on_bar` blocking on model load | Artifact loaded once at `on_start`; inference sync ≤1ms; 17.11 test |
| R-Z7 | Train/serve skew | Feature schema fingerprint in sidecar; loader raises on mismatch (17.7) |
| R-Z8 | Insufficient trade volume for per-strategy training | Minimum-trade-count gate in 17.6 CLI; open decision #3 |
