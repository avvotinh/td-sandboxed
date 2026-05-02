# Strategy Review — 2026-05-02

**Scope:** all 6 strategies (`ma_crossover`, `supertrend`, `donchian_breakout`, `rsi_mean_reversion`, `bollinger_mean_reversion`, `orb`) plus shared infrastructure (`base_strategy`, `bracket_strategy`, mixins, registry, account_binding, data_router, regime_routing).
**Branch / head:** `feature/architecture` @ `a1296d1` (post-Epic 11).
**Reviewers:** 6× python-reviewer (per-strategy) + 1× architect (cross-cutting) + 1× Explore (coverage) — all run in parallel.
**Verifier:** the orchestrator (Claude) re-checked CRITICAL/HIGH claims empirically before landing this doc.

---

## Executive Summary

The strategy layer is **structurally healthy**. Composition over inheritance is the dominant pattern, the regime layer (Epic 11) is genuinely additive, and the sizing path has a single auditable seam. None of the 6 strategies has a CRITICAL bug verified after re-checking reviewer claims. The two issues most worth fixing before the backtest epic begins are:

1. **Cross-strategy validation invariants** (HIGH) — `BracketStrategyConfig` allows `sl_atr_mult >= tp_atr_mult` (R:R < 1) and individual strategies accept obviously-degenerate parameters (`num_std=20.0`, `session_open >= session_close`). One-line guards close all of them.
2. **Bracket execution path coverage gaps** — five bracket strategies share `_submit_bracket_for_entry` but no test exercises tick-rounding, ATR-zero, or position-reversal end-to-end.

Two structural improvements worth scheduling right after the backtest epic:

3. **`MeanReversionMixin`** — `RSIMeanReversionStrategy` and `BollingerMeanReversionStrategy` are character-for-character identical except for `generate_signal`. The duplication compounds with each new MR variant.
4. **Implicit mixin contract → explicit `BracketHost` Protocol** — `BracketStrategyMixin` requires 10+ host attributes verified only by `# type: ignore`. A 7th bracket strategy that forgets `RiskSizedMixin` fails at first signal, not at construction.

### Reviewer accuracy notes (corrections applied)

Two reviewer findings were re-tested empirically and reclassified:

| Reviewer claim | Severity claimed | Verified status | Action |
|---|---|---|---|
| `__post_init__` on `BracketStrategyConfig` and friends "never runs" because msgspec `Struct` doesn't fire it | CRITICAL (architect) | **Incorrect.** Tested with `MACrossoverConfig(slow_period=20, fast_period=50)` → raises `ValueError`. Tested `SupertrendConfig(period=-1)` → raises. Tested `RSIMeanReversionConfig(oversold=0.7, overbought=0.3)` → raises. NautilusTrader's `StrategyConfig` does invoke `__post_init__`. | Demoted to "not applicable" — original validators are live |
| `MA Crossover` and `Supertrend` "bypass the rule engine" because `submit_order` is called without an explicit rule check | HIGH (ma_crossover, supertrend reviewers) | **Incorrect.** Validation is at the adapter layer: `src/execution/validated_adapter.py::ValidatedZmqAdapter.send_order` validates every order before forwarding to the underlying `ZmqAdapter`. Strategies invoke Nautilus's `submit_order` which the engine routes to the configured `OrderGateway` (Epic 9 P0.12) — single choke-point validation regardless of which strategy issued the order. | Demoted; the existing pattern is correct |

The remaining findings below are accurate.

---

## Per-strategy reviews

### MA Crossover (`ma_crossover.py`)

**Verdict:** APPROVE_WITH_FIXES — logic correct; sizing and lifecycle hooks need attention.

#### HIGH

- **`get_position_size()` returns `float(self.config.trade_size)` instead of using `RiskSizedMixin`** — fixed lot count violates FTMO discipline (uncontrolled risk %). Mix in `RiskSizedMixin` and replace with `self.size_from_risk(...)`. (`ma_crossover.py:179,193`)

#### MEDIUM

- **`_prev_fast` / `_prev_slow` not reset in `on_stop`** — stop+restart without explicit reset replays stale EMA values, producing a false crossover on the first new bar. Override `on_stop` or call `self.on_reset()` from it. (`ma_crossover.py:100-109`)
- **`__post_init__` doesn't validate non-positive periods** — only `slow > fast` checked; `fast_period=0` passes. Add positive guards. (`ma_crossover.py:39`)

#### Strengths

- Crossover condition correctly handles touch-without-cross (equal values return NONE; tested at line 226).
- Regime declaration `[TRENDING_UP, TRENDING_DOWN]` is semantically correct.
- `on_reset` fully clears all mutable state.

#### Test coverage gap

- No test exercises a real `MACrossoverStrategy` instance — all signal tests replicate the logic in helper functions. If `generate_signal` diverges, tests won't catch it.
- Reversal double-order race (close + new entry on same bar) is untested.

---

### Supertrend (`supertrend.py`)

**Verdict:** APPROVE_WITH_FIXES — sound logic, missing ATR-zero guard.

#### MEDIUM

- **No ATR-zero guard before bracket submission** — a flat-open synthetic bar (H=L=C) produces `atr=0`, which `_validated_offset` rejects with `ValueError`, crashing the bar-processing loop. Add `if self._atr.value <= 0: log.warning(...); return` before `_submit_bracket_for_entry`. (`supertrend.py:132`)
- **Deferred `from nautilus_trader.indicators.volatility import AverageTrueRange` inside `__init__`** — slows repeated instantiation; if the cycle is real, fix via `TYPE_CHECKING` block.

#### LOW

- `bracket_strategy.py:95` broad `except Exception` should be `(KeyError, LookupError, AttributeError)`.

#### Strengths

- Signal logic matches canonical Pine Script formulation; first-bar `_prev_trend = None` correctly returns NONE.
- All 5 numeric config fields validated. Regime declaration `[TRENDING_UP, TRENDING_DOWN]` is correct.
- All four mixins actively used; MRO order clean.

#### Test coverage gap

- ATR-zero path entirely untested.
- Position-reversal close-then-reopen branch untested at integration level.

---

### Donchian Breakout (`donchian_breakout.py`)

**Verdict:** APPROVE_WITH_FIXES — one HIGH (latent CLOSE-signal bug), config validation gaps.

#### HIGH

- **`_execute_signal` override silently shadows `BaseStrategy._execute_signal` and never delegates `CLOSE`** — `generate_signal` doesn't currently emit `CLOSE`, but if a future session-filter or regime-kill-switch injects a `CLOSE` via `on_bar`, the override intercepts it before `BracketStrategyMixin._submit_bracket_for_entry` can check `is_flat`. Either delegate to `super()._execute_signal(signal)` for the CLOSE branch or document explicitly that this strategy never emits CLOSE and remove the dead branch. (`donchian_breakout.py:107`)

#### MEDIUM

- **`__post_init__` does not validate `sl_atr_mult < tp_atr_mult`** — config with `sl=5.0, tp=1.0` passes (R:R < 1). This gap exists across all five bracket strategies; fix in `BracketStrategyConfig` to inherit it. (`donchian_breakout.py:44`)
- **Only `channel_period=0` and `atr_period=-1` tested**; `sl_atr_mult <= 0` and `tp_atr_mult <= 0` branches are untested. (~40% validation coverage.)

#### Strengths

- Prior-band caching pattern (`_prev_upper` / `_prev_lower` updated before any early return) is the correct fix for the classic "bar always inside its own channel" footgun.
- Regime declaration `[TRENDING_UP, TRENDING_DOWN]` correct.
- Mixin composition clean, no diamond-inheritance state conflicts.

---

### RSI Mean Reversion (`rsi_mean_reversion.py`)

**Verdict:** APPROVE_WITH_FIXES — exit-priority parameterization hazard + missing `super()` call.

#### MEDIUM

- **`__post_init__` doesn't call `super().__post_init__()`** — silently bypasses `BracketStrategyConfig` parent validation (`sl_atr_mult`, `tp_atr_mult`, `risk_percent`). Add `super().__post_init__()` as the first line. (`rsi_mean_reversion.py:44-50`)
- **No minimum-spread guard on `oversold` / `exit_neutral` / `overbought`** — `oversold=0.3, exit_neutral=0.31` passes the strict-ordering check but creates a parameterization hazard: tiny RSI moves can re-enter immediately after exit. Add `if (exit_neutral - oversold) < 0.05 ...`. (`rsi_mean_reversion.py:44-50`)
- **`generate_signal` lacks `-> SignalType` return annotation.**

#### Strengths

- Exit-priority-before-entry (line 91-98) correctly prevents same-bar direction flip.
- Regime declaration `[RANGING]` is semantically tight.
- ATR multipliers (1:2 R:R) appropriate for MR.

#### Test coverage gap

- Boundary equality (`prev == oversold`, `rsi=0.301`) untested.
- `on_reset` clearing `_prev_rsi` untested.
- Registry assertion is comment-only ("Registry verified by successful import"); make explicit.

---

### Bollinger Mean Reversion (`bollinger_mean_reversion.py`)

**Verdict:** APPROVE_WITH_FIXES — squeeze guard + config upper bound + structural duplication with RSI MR.

#### HIGH

- **No squeeze / zero-width band guard** — `upper - lower == 0` produces no entries silently (looks like "no trade" rather than "broken state"). Add `if (upper - lower) < _MINIMUM_BAND_WIDTH: return SignalType.NONE` plus a one-shot warning. (`bollinger_mean_reversion.py:93`)
- **`num_std` upper bound not validated** — `num_std=20.0` passes; misconfigured YAML produces zero-trade backtests with no error. Add `if self.num_std > 5.0: raise ValueError(...)`. (`bollinger_mean_reversion.py:43`)

#### MEDIUM

- **Strict-less-than entry condition misses exact-touch** — docstring says "touches/crosses" but code only handles crosses. Change to `close <= lower` / `close >= upper` to match intent. (`bollinger_mean_reversion.py:93-96`)
- **`on_reset` doesn't call `super().on_reset()`** — same bug as RSI MR.

#### Cross-strategy notes

- **Near-total structural duplication with `RSIMeanReversionStrategy`** — `__init__`, `on_start`, `on_reset`, `_execute_signal`, mixin composition, ATR multiplier defaults, `set_position_sizer` call are character-for-character identical. Only `generate_signal` differs. Strong candidate for a `MeanReversionMixin` (or shared base class) before any new MR variant lands.

#### Strengths

- Regime declaration `[RANGING]` correct.
- Exit-before-entry priority prevents same-bar race.
- ATR multipliers consistent with RSI MR (clean cross-strategy comparison).

---

### Opening Range Breakout (`orb.py`)

**Verdict:** APPROVE_WITH_FIXES — config guards missing, DST untested.

#### HIGH

- **`__post_init__` doesn't enforce `session_open < session_close`** — `open_hour=16, close_hour=8` silently creates an overnight window; ORB is documented as intraday-only. (`orb.py:52`)
- **Minute fields not bounds-checked** — `session_close_minute=90` raises a cryptic `datetime.time` error deep in execution; `opening_range_minutes` has no upper bound. Add `0 <= minute <= 59` and an upper sanity bound on OR length. (`orb.py:52`)

#### MEDIUM

- **`generate_signal` is 67 lines** — borderline over the 50-line cap. Split into `_accumulate_opening_range()` and `_evaluate_breakout()`.
- **`_bar_timestamp` uses raw `// 1_000_000_000`** — no inline comment explaining the Nautilus nanosecond convention.

#### LOW

- **No DST transition test** — the docstring says "DST-safe via SessionFilterMixin" but the test suite has no BST→GMT case. Mixin is well-tested in isolation; ORB-level coverage is missing.

#### Strengths

- Half-open OR window semantics correct (`elapsed >= opening_range_minutes` terminates OR; boundary bar evaluates breakout, not accumulation). The most common ORB bug is handled.
- `_reset_session_state` cleanly separated.
- Regime declaration `regimes=[]` (Phase 1 explicit opt-out) is unambiguous; Phase 2 wiring is a one-liner (`[HIGH_VOLATILITY]`).

---

## Architecture (cross-cutting)

**Verdict:** APPROVE_WITH_FIXES — composition spine sound; one HIGH (registry isolation), three MEDIUMs.

### Strengths

- **Composition over inheritance is dominant** — five of six strategies are flat `BaseStrategy + 3-4 mixins`. Single inheritance depth, no diamond. Largest file (`base_strategy.py`) is 380 lines, comfortably under the 800 cap.
- **Regime layer is genuinely additive** — `RegimeAwareRouter` wraps `StrategyDataRouter` via a Protocol; reuses `_route_bar_to_account` as the per-account seam; preserves the redis callback signature. Strategies were not touched in Epic 11.
- **Sizing has a single auditable seam** — `RiskBasedPositionSizer.calculate_lot_size` returns `Decimal("0")` rather than promoting to `min_lot_size`; both `_submit_bracket_for_entry` and `_submit_bracket_order` honor "skip on non-positive qty" with WARNING.
- **Audit-before-routing is explicit** — `RegimeAwareRouter.route_bar_async:106` matches the FTMO double-entry discipline.
- **Frozen configs and stateless mixins** — `ATRStopMixin` and `SessionFilterMixin` are pure static methods; `RiskSizedMixin` holds only an injected sizer reference.

### Findings

#### HIGH

- **`StrategyRegistry._strategies` and `_strategy_regimes` are class-level mutable dicts with no test isolation guarantee.** `clear()` exists but is opt-in. Two desync risks: (1) `_normalise_regimes` raising after `_strategies[name] = ...` leaves the maps drifted; (2) backtest harness running multiple configs in one process hits `"already registered"` on re-import. Fix: make registration idempotent (compare-and-replace if same class object), wrap dict writes in a single transactional block, add an autouse pytest fixture snapshotting both dicts. (`registry.py:57-58`)

- **`BracketStrategyMixin` has 10+ implicit host-class requirements** verified only by scattered `# type: ignore[attr-defined]`. Adding a 7th bracket strategy that forgets a mixin (e.g. omits `RiskSizedMixin`) fails at first signal, not at construction. Fix: extract a `BracketHost` `Protocol` and have `BracketStrategyMixin` declare `self: BracketHost`. (`bracket_strategy.py:54-66`)

- **`route_bar` schedules `asyncio.create_task` assuming a running loop.** A future synchronous backtest harness calling `route_bar` outside an async context raises `RuntimeError: no running event loop` and the bar is silently dropped. The docstring acknowledges this. Fix: assert a running loop at construction, or expose only `route_bar_async`. (`regime_routing.py:121`)

- **`ma_crossover._go_long`/`_go_short` silently override and bypass the `is_flat` guard** from `base_strategy.py:234,250`. Reversal logic is open-coded in `_execute_signal`. Fix: factor reversal into the base as `_reverse_to(side)` template method, or make `is_flat` a separately-overridable hook. (`ma_crossover.py:170-196`)

#### MEDIUM

- **`_calculate_atr_stop` and `_in_session` are convenience proxies on `BaseStrategy`** that duplicate the mixin static methods. Drift risk if one is updated. Remove the proxies; require the mixin where the math is needed. (`base_strategy.py:280-301`)

- **`_read_account_balance` does `Decimal(str(balance.as_double()))`** — the `str(float)` round-trip violates `sandboxed-domain.md`'s rule "balance reads must come from Redis HWM cache (`account:{id}:snapshot`)". The cache is `Decimal`-native and avoids the float crossing. Reroute. (`bracket_strategy.py:101-109`)

- **`data_router.py:117,156` bare `except Exception` swallows strategy errors with only a log.** A misbehaving strategy silently drops bars indefinitely. Add a per-account error counter and circuit-break after N consecutive failures. (`data_router.py:117,156`)

#### LOW

- `BaseStrategy` properties `instrument` and `account` lack return-type annotations. (`base_strategy.py:99-114`)
- `data_router.py:130` `route_bar_async` just calls the sync version — drop one or make the async version actually async.
- `register_strategy` mutates global state at *import* time; convenient but couples discovery to import side-effects.

### Anti-patterns flagged

1. **Implicit-mixin-contract / "duck-typed inheritance"** — `BracketStrategyMixin` works by convention, not contract. (HIGH above.)
2. **Global mutable singleton** — `StrategyRegistry` class-level dicts mutated by import-time decorators. Test isolation opt-in. (HIGH above.)

### Refactor recommendations (priority-ordered)

1. **Promote the implicit `BracketStrategyMixin` contract to a `BracketHost` Protocol** — `Self: BracketHost`, removes all `# type: ignore[attr-defined]`, fails fast at static-check time when the mixin set is incomplete on a new strategy.
2. **Make `StrategyRegistry` instance-based** — keep a module-level default singleton for back-compat, expose `StrategyRegistry()` for tests and the future backtest harness which will want distinct strategy sets per run.
3. **Route `_read_account_balance` through the Redis HWM snapshot** per the FTMO domain rule.
4. **Lift `_execute_signal` reversal logic into `BaseStrategy`** as a `_reverse_to(side, qty_fn)` template method.
5. **Add an MRO/composition smoke test** — for each registered strategy, assert (a) the expected mixin set is present, (b) `super().__init__` resolves, (c) all `BracketHost` Protocol attributes resolve.
6. **Extract `MeanReversionMixin`** — share the identical infrastructure between RSI MR and Bollinger MR.

### Phase 2 (HMM regime classifier) impact

Two footguns surface:

- **Strategy `regimes=[...]` declarations are static enum sets.** An HMM emitting regime *probabilities* loses information when collapsed to a hard state. Pre-empt by making the regime allow-list a `RegimeAdmission` Protocol now (with `frozenset` as the trivial impl) so Phase 2 ships a new admission type rather than reworking the registry.
- **HMM warmup is 100x longer than rule-based feature warmup.** Today's `extractor.update(bar) is None → return` silently drops bars during warmup; document or change this before HMM lands.

Nothing in the strategy layer itself blocks Phase 2 — the regime concern is fully isolated in `regime_routing.py` and `register_strategy(regimes=)`. Good architecture.

---

## Test Coverage Matrix

### Per-strategy

| Strategy | Unit (lines / cases) | Integration | Backtest | Signal up | Signal down | Warmup | Param valid. | Mixin integ. | Regime decl. | E2E w/ router |
|---|---|---|---|---|---|---|---|---|---|---|
| ma_crossover | 544 / 31 | smoke + compliance + orchestration + rule_engine_flow | smoke | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| supertrend | 166 / 12 | bracket_strategies_smoke | bracket_strategies_smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| donchian_breakout | 158 / 11 | bracket_strategies_smoke | bracket_strategies_smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| rsi_mean_reversion | 128 / 10 | bracket_strategies_smoke | bracket_strategies_smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| bollinger_mean_reversion | 107 / 8 | bracket_strategies_smoke | bracket_strategies_smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| orb | 192 / 13 | bracket_strategies_smoke | bracket_strategies_smoke | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |

### Shared infrastructure

| Module | Test file (lines / cases) | Notable gaps |
|---|---|---|
| base_strategy.py | 358 / 27 | No multi-strategy composition tests; no error handling for invalid bar data |
| bracket_strategy.py | 88 / 7 | **SMOKE-ONLY** — actual bracket order submission, price precision untested |
| registry.py | 340 / 29 | Unregistered lookup errors in production context untested |
| account_binding.py | 257 / 12 | No error recovery on strategy instantiation failure |
| data_router.py | 413 / 22 | No regime-router integration; no rate-limit / backpressure |
| risk_based_position_sizer.py | 297 / 22 | No live account-balance integration |
| ATRStopMixin | 128 / 11 | Minimal coverage; no FX bid/ask tick edge cases |
| RiskSizedMixin | 88 / 4 | **SMOKE-ONLY** — no actual sizing scenarios |
| SessionFilterMixin | 168 / 15 | No multi-session transition within a backtest run |
| regime_routing.py | 699 / 20 | No live MT5 testing; no asymmetric thresholds |

### Coverage gaps (priority-ordered)

1. **E2E router integration: 0 / 6 strategies** — none have tests exercising bar→RegimeAwareRouter→StrategyDataRouter→strategy. Unit tests for each component exist; no cross-layer integration verifies regime-based filtering or audit trail before routing.
2. **Bracket execution path: smoke-only** — five strategies share `_submit_bracket_for_entry`; no test exercises tick-rounding, ATR-zero, or position-reversal end-to-end.
3. **ma_crossover signal generation never exercises a real strategy instance** — all tests replicate logic in helpers.
4. **Position-size scaling with live balance** — sizer tested with mocks; no integration test for zero-balance / connection-error mid-bar.
5. **SessionFilterMixin multi-session behavior** — boundary logic tested, but no consecutive 24h backtest across session boundaries.
6. **DST transition** — `SessionFilterMixin` well-tested in isolation, but no ORB-level case for BST→GMT.

### Notable observations

- **ma_crossover is over-tested for its surface (544 lines for two EMAs and one crossover check)** — most tests would belong in `BaseStrategy` tests. Flag for de-duplication when extracting `BaseStrategy` test fixtures.
- **Bracket-strategy integration is smoke-only** — `test_bracket_strategies_smoke.py` runs 500 synthetic bars and asserts only that `BacktestResult` is well-formed. Trade counts, P&L, signal sequences are not asserted. Contrast with `test_backtest_smoke.py` (ma_crossover) which includes daily-loss-limit rule-engine integration.
- **Regime declarations are declared but the rejection path is not exercised** — four strategies declare `regimes`, but no test verifies that a BUY from supertrend during HIGH_VOLATILITY is actually not routed; the regime_aware_router unit tests use stub inner routers.

---

## Recommended next moves (priority-ordered)

The user has already indicated the next epic will focus on backtesting. The list below is ordered for that context — what to fix before / during the backtest epic vs. what can wait.

### Land before backtest epic

1. **Cross-strategy validation invariants** — add `sl_atr_mult < tp_atr_mult` in `BracketStrategyConfig.__post_init__`. Add `super().__post_init__()` call to RSI MR and Bollinger MR. Add minute-field bounds + `session_open < session_close` to ORB. Add `num_std` upper bound to Bollinger MR. Add positive-period guards to MA Crossover. **One PR, ~30 lines, all six configs.**
2. **Squeeze + ATR-zero guards** — `BollingerMeanReversionStrategy` (zero-width band), `SupertrendStrategy` (`atr=0` flat-bar). Both are silent failure modes that will misreport in backtests. **One PR, ~10 lines per strategy + tests.**
3. **`MeanReversionMixin` extraction** — backtest epic will likely add new MR variants; landing the mixin before they're written keeps the pattern clean. **One PR, ~80 lines moved + 2 strategies updated + tests preserved.**

### Land during backtest epic (since the harness will exercise these paths)

4. **Bracket execution coverage** — add tests for tick-rounding, ATR-zero, position-reversal. Use the backtest harness fixtures.
5. **E2E router integration tests** — pick 1-2 strategies and assert regime-rejection actually filters bars in the live router.
6. **`__post_init__` regression tests** — one deliberately-invalid config per strategy, asserting `ValueError`. Lightweight defense against the kind of "validator regression" the architect-reviewer (incorrectly) suspected — making the tests explicit removes the ambiguity.

### Land after backtest epic (architectural cleanup)

7. **`BracketHost` Protocol** — refactor `BracketStrategyMixin` to declare its host contract. Removes all `# type: ignore[attr-defined]`.
8. **`StrategyRegistry` instance-based** — supports per-backtest-run distinct strategy sets.
9. **Route `_read_account_balance` through Redis HWM snapshot** — aligns with `sandboxed-domain.md`.
10. **Lift reversal logic into `BaseStrategy._reverse_to`** — removes the `ma_crossover` `is_flat` bypass.

### Defer until Phase 2 (HMM)

11. **`RegimeAdmission` Protocol** — replace the `frozenset[RegimeState]` allow-list with a `(probabilities) -> bool` admission type so HMM probabilities don't have to collapse to hard states.

---

## References

- Epic 11 context: `docs/epic-11-context.md`
- Architecture: `docs/architecture.md` (post-Epic 11 v3.2)
- Project rules: `.claude/rules/python/`, `.claude/rules/common/`, `.claude/rules/database/audit.md`
- Regime classifier research: `docs/research/regime-classifier.md`, `docs/research/regime-classifier-architecture.md`
- This review's reviewer agent IDs (for follow-up if needed):
  - python-reviewer × 6: `aaa7c9cfd8876aa13`, `aa598f5ae3106bc70`, `a67ad3c2806824844`, `ad750a2e8eb65ef53`, `aeb82eada4aec569a`, `adf82c9161cfff859`
  - architect: `ad4d832129a9f636f` (CRITICAL claim incorrect; see "Reviewer accuracy notes" above)
  - Explore (coverage): in-line agent (no persistent ID)
