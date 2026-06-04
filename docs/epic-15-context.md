# Epic 15: Regime Backtest-Live Parity (RegimeActor) — Technical Context

**Created:** 2026-05-24
**Last updated:** 2026-05-24
**Status:** **Contexted** — 13 stories drafted, not started
**Epic:** 15 of 15+
**Stories:** 13 (15.1 – 15.13) across 4 phases (P0–P3)
**Predecessor (regime work):** Epic 11 (Market Regime Classifier Phase 1) — closed 2026-05-02
**Source design:** `docs/design/regime-actor-design.md` (v1.1, security + database reviewed)
**Source research:** `docs/research/meta-labeling-corrective-ai.md` (the downstream epic this unblocks)
**Branch:** `feat/regime-actor-backtest-parity`

> **Numbering note:** This is **Epic 15**. **Epic 14 remains reserved for the mt5-bridge EA / ZMQ
> work** (referenced throughout `CLAUDE.md`, the `mql5-zmq-bridge` / `mql5-patterns` skills, and
> `.claude/rules/mql5/*`, with story map 14.1–14.6 / 14.19 / 14.20). RegimeActor parity is a
> standalone infrastructure epic that builds on Epic 11 and is independent of the mt5-bridge
> track — the two can proceed in parallel. (An earlier 2026-05-24 decision briefly assigned this
> work to Epic 14, then reversed it once the depth of the mt5-bridge "Epic 14" documentation was
> surfaced.)

---

## Overview

### Problem Statement

Epic 11 shipped a rule-based regime classifier, but it was built as `RegimeAwareRouter` — an
**external bar-dispatch wrapper** around `StrategyDataRouter` that gates by **withholding the
bar** from disallowed strategies (`src/strategies/regime_routing.py:139`). Two facts surfaced
during the meta-labeling research (2026-05-24):

1. **It is wired into neither backtest nor live.** Grep of `src/engine/` finds zero references
   to `RegimeAwareRouter`. The live data path is Nautilus-native via `RedisDataClient`
   (`redis_data_client.py:273` → message bus → `strategy.on_bar`), not the router. So regime
   gating runs **nowhere** in production today.
2. **It is architecturally incompatible with the backtest engine.** Nautilus `BacktestEngine`
   owns bar dispatch (`add_strategy` + `add_data` → engine calls `on_bar` itself). There is no
   external callback seam to insert a router. The "gate by withholding" model cannot exist
   inside the engine.

This violates the architecture's stated **"Backtest-Reality Alignment: Same codebase for
backtest and live trading"** principle (`docs/architecture.md:38`): the regime pipeline can
only ever run live (via the never-wired router), so a backtest can never reproduce live
regime-gated behavior. It also blocks the meta-labeling spike, whose #1 prerequisite is
"compute `RegimeFeatures` natively during a backtest."

### Solution

Replace `RegimeAwareRouter` with a **NautilusTrader `Actor`** (`RegimeActor`) that runs the
**unchanged** classify → hysteresis → audit pipeline in `on_bar` and **publishes** the
confirmed regime to a shared per-`bar_type` `RegimeStateStore`. Strategies **read** that store
at their **entry-only** order seam and **suppress their own disallowed entries** — instead of
never seeing the bar. Built once via a shared `build_regime_actor` factory, attached via
`add_actor` in **both** backtest (`BacktestRunner.attach_regime`) and live
(`node_factory` / `LiveOrchestrator`) — mirroring the proven `PropFirmComplianceActor` pattern
(`src/engine/actors.py` `build_compliance_actor`, used identically in both paths since Epic 10.5d).

```
Bar arrives (delivered by Nautilus engine to ALL subscribers)
  → RegimeActor.on_bar:  FeatureExtractor → Classifier → Hysteresis
                         → audit (telemetry) → RegimeStateStore.publish(decision)
  → Strategy.on_bar:     generate_signal → _regime_admits(signal)?  ← reads the store
                           • store None        → allow (parity with disabled)
                           • snapshot None      → suppress (warmup, no confirmed regime)
                           • HIGH_VOLATILITY    → suppress (global kill-switch)
                           • signal regime ∈ allow-list (or None) → allow, else suppress
                         → entry submitted ONLY if admitted; EXITS never gated
```

**The semantic inversion** (vs Epic 11): old = "withhold bar, strategy never runs"; new =
"deliver bar, strategy self-suppresses entry." Exits (`_close_position`, scale-out) are
**never** gated — in FTMO you must always be able to close risk.

### Scope (Epic 15)

**In Scope:**

- `RegimeStateStore` / `RegimeSnapshot` — shared per-`bar_type` regime publication object.
- `RegimeActor` (Nautilus `Actor`) reusing the **unchanged** Epic-11 pipeline
  (`FeatureExtractor`, `RuleBasedRegimeClassifier`, `HysteresisFilter`, `RegimeAuditAdapter`).
- `build_regime_actor` shared factory + `BacktestRunner.attach_regime` + live wiring
  (`node_factory` / `LiveOrchestrator`).
- `BaseStrategy._regime_admits` + **entry-only** gating in `_go_long`/`_go_short` (safe-by-default)
  and `_submit_bracket_for_entry`.
- Audit path simplified (review R-D): **live** routes through the existing `AuditWriter` async
  queue; **backtest** keeps regime audit in-memory (`audit_to_db=False`, zero rows to `audit_logs`).
- Alembic revision: `audit_logs` retention 90 → **180 days** (review R-F).
- Remove `RegimeAwareRouter` + `build_regime_aware_router`; port/retire the Epic-11 regime tests.
- Default-OFF: with no store injected, behavior is **byte-identical** to today.

**Out of Scope (defer):**

- **Meta-label gate / `MetaLabelGate`** — separate later epic (Signal-Quality). Only forward-compat
  hook included: optional `features` field on `RegimeSnapshot`. Source: `docs/research/meta-labeling-corrective-ai.md`.
- **`StrategyDataRouter` removal** (still referenced by `account_binding.py`) — hand to `refactor-cleaner`.
- **Doc-drift fix (review R-G):** `.claude/rules/database/timescale.md` + `sandboxed-domain.md` name
  non-existent tables (`trade_audit_log`/`rule_check_log` vs real `audit_logs`/`rule_violations`) — docs-only PR.
- HMM / ML regime upgrade (Epic 11 Phase 2 territory); multi-symbol beyond single-`bar_type`-per-node.
- `feature_recorder` parquet training stream (meta-label epic).

---

## Architectural Decisions

> Full detail + traced file:line evidence in `docs/design/regime-actor-design.md`. Summary:

### 1. Nautilus `Actor`, not an external router
The `PropFirmComplianceActor` precedent (`build_compliance_actor`, attached via `add_actor` in
both backtest `engine.py:126-166` and live `node_factory.py:177`) is the only pattern that runs
identical code in both environments. The router model is impossible inside the engine.

### 2. Shared in-memory `RegimeStateStore` (not msgbus / Cache)
Zero serialization, O(1) hot-path read, identical object both paths via the shared factory.
Msgbus/Cache rejected for same-bar read-your-write ordering friction; strategy-owned extractor
rejected (duplicates indicators, breaks single-source-of-truth + audit correspondence).

### 3. Gating moves into the strategy, entry-only (review R-A/R-B/R-C — CRITICAL)
The actor cannot withhold a bar, so suppression lives in the strategy. Gate is placed **only**
at entry-only seams (`_go_long`/`_go_short` self-gate for safe-by-default, plus
`_submit_bracket_for_entry`). `_close_position` and scale-out exits (`evaluate_scale_out`,
`_close_partial`, `_modify_sl`) are **never** gated. A HIGH_VOL reversal therefore closes the
position but suppresses the new entry → strategy goes flat (intended, FTMO-safe; explicit test).

### 4. Audit simplified to the single existing `AuditWriter` queue (review R-D)
Regime audit is **telemetry, not an `account.*` mutation** (verified: `audit.py:79` `account_id=None`;
double-entry rule does not apply), so strict audit-before-publish ordering is not required.
**No second buffer / `RegimeAuditSink` deque.** Live enqueues onto the existing bounded
`AuditWriter` queue; backtest stays in-memory (`audit_to_db=False`) and writes zero rows to
`audit_logs` (review R-E — backtest must not pollute the live hypertable / `audit_daily_summary`).

### 5. `audit_logs` retention 90 → 180 days (review R-F)
Migration 007 set 90d; FTMO requires 180d (`sandboxed-domain.md`). A new Alembic revision
`remove_retention_policy` → `add_retention_policy(... '180 days')`, no `DROP TABLE`.

### 6. Actor-before-strategy ordering is a verified contract, not an assumption (risk R1)
Whether Nautilus dispatches actor `on_bar` before strategy `on_bar` for the same `bar_type` is
proven by a dedicated test (story 15.4). Contingency if not guaranteed: **one-bar-lag** contract
(strategy reads previous bar's confirmed regime — acceptable, hysteresis already imposes latency).

### 7. Default-OFF parity
No store injected ⇒ `_regime_admits` returns `True` ⇒ byte-identical to current behavior. Opt-in
rollout, same as Epic 11's `regime_classifier.enabled: false`.

---

## Story Breakdown

| # | Story | Effort | Phase | Binding AC (review resolution) | Status |
|---|---|---|---|---|---|
| 15.1 | Lift `_build_extractor` → `src/regime/builders.py` (re-export; factory still works) | S | P0 Extraction | — | backlog |
| 15.2 | `RegimeStateStore` + `RegimeSnapshot` (`src/regime/state_store.py`); optional `features` field | S | P0 Extraction | R-H precondition (unknown bar_type → `None`) | backlog |
| 15.3 | Alembic revision: `audit_logs` retention 90 → 180 (up+down, no `DROP TABLE`) | S | P0 Extraction | **R-F**; db+security review gate | backlog |
| 15.4 | ⚠️ R1 ordering verification spike (actor-before-strategy `on_bar`); one-bar-lag fallback | S | P1 Actor | risk R1 — gates 15.7 | backlog |
| 15.5 | `RegimeActor` + `RegimeActorConfig` (`audit_to_db=False`); reuse pipeline verbatim | L | P1 Actor | **R-D** (no deque; backtest no loop/DB) | backlog |
| 15.6 | `build_regime_actor` in `src/engine/actors.py` (enabled=False → None) | M | P1 Actor | single extractor (SSOT) | backlog |
| 15.7 | `BaseStrategy._regime_admits` + entry-only gating in `_go_long`/`_go_short` + bracket seam | M | P1 Actor | **R-A** (close never gated), **R-B** (safe-by-default), **R-C** (scale-out ungated), **R-H** | backlog |
| 15.8 | `BacktestRunner.attach_regime` + store/allow-list injection in `run_backtest` | M | P1 Actor | **R-E** (zero rows to `audit_logs`); add-order regime→strategy→compliance | backlog |
| 15.9 | Port ablation CSV test to a real `BacktestRunner` (`test_regime_actor_ablation_csv.py`) | M | P1 Actor | risk R2 (warmup delta documented) | backlog |
| 15.10 | `AccountNodeSpec` regime fields + attach order in `node_factory.py` | M | P2 Live | R8 (runtime-attr injection) | backlog |
| 15.11 | Per-account actor + store in `LiveOrchestrator`; audit via existing `AuditWriter` (no drainer) | M | P2 Live | **R-D** (single bounded queue, no extra task) | backlog |
| 15.12 | Remove `RegimeAwareRouter` + `build_regime_aware_router`; update `src/regime/__init__.py` | S | P3 Cleanup | R6 (`StrategyDataRouter` retained) | backlog |
| 15.13 | Retire/rewrite obsolete regime tests (router unit/e2e); reused-component tests unchanged | S | P3 Cleanup | suite green, ≥80% on new modules | backlog |

**Total effort:** ~5–5.5 working days (P0 ~0.5, P1 2.5–3, P2 ~1.5, P3 0.5). Phases are independently
mergeable; P0–P1 deliver backtest parity with zero risk to the running engine (default-OFF).

**Test fate (Epic 11 regime tests):** `tests/unit/regime/{features,classifier,hysteresis,decision,audit}.py`
port **unchanged** (reused components). `test_regime_aware_router.py` retired → `test_regime_actor.py`
+ `test_base_strategy_regime_gate.py`. `test_router_e2e.py` → `test_regime_actor_e2e.py`.
`test_router_ablation_csv.py` → `test_regime_actor_ablation_csv.py` (now exercises the real
`FeatureExtractor` via the actor).

**Open decisions carried into implementation** (from design v1.1, §"Ambiguities"):
1. 15.4 ordering result picks same-bar vs one-bar-lag (sequencing gate for 15.7).
2. Live sync-`on_bar` → async `AuditWriter` enqueue primitive (confirm at 15.5; telemetry, degrade gracefully).
3. `RegimeSnapshot.features` included now (recommended, forward-compat for meta-label epic).
4. `primary_symbol` explicit on `RegimeActorConfig` (recommended; avoids re-introducing the bar_type parser).

**Per-story detail:** the full task breakdown with file:line seams lives in
`docs/design/regime-actor-design.md` §6 + §10. XL/complex stories (15.5, 15.7) may get a dedicated
`docs/sprint-artifacts/15-N-*.md` at draft time per the lightweight-docs convention.
