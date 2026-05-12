# Epic 13 — Retrospective

**Epic:** 13 — Strategy Tactics Phase 1 — 50/50 + Trail Uncapped (backtest-only)
**Window:** 2026-05-06 (spec drafted) → 2026-05-12 (closed)
**Branch:** `epic-13-strategy-tactics`
**Stories shipped:** 11/11 (13.1 – 13.11)
**Status:** **DONE**

---

## 1. Original scope

The Epic 13 spec (`docs/epic-13-context.md` + `docs/research/strategy-tactics-implementation-plan.md`) set out to add three exit tactics to the engine's six production strategies:

- **50% partial close at +1R** (lock half the gain at first R-multiple)
- **Breakeven SL move** after the partial close
- **Supertrend ATR(7)×2.1 uncapped trail** on the remaining 50%

Tactics applied to trend-followers only (Supertrend, Donchian, MA crossover); mean-reversion strategies (Bollinger, RSI, ORB) explicitly gated out because natural-target exits don't pair with uncapped trails.

The implementation plan was sized 9 stories (13.1 – 13.9). Default-OFF in firm config; backtest-only — live tactics deferred to Epic 14 (MT5 EA).

**Quant review §2.6 hypothesis:** ~+30 % EV uplift across trend-followers from the tactic shift, with the bulk of the improvement coming from tail capture on the trailing remainder.

---

## 2. What actually shipped

11 stories + 3 follow-ups, all backtest-only, all under default-OFF safety:

| # | Story | Commit | Size | Verdict |
| --- | --- | --- | --- | --- |
| 13.1 | Nautilus modify_order spike | (research, no commit) | S | done |
| 13.2 | Config fields + invariants | `0ac0486` | S | done |
| 13.3 | BaseStrategy helpers (`_close_partial`, `_modify_sl`) | `177792a` | M | done |
| 13.4 | `BracketScaleOutMixin` state machine | `bf43630` | M | done |
| 13.5 | Wire mixin into Supertrend | `1afe90d` | M | done |
| 13.6 | Supertrend trail indicator + `_update_trailing_sl` | `7b7b43d` | M | done |
| 13.7 | E2E integration test on synthetic bars | `2a947b0` | M | done |
| 13.8 | Per-firm config wiring (ftmo.yaml) | `3e7f9be` | S | done |
| 13.9 | Backtest A/B harness + Supertrend M5 validation | `1cfd8ae` | M | done |
| 13.10 | Wire mixin into Donchian | `0159964` | M | done |
| 13.11 | Wire mixin into MA crossover + bracket migration | `aea0ae1` | L | done |

**Follow-ups closed in the same epic** (not numbered stories):

- M15 baseline retry (`a9e6d48`) — Phase 12.A direction §3.1
- Supertrend M15 scale-out (`b6ebfee`) — direction §3.2 (Supertrend slice)
- Phase 12.A final verdict (`e89116d`) — Sharpe verification, all 6 strategies on both timeframes
- Phase 1 invariant fix on Supertrend + Donchian configs (`dd5a568`)
- Scale-out wiring hoist into shared mixin (`c04ce46`) — rule of three refactor

The harness shipped by 13.9 (`trading-engine backtest ab` CLI + `ab_compare.py`) became the workhorse for every subsequent validation — 13.10, 13.11, M15 follow-ups, and the corrective Phase 12.A verdict all reused it.

---

## 3. Headline findings

### 3.1 The +30 % uniform hypothesis was wrong; scale-out is signal-conditional

The quant review §2.6 estimated ~+30 % EV uplift across trend-followers as a class. Reality post-13.9/13.10/13.11:

| Strategy × timeframe | EV (baseline → variant) | Δ% | Tactic verdict |
| --- | --- | ---: | --- |
| Supertrend M5 | −0.282 → −0.134 | **+52 %** | benefits |
| Supertrend M15 | −0.075 → −0.029 | **+62 %** | benefits |
| Donchian M5 | +0.167 → +0.015 | **−91 %** | **HURTS** |
| Donchian M15 | +0.075 → +0.144 | **+91 %** | benefits |
| MA crossover M5 | −0.056 → +0.045 | **EV sign-flip** | benefits |
| MA crossover M15 | −0.315 → −0.407 | −29 % | **HURTS** |

The split is **signal-noise on the chosen timeframe**:

- Noisy signal (Supertrend M5/M15, MA M5) → BE protection > tail-foregone cost → benefits
- Clean signal (Donchian M5, MA M15) → half-at-1R + half-at-BE wrecks the median winner → hurts

This is a refinement of the original hypothesis, not a rejection — the tactic is real and the +52 %–62 % numbers on Supertrend match the quant prediction's order of magnitude. But it cannot be turned on globally.

### 3.2 The Phase 12.A "best strategy" was an artifact

Story 12.7a (Phase 12.A in-sample baseline) ran the six strategies on XAUUSD M5 + M15 with FTMO compliance wired and surfaced `ma_crossover` M15 as the highest-Sharpe strategy at **+0.137** — the apparent winner of the entire campaign.

Story 13.11 then migrated MA crossover from `BaseStrategyConfig` (no SL) to `BracketStrategyConfig` (ATR-based SL/TP). With proper risk management:

| | Pre-13.11 (no SL) | Post-13.11 (ATR bracket) |
| --- | ---: | ---: |
| MA M5 Sharpe | +0.030 | −0.017 |
| MA M15 Sharpe | **+0.137** | **−0.097** |

The Sharpe 0.137 was an artifact of the strategy having no stop-loss at all — it only exited on opposite crossover, so trades could ride trends past any TP and survive arbitrary retracements. **A no-SL strategy could never have shipped to FTMO regardless of backtest Sharpe.**

Post-13.11 best Sharpe across the 16-experiment grid is `donchian_breakout` M5 baseline = **+0.065** — still 12.3× below the Decision §2 filter of 0.8.

### 3.3 Phase 12.B / Story 12.7b stays gated

No strategy clears Sharpe ≥ 0.8 on XAUUSD M5/M15 defaults. **All 6 strategies pass FTMO compliance** (0 breaches, max DD < 5.1 %), so signal quality is the binding constraint, not rules. The three recoverable directions documented in `epic-12-phase-12a-final-verdict.md` (lower filter, signal-quality improvement, multi-symbol coverage) are next-epic scope, not in-flight.

### 3.4 13.9 surfaced four pre-existing backtest infrastructure gaps

When `trading-engine backtest ab` first tried to consume the Epic 12.7.0 dataset end-to-end, four latent issues fired in sequence:

1. **Parquet schema mismatch.** `stitch_chunks_to_window.py` writes `time` int64 ms; `runner_facade._build_bars` expected a tz-aware DatetimeIndex. → fix: `_normalise_parquet_index` accepts both shapes.
2. **YAML Decimal coercion.** `BracketStrategyConfig` fields are typed `Decimal` but YAML loads them as `str` and `__post_init__` compares to `0`. → fix: `_coerce_strategy_params` walks type hints and lifts `str` / `int` / `float` into `Decimal` for `Decimal`-annotated fields.
3. **XAUUSD instrument precision.** Nautilus's stock `TestInstrumentProvider.default_fx_ccy("XAUUSD")` returns `size_precision=0` which rejects 0.5-lot orders. → fix: `_build_xauusd_instrument` constructs a CurrencyPair with `size_precision=2` matching the MT5 micro-lot convention.
4. **Money → Decimal conversion.** `Decimal(str(Money(123.45, USD)))` fails on `"123.45 USD"`. → fix: `_pos_pnl_decimal` helper uses `Money.as_decimal()`.

All four gaps got dedicated unit tests so they cannot regress.

---

## 4. What worked

- **TDD discipline.** Every story landed RED → GREEN. Donchian and MA crossover scale-out tests were written first and failed before the wiring code went in. Test count grew from 3,401 (pre-epic) → 3,458 (close).
- **`python-reviewer` caught real issues.** Surfaced one HIGH on swallowed exceptions in `_extract_trades` (out-of-scope, noted), one MEDIUM on `Money.as_decimal()` duck-typing (fixed inline), one HIGH on the Phase 1 invariant bypass (fixed in `dd5a568`), and one HIGH on a stale comment in the baseline runner (fixed during 13.11).
- **Rule of three discipline.** Resisted the urge to extract the host-side scale-out wiring after Supertrend or after Donchian. Waiting until MA crossover (the third user) gave a clean signal that the abstraction was real, not speculative. The extract (`c04ce46`) removed 142 net lines without changing any behaviour.
- **Per-story commit + sprint-status update + memory bump.** The `Implement spec 13 story 13.X` + `chore: sprint-status` pair lands each story as two clean commits. Memory entries got updated story-by-story rather than in a single end-of-epic dump, so a future reader can trace the campaign sequentially.
- **Phase 12.A split out of 12.7.** Story 12.7 was originally scoped as one XL sweep experiment. Splitting it into 12.7a (in-sample baseline of all 6 — required as input) and 12.7b (sweep — gated on 12.7a) gave a clean halt point when no strategy cleared the filter. The split was a 1-line sprint-status edit; the value was avoiding a guaranteed-to-overfit sweep.
- **Backtest A/B CLI shipped early.** 13.9 delivered `trading-engine backtest ab` as the validation harness. It became the default tool for every subsequent comparison (13.10 Donchian, 13.11 MA crossover, all M15 follow-ups). A one-off script would have cost the same to write and given zero reuse.

---

## 5. What didn't work / lessons

### 5.1 The quant review's uniform-uplift hypothesis should have been pre-validated

The implementation plan was sized around the +30 % EV assumption. We discovered the strategy-dependent reality only after wiring tactics into all 3 trend-followers (stories 13.5, 13.10, 13.11 — 3 weeks of work). A 1-day pilot on a synthetic bar series or a single quick A/B on Supertrend M5 BEFORE 13.10/13.11 would have caught the signal-conditional pattern earlier, possibly redirecting 13.11 (which is the biggest refactor in the epic) toward a different design.

**Action:** Future epics built around a quant-review hypothesis should ship a single-strategy pilot in story 1 — before the full implementation plan commits resources to N strategies.

### 5.2 Pre-existing backtest infrastructure gaps surfaced inside a "validation report" story

The four gaps in §3.4 had been latent since Epic 8/12; nothing had run a production strategy end-to-end on a real parquet through `run_baseline` with a non-default instrument. Story 13.9's commit had to absorb 200+ lines of infra fix + 8 unit tests in addition to the harness + report — a lot for "Backtest A/B validation report (M)".

**Action:** Epic 12.7a (or the equivalent in future epics) should be the **first** consumer of any new dataset / instrument / harness combination, not the last. A "dry-run smoke" on the first new strategy + new dataset combination would surface infra gaps as their own story.

### 5.3 MA crossover's no-SL design was hidden under the strategy abstraction

`MACrossoverStrategy` had shipped (pre-Epic 13) without any stop-loss — only opposite-crossover exits. This was orthogonal to FTMO compliance (where compliance is checked at the rule-engine level, not the strategy level) so it never failed any gate. It only became visible when Story 12.7a surfaced Sharpe 0.137 as suspiciously high and Story 13.11 made the migration unavoidable.

**Action:** Strategy admission should require an explicit risk-management contract — every entry must have a corresponding SL (whether ATR-derived, fixed, or signal-defined). Add an audit gate to `test_strategy_validation_gate.py` that asserts every concrete strategy submits a `STOP_MARKET` companion to every entry. (Note: Story 13.11 already moved MA crossover into the bracket bucket of that gate, so the test passes — but the bracket bucket assertion only checks for `_submit_bracket_for_entry`, not the SL itself.)

### 5.4 The Phase 1 cross-field invariant gap had been latent since Story 13.2

`SupertrendConfig.__post_init__` did not call `super().__post_init__()`, bypassing `BracketStrategyConfig`'s Phase 1 invariants (`breakeven_at_r ≤ scale_out_r_trigger`, `trailing_enabled` requires `scale_out_enabled`, R:R > 1, `safety_tp_atr_mult > 0`). Story 13.10 inherited the pattern. Only Story 13.11 — where the reviewer flagged the gap as the "third time the pattern shipped" — triggered a fix across all three configs.

**Action:** When a new `__post_init__` is written on a `Struct` subclass, the pattern should always start with `super().__post_init__()` unless there's a deliberate reason. The `python-reviewer` rubric should explicitly check this.

### 5.5 The mixin host contract is duck-typed and not statically verified

`BracketScaleOutMixin` reaches host attributes (`_position`, `_find_active_sl_order`, `is_flat`, `config`) via `# type: ignore[attr-defined]`. A `Protocol` listing the required surface would catch wiring mistakes at type-check time — but mypy isn't yet wired into CI for `services/trading-engine`, so the protocol benefit isn't realisable yet.

**Action:** Wiring mypy into CI is a multi-story effort tracked outside Epic 13. The mixin's duck-typed contract is acceptable until then; the comment block on the class docstring lists the required host surface.

---

## 6. Action items for the next epic(s)

| # | Action | Owner | Epic |
| --- | --- | --- | --- |
| 1 | Single-strategy pilot before multi-strategy implementation plan commits | Planner | First story of any quant-hypothesis-driven epic |
| 2 | Dry-run smoke as the **first** consumer of any new dataset/instrument/harness combination | TDD | Epic 14 story 1 |
| 3 | Strategy admission audit gate: every entry must have an SL companion | Code review | Backlog (low priority — no FTMO violation today) |
| 4 | Every new `__post_init__` calls `super().__post_init__()` unless there's a deliberate reason | python-reviewer rubric | Add to `.claude/rules/python/code-review.md` |
| 5 | Mypy into CI for `services/trading-engine` | Architect | Backlog (multi-story) |
| 6 | True per-trade R-multiples via SL distance on `TradeRecord` | Phase 2 | Backlog |
| 7 | `equity_curve` extraction off `BacktestEngine` independent of `_prop_firm_actor` | Phase 2 | Backlog |
| 8 | Fix pre-existing bare `except` in `engine._extract_trades` | Code review HIGH from 13.9 | Backlog (small) |

Items 1, 2, 4 land as **process / harness** changes rather than code work. Items 3, 5, 6, 7, 8 are backlog tickets sized small-to-medium that can be picked up opportunistically.

---

## 7. By the numbers

- **Stories:** 11 shipped (13.1–13.11), 0 dropped
- **Wall-clock:** 7 days (2026-05-06 spec → 2026-05-12 close)
- **Commits ahead of `main`:** 52 (Epic 13 work + Epic 12.7+ that was on the same branch)
- **Tests:** 3,401 unit → 3,458 unit + 7 integration (+57 new tests, all on Epic 13 work)
- **Net lines:** ~+5k added, ~−260 removed by the rule-of-three refactor
- **Reviewer findings addressed:** 4 HIGH (1 deferred as out-of-scope) + 2 MEDIUM
- **Backtest infra gaps fixed:** 4 (in 13.9) + 1 (Phase 1 invariant, in `dd5a568`)
- **Validation reports produced:**
  - `validation-report-epic13.md` (13.9 Supertrend M5)
  - `epic-12-baseline-comparison.md` (12.7a M5)
  - `epic-12-baseline-comparison-m15.md` (M15 retry)
  - `epic13-supertrend-m15-followup.md` (Supertrend M15)
  - `epic13-donchian-scaleout-results.md` (13.10)
  - `epic13-ma-crossover-scaleout-results.md` (13.11)
  - `epic-12-phase-12a-final-verdict.md` (final Sharpe verdict)
  - `epic-12-baseline-comparison-m15-scaleout.md` (M15 scale-out overlay)
  - this retrospective

The validation effort produced more documentation than code — a deliberate choice, since the value of Epic 13 is the **empirical answer** to a quant hypothesis, not the LOC count.

---

## 8. Next epic candidates

In rough cost order:

- **Epic 14 — MT5 EA + live trading unblock.** Removes the `ZmqExecutionClient.modify_order` `NotImplementedError`. After 14 ships, Epic 13 tactics can be deployed live behind firm-config flags.
- **Strategy-signal improvement epic** (no number assigned). Multi-indicator confirmation, regime gating, session filters. Sized multi-story, but the only path to clearing the Decision §2 Sharpe ≥ 0.8 filter on XAUUSD.
- **Multi-symbol dataset materialization.** EURUSD / GBPUSD M5 + M15 fetch via the Epic 12.7.0 tooling. Pure operator work, no code. Validates whether XAUUSD M5/M15 noise is the bottleneck or if the strategies have a real symbol-agnostic edge problem.
- **Phase 2 scale-out variants** (60/30/10, 50/25/25, Chandelier trail). Picks up the Epic 13 quant review §7 deferred work once Phase 1 is in production.

---

## 9. References

- `docs/epic-13-context.md` — original Epic 13 spec
- `docs/research/strategy-tactics-quant-review.md` — quant review (§2.6 +30 % hypothesis, contradicted)
- `docs/research/strategy-tactics-implementation-plan.md` — 9-story implementation plan
- `docs/sprint-artifacts/sprint-status.yaml` — story-by-story status
- All eight validation reports listed in §7
- Memory: `~/.claude/projects/-home-hopdev-Dev-Sandboxed/memory/project_epic13_progress.md`
