# Design Document: Port Regime Classification to a NautilusTrader `RegimeActor`

**Status:** Proposed
**Date:** 2026-05-24
**Author:** architect (ECC)
**Scope:** `services/trading-engine/` only (monorepo boundary respected — no cross-service imports)
**Principle served:** "Backtest-Reality Alignment: Same codebase for backtest and live trading" (`docs/architecture.md:38`)

> Origin: produced by the `architect` agent after the discovery that the Epic 11 regime
> pipeline (`RegimeAwareRouter`) is an external bar-dispatch wrapper, is **not wired into
> live or backtest**, and is architecturally incompatible with Nautilus's engine-owned bar
> dispatch. This design replaces it with a Nautilus `Actor`, mirroring the proven
> `PropFirmComplianceActor` pattern, so regime runs identically in backtest and live — and
> natively unblocks the meta-labeling spike (`docs/research/meta-labeling-corrective-ai.md`).

---

## Review Resolutions (2026-05-24, v1.1) — supersede the body where they conflict

Reviewed by `security-reviewer` + `database-reviewer` before planning. Verdict: **conditional proceed**. The actor approach and the "regime audit = telemetry, not an `account.*` mutation" argument were both **verified sound** (security F7, db F7: `context` JSONB carries `pop_score` with no migration). The following resolutions are binding on the plan and **override the original §1.4 / §2.2 / §8 where they differ**:

- **R-A (was security F2, CRITICAL — reversal-close asymmetry):** On a `HIGH_VOLATILITY` bar with a reversal signal, `_execute_signal` calls `_close_position()` (`supertrend.py:164-168`) **before** the entry gate, so the position **closes but the new entry is suppressed → strategy goes flat with no hedge**. This is the *intended, FTMO-safe* behavior (closing risk is always allowed; opening in HIGH_VOL is not). It MUST be (a) documented as intended and (b) covered by an explicit test: "HIGH_VOL reversal → close fires, entry suppressed, strategy flat." `_close_position` is **never** gated.
- **R-B (was security F4, HIGH — safe-by-default gating):** Do **not** rely on per-seam convention. `BaseStrategy._go_long` / `_go_short` (`base_strategy.py:222-226`) MUST call `_regime_admits` themselves, so any strategy — including future ones not using `BracketStrategyMixin` — is gated by default. The bracket seam (`_submit_bracket_for_entry`) keeps its gate too; both are entry-only.
- **R-C (was security F3 — exits never gated):** `evaluate_scale_out`, `_close_partial`, `_modify_sl` (`bracket_scale_out.py:136-213`) are **explicitly approved ungated exit/risk-reduction paths**. Enumerate them in the plan so no implementer adds a gate there.
- **R-D (was security F5 + db F2/F3 — audit path; USER DECISION: simplify):** **Drop `RegimeAuditSink` (the bounded deque) entirely.** It was a second buffer in front of `AuditWriter`'s already-bounded `asyncio.Queue` (`audit_writer.py:64`) and `deque(maxlen=N)` silently drops oldest (violates `audit.md`). Instead:
  - **Live:** the actor routes the regime `AuditEntry` through the **existing `AuditWriter` async queue** (the single bounded buffer with real back-pressure). Because regime audit is telemetry (F7), strict audit-before-publish ordering is **not required** — the original §1.4 "Option B" rationale no longer applies.
  - **Backtest:** regime audit stays **in-memory only**; `RegimeActorConfig.audit_to_db = False` is the default and the live drain path is simply not active. (Backtest has no running asyncio loop anyway — this also sidesteps that wrinkle.)
- **R-E (was db F5, MEDIUM — backtest must not pollute live DB):** Backtest regime audit (≈105k rows/yr at M5) MUST NOT write to the live `audit_logs` hypertable (would skew the `audit_daily_summary` continuous aggregate from migration 007 and compete for retention). If backtest regime audit is needed for debugging/training, write it to **parquet alongside the `feature_recorder` (§7.2)**, never the DB. This is enforced by R-D's `audit_to_db=False` default.
- **R-F (was db F1, HIGH — retention; USER DECISION: 180 is canonical):** `audit_logs` is currently 90-day (`007_audit_retention_and_aggregate.py:28`) but FTMO requires 180 (`sandboxed-domain.md`). The plan bundles a **new Alembic revision** that does `remove_retention_policy` → `add_retention_policy('audit_logs', INTERVAL '180 days')`. Regime audit inherits the corrected policy.
- **R-G (was db F6, LOW — doc drift, separate PR):** `.claude/rules/database/timescale.md` + `sandboxed-domain.md` name non-existent tables (`trade_audit_log`, `rule_check_log`); the real tables are `audit_logs` / `rule_violations`. Fix in a **docs-only follow-up**, not this epic.
- **R-H (was security F8/F9 — tests):** Add tests: warmup with a pre-existing position + flip signal → flat (no entry); `_regime_admits` with `None` snapshot → `False`.

**Net design changes vs body:** `src/regime/audit_sink.py` is **removed from the New-files list** (§10); a new **Alembic revision** file is added; `_go_long`/`_go_south` gating is added to `BaseStrategy` (§2.2); the live drainer task in §3/§6 is **deleted** (the existing `AuditWriter` worker already drains its own queue).

---

## 0. Confirmed facts (traced, not assumed)

| Claim | Evidence | Confirmed? |
|---|---|---|
| Regime pipeline today is an external bar-dispatch wrapper that gates by withholding bars | `regime_routing.py:139-145` `_dispatch` only calls `_route_bar_to_account` for allowed accounts; `HIGH_VOLATILITY` → `return` (global skip) | **Confirmed** |
| Audit-before-routing today: `await self._audit.log(decision)` precedes dispatch | `regime_routing.py:106` then `:108` | **Confirmed** |
| `RegimeAwareRouter`/`StrategyDataRouter` are NOT wired into the live engine | Grep across `src/`: references only in factory, `__init__`, `account_binding.py`, tests, and (separate) `accounts/signal_router.py`. Zero in `src/engine/` | **Confirmed** |
| Live data path is Nautilus-native via `RedisDataClient` | `node_factory.py:155-174` registers `RedisDataClient` as a `LiveDataClientFactory` + `node.trader.add_strategy`; `redis_data_client.py:268` `run_redis_bar_listener` → `_handle_data_py` (Nautilus ingest → bus → `on_bar`) | **Confirmed** |
| Backtest dispatch is Nautilus-owned (no external callback seam) | `engine.py:123-124` `add_strategy`, `:184` `engine.run()` | **Confirmed** |
| Actor is the proven cross-cutting template, built identically in both paths | `engine/actors.py:35` `build_compliance_actor`; backtest `engine.py:126-166` `attach_prop_firm_compliance`→`add_actor`; live `node_factory.py:177` `add_actor(spec.compliance_actor)` | **Confirmed** |
| Compliance actor's `on_bar` is **sync** and audits **synchronously in-process** (appends `BreachEvent`s to a list; does NOT call async `AuditWriter` per bar) | `prop_firm_actor.py:231-269`, `record_compliance_check:181-199` | **Confirmed** |
| `AuditWriter.log_async` is a coroutine wrapping `asyncio.Queue.put` (`audit_writer.py:140-153`); `log_sync:130` does a blocking `_batch_insert` | Read directly | **Confirmed** |
| Strategy registry already carries the per-strategy regime allow-list (`None`=always-allow / `[]`=never-route) | `registry.py:58-89`, `:158-190`; `_normalise_regimes:26-39` rejects `UNKNOWN` | **Confirmed** |
| `SupertrendStrategy` declares `regimes=[TRENDING_UP, TRENDING_DOWN]` at registration | `supertrend.py:68-71` | **Confirmed** |
| Factory raises `NotImplementedError` for >1 symbol | `factory.py:117-127` | **Confirmed** |
| Live builds **one `TradingNode` per account** | `node_factory.py:114-185`, `live_orchestrator.py:497-533` | **Confirmed** |
| Whether `redis_adapter.set_bar_callback(router.route_bar)` is wired live | `set_bar_callback` exists (`redis_adapter.py:330`); no production call site sets the router as that callback | **Inferred (strongly): vestigial.** Absence confirmed; intent cannot be proven. See §5 |

**Consequence:** there is *no production regime behavior to preserve*. We integrate once, correctly, against the Nautilus actor model.

---

## 1. `RegimeActor` design

### 1.1 The semantic shift (central problem)

A Nautilus `Actor` **cannot withhold** a bar — the engine delivers every subscribed bar to every subscriber. The current "gate by withholding" model is impossible inside an actor. The model inverts:

- **Old (router):** classify → withhold bar → strategy never runs.
- **New (actor):** classify → **publish** confirmed regime → strategy runs `on_bar`, reads regime, and **suppresses its own order emission** if disallowed.

Identical to the compliance-actor inversion (it became a reactive tracker because it cannot prevent a fill, `prop_firm_actor.py:13-16`). Regime actor becomes a *state publisher*; suppression moves to the order-emission seam.

### 1.2 Class shape — new file `src/regime/actor.py`

```python
class RegimeActorConfig(ActorConfig, frozen=True):
    bar_type: BarType | None = None        # subscribe target; None for unit tests
    primary_symbol: str

class RegimeActor(Actor):
    def __init__(
        self,
        config: RegimeActorConfig,
        classifier: RuleBasedRegimeClassifier,   # REUSED unchanged
        feature_extractor: FeatureExtractor,      # REUSED unchanged (one per bar_type)
        hysteresis: HysteresisFilter,             # REUSED unchanged
        regime_state: RegimeStateStore,           # NEW: shared publication object (§2)
        audit_sink: RegimeAuditSink | None = None,# NEW: sync-safe audit hop (§1.4)
    ) -> None: ...
```

The four pipeline components are injected **unchanged** (single-source-of-truth: the actor owns the only `FeatureExtractor`, indicators computed exactly once).

### 1.3 Lifecycle

```
on_start():  if config.bar_type: self.subscribe_bars(config.bar_type)   # cf prop_firm_actor.py:203-206
on_bar(bar):                                  # SYNC — Nautilus contract
    features = self._extractor.update(bar)    # features.py:105
    if features is None: return               # warmup: no audit, no publish (cf regime_routing.py:97-98)
    raw = self._classifier.decide(features)   # classifier.py:46
    decision = self._hysteresis.apply(raw, ts, features)  # hysteresis.py:94
    self._audit(decision)                     # AUDIT BEFORE PUBLISH (§1.4)
    self._regime_state.publish(decision)      # consumption seam (§2)
on_stop():   try: self.unsubscribe_bars(...)  except RuntimeError: pass  # cf prop_firm_actor.py:225-229
```

### 1.4 Async-audit-in-a-sync-actor (audit-before-routing discipline)

Today the router does `await self._audit.log(decision)` (`regime_routing.py:106`). Nautilus `on_bar` is **sync** — cannot `await`. Options:

| Option | Mechanism | Audit-before-publish? | Verdict |
|---|---|---|---|
| A. async task | `create_task(writer.log_async(...))` — does not complete before publish | **No** (same defect router's sync path documents, `regime_routing.py:116-119`) | Reject |
| **B. sync in-memory buffer (CHOSEN)** | `RegimeAuditSink` **synchronously** appends `AuditEntry` before `publish`; separate async drainer moves to `AuditWriter` (live: tracked task; backtest: `on_stop`) | **Yes** (append-before-publish is sync+ordered) | **CHOSEN** — mirrors compliance actor's sync-record discipline |
| C. msgbus audit event | publish a `RegimeAudit` for an async audit actor | ordering not guaranteed | Reject |

`RegimeAuditSink` **reuses `RegimeAuditAdapter._to_entry`** (`audit.py:69-100`) verbatim — only *where the await happens* moves (per-bar → batched-drain), which is the latency rationale the adapter docstring already gives (`audit.py:11-14`).

> **Flagged for `security-reviewer` / `database-reviewer`:** the regime decision is NOT an `account.*` mutation — it gates a downstream order whose real mutation is still guarded by the existing `RuleEngine` audit path. Regime audit is *telemetry of a gating decision*, already non-blocking (`log_async`) today, so Option B weakens no existing guarantee. Flagged explicitly, not asserted.

---

## 2. State publication + consumption

### 2.1 Decision: shared in-memory `RegimeStateStore` injected into actor + strategy

| Option | Verdict |
|---|---|
| Nautilus msgbus pub/sub of custom data | Viable fallback; same-bar ordering vs strategy `on_bar` not guaranteed; more moving parts |
| Nautilus `Cache` custom data | Reject — serialization friction; same-bar read-your-write timing issue |
| **Shared in-memory `RegimeStateStore` (CHOSEN)** | Zero serialization, O(1) hot-path read, trivially testable, identical object in both paths via shared factory |
| Strategy owns its own `FeatureExtractor` | **Reject** — duplicates indicators per strategy; breaks single-source-of-truth + audit correspondence |

```python
@dataclass(frozen=True)
class RegimeSnapshot:
    bar_type: str
    current_state: RegimeState
    confidence: float
    ts: datetime

class RegimeStateStore:
    """Single source of truth for latest confirmed regime per bar_type.
    Written ONLY by RegimeActor.on_bar; read by strategies pre-order."""
    def publish(self, decision: RegimeDecision) -> None: ...
    def current(self, bar_type: str) -> RegimeSnapshot | None: ...
```

Immutability (`coding-style.md`): `publish` replaces the per-`bar_type` snapshot with a new frozen object.

### 2.2 Consumption seam in `BaseStrategy`

Gate **only at entry-only seams** so exits are never suppressed (FTMO-critical):

```python
def _regime_admits(self, signal: SignalType) -> bool:
    store = self._regime_state              # injected; None when regime disabled
    if store is None: return True           # parity with enabled=False today
    snap = store.current(str(self.config.bar_type))
    if snap is None: return False           # warmup: no confirmed regime → suppress
    state = snap.current_state
    if state == RegimeState.HIGH_VOLATILITY: return False   # global kill-switch
    allowed = self._allowed_regimes
    return allowed is None or state in allowed
```

Recommended placement: **`_submit_bracket_for_entry`** (`bracket_strategy.py:276-306`, entry-only by contract) for bracket strategies, and `_go_long`/`_go_short` for the plain path. **Never** in `_close_position`/scale-out exits.

### 2.3 Allow-list + kill-switch mapping

- Allow-list: inject `self._allowed_regimes = StrategyRegistry.get_regimes(name)` (`registry.py:158`) at build time — same source the router uses today (`factory.py:143-146`). `None`/`frozenset`/`[]` semantics preserved verbatim.
- `HIGH_VOLATILITY`: unconditional `return False` *before* the allow-list check → every strategy skips, including always-allow ones (reproduces `regime_routing.py:140-141` precedence).

---

## 3. Shared factory + attach points

- **`build_regime_actor`** in `src/engine/actors.py` (beside `build_compliance_actor`), `enabled=False → return None` (zero-overhead default). Reuses `_build_extractor` (lift to `src/regime/builders.py` to avoid cycle).
- **`BacktestRunner.attach_regime`** mirrors `attach_prop_firm_compliance` (`engine.py:126-166`); `run_backtest` wires store between `add_data` and `add_strategy`, injecting the store + allow-list into the strategy.
- **Live**: `AccountNodeSpec` gains `regime_actor`/`regime_state`; `build_account_trading_node` attaches actor **before** strategy; `LiveOrchestrator._build_session_components` builds per-account actor+store+audit-drainer task (mirror health-push loop `:737-758`).
- **Add order:** `add_actor(regime)` → `add_strategy` → `add_actor(compliance)` (regime before strategy for read-after-write; compliance independent).

### 3.4 Ordering caveat (see R1)

Regime actor must update the store **before** the strategy reads it for the same bar. Relies on add-order + subscription order — **must be verified by a focused integration test**. If Nautilus does not guarantee actor-before-strategy `on_bar` for the same `BarType`, fall back to the **one-bar-lag contract** (strategy reads regime confirmed as of previous bar; acceptable because hysteresis already imposes multi-bar confirmation latency).

---

## 4. Multi-symbol / multi-bar-type

- Live is one node per account → **one `RegimeActor` per node** scoped to its bar_type; dissolves the Phase-1 single-symbol limit naturally.
- Backtest is single-symbol per run → one actor per run.
- Multiple bar_types in one run/node → **one `RegimeActor` per bar_type**, each writing its slice of the per-`bar_type`-keyed store. Phase-1 scope stays single bar_type; path to multi needs no new abstraction.

---

## 5. Fate of `RegimeAwareRouter` / `StrategyDataRouter`

- **Live data path confirmed Nautilus-native** via `RedisDataClient` (`redis_data_client.py:160,273`); `StrategyDataRouter.route_bar` is **not** a live call site. The `data_router.py:8-17` docstring describes a pre-`TradingNode` (Epic ≤9) design superseded by Epic 10.5 per-account nodes.
- **`RegimeAwareRouter`: deprecate + remove** (Phase 3) — incompatible with actor model, never wired. Delete `regime_routing.py` + `build_regime_aware_router` (`factory.py:76-160`); keep `_build_extractor`.
- **`StrategyDataRouter`: retain, do not extend.** Removal is a separate cleanup (`account_binding.py` still references it) → hand to `refactor-cleaner` as follow-up. *Cannot confirm it is fully dead.*

---

## 6. Migration plan (phased, independently shippable)

- **P0** — Extract `builders.py`; add `RegimeStateStore`, `RegimeAuditSink` + unit tests. No wiring, no runtime change.
- **P1** — `RegimeActor`, `build_regime_actor`, `attach_regime`, `BaseStrategy._regime_admits` + entry-only gate, store injection in `run_backtest`. **Default-off** = byte-identical to today. New e2e + ablation tests; **verify actor-before-strategy ordering**.
- **P2** — Live wiring (`AccountNodeSpec`, `node_factory`, `LiveOrchestrator` actor + drainer) + live integration test.
- **P3** — Remove `RegimeAwareRouter`; rewrite obsolete tests.

**Test fate:**

| Test | Fate |
|---|---|
| `tests/unit/regime/{features,classifier,hysteresis,decision,audit}.py` | **Port unchanged** (reused components don't change) |
| `tests/unit/strategies/test_regime_aware_router.py` | **Obsolete** → `test_regime_actor.py` + `test_base_strategy_regime_gate.py` |
| `tests/integration/regime/test_router_e2e.py` | **Rewrite** as `test_regime_actor_e2e.py` (scripted-extractor double `:53-65` ports directly) |
| `tests/integration/regime/test_router_ablation_csv.py` + fixtures | **Port** to drive a real `BacktestRunner` (CSV fixtures finally exercise the real `FeatureExtractor`) |

---

## 7. Impact on the meta-labeling spike

The spike's biggest blocker (research Open Question #1, `meta-labeling-corrective-ai.md:408`) — "backtest doesn't compute `RegimeFeatures`" — is **resolved**: the actor's `on_bar` runs `FeatureExtractor.update(bar)` natively in backtest, no lookahead, same engine that produces the trades.

### 7.1 `MetaLabelGate` plugs into the SAME seam

The router seam disappears; the successor is `BaseStrategy._regime_admits` / `_submit_bracket_for_entry` — regime allow-list and meta-label PoP are both **pre-order entry-suppression checks** and compose:

```python
def _admit_entry(self, signal, features) -> bool:
    if not self._regime_admits(signal): return False          # regime + HIGH_VOL
    if self._meta_gate is not None and not self._meta_gate.should_take(features, signal):
        return False                                          # meta-label PoP
    return True
```

`MetaLabelGate` reads the **same `RegimeFeatures` the actor published** (extend `RegimeSnapshot` to carry `features`, or expose `current_features(bar_type)`) → model input identical to the audited regime decision, no recomputation/drift. Inference stays synchronous, <0.3ms.

### 7.2 Feature snapshots for training

Add an optional `feature_recorder` to `RegimeActor` (off by default): `on_bar` appends `(ts, bar_type, asdict(features), confirmed_state)` to a buffer the `BacktestRunner` flushes to parquet on `on_stop`. Satisfies spike step 2 natively — no `record_features=True` recompute path needed.

---

## 8. Risks & trade-offs

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Nautilus may not guarantee actor `on_bar` before strategy `on_bar` same bar → stale regime | **HIGH** | Ordering test (§6 P1); else adopt one-bar-lag contract (within hysteresis tolerance) |
| R2 | Warmup differs: strategy runs `on_bar` but suppressed at entry vs legacy never seeing bar | MEDIUM | Documented; quantified by ablation; net more conservative (FTMO-safe) |
| R3 | Async audit off hot path could lose buffered entries on hard crash | MEDIUM | Bounded deque; frequent live drain; backtest flush on `on_stop`; no worse than today's `log_async` queue. Flag `database-reviewer` |
| R4 | Exits accidentally gated → cannot close risk in HIGH_VOL | **CRITICAL** | Gate only in entry-only seams; explicit test: HIGH_VOL suppresses entries, never exits |
| R5 | Two actors on one node subscribe same bar_type | LOW | Different computations; one extra `FeatureExtractor` (already so in router design); no interdependency |
| R6 | `StrategyDataRouter` removal scope-creep | LOW | Out of scope (§5); hand to `refactor-cleaner` |
| R7 | Multi-symbol live assumes one primary bar_type | LOW | Phase-1 single bar_type; store per-bar_type-keyed → N actors compose |
| R8 | Injecting store/allow-list into msgspec-backed strategies | MEDIUM | Inject as runtime attributes after construction (not config fields), avoiding the msgspec constraint that bit `BracketStrategyConfig` (`bracket_strategy.py:55-63`) |

---

## 9. Effort estimate

| Phase | Estimate |
|---|---|
| P0 — builders + store + sink + tests | 0.5–1 day |
| P1 — actor + factory + attach + gate + ported tests + ordering check | 2–3 days |
| P2 — live wiring + integration tests | 2 days |
| P3 — remove router + rewrite tests | 0.5 day |
| **Total P0–P3** | **5–6.5 days** |
| Meta-label follow-on (separate epic, after spike validates) | 1–2 days |

---

## 10. Files

**New:** `src/regime/actor.py`, `src/regime/state_store.py`, `src/regime/audit_sink.py`, `src/regime/builders.py`

**Modified:** `src/engine/actors.py` (+`build_regime_actor`), `src/backtesting/engine.py` (+`attach_regime`), `src/backtesting/runner_facade.py` (wire store), `src/engine/node_factory.py` (`AccountNodeSpec` + attach order + inject store), `src/engine/live_orchestrator.py` (per-account actor+store+drainer), `src/strategies/base_strategy.py` (`_regime_admits` + gate), `src/strategies/bracket_strategy.py` (gate in `_submit_bracket_for_entry`)

**Removed (P3):** `src/strategies/regime_routing.py`, `build_regime_aware_router` in `src/regime/factory.py:76-160`

**Unchanged (reused verbatim — the point):** `src/regime/{features,classifier,hysteresis,decision,states,audit}.py`, `src/strategies/registry.py`, `src/config/firm_profile.py`

---

### One-line summary

Replace the never-wired, gate-by-withholding `RegimeAwareRouter` with a `RegimeActor` that runs the **unchanged** classify→hysteresis→audit pipeline in `on_bar` and publishes the confirmed regime to a shared per-`bar_type` `RegimeStateStore`; strategies read it at their **entry-only** order seam and suppress disallowed entries — built by one `build_regime_actor` used identically in backtest (`attach_regime`) and live (`node_factory`/`LiveOrchestrator`), mirroring `PropFirmComplianceActor`, and giving the meta-labeling spike a native backtest feature stream at the same suppression seam.
