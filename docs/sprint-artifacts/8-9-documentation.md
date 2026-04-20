# Story 8.9: Documentation + Bracket Refactor + Debt Cleanup

Status: Backlog

## Story

As a **maintainer of the Sandboxed trading engine**,
I want **the 5 bracket-order strategies to share one base class, the
known Epic 8 debt items resolved, and backtest usage documented end to
end**,
So that **future strategy additions don't duplicate boilerplate, the
ORB session logic is correct on M15+, and newcomers can run a sweep
without reverse-engineering the codebase**.

## Acceptance Criteria

1. **AC1 — `BracketStrategyMixin` collapses per-strategy duplication**:
   `src/strategies/bracket_strategy.py` exposes
   `BracketStrategyConfigMixin` (fields: `sl_atr_mult`, `tp_atr_mult`,
   `risk_percent`, `pip_size`, `pip_value_per_lot`, `atr_period`) and
   `BracketStrategyMixin` with methods
   `_last_bar() -> Bar | None`,
   `_read_account_balance() -> Decimal`,
   `_compute_bracket_params(...)`,
   `_submit_bracket_for_entry(...)`. Supertrend, Donchian, RSI MR,
   Bollinger MR, ORB inherit from the mixin and drop the local copies
   (~60 LoC each). Total LoC under `src/strategies/` drops by ≥250.

2. **AC2 — `initial_balance_fallback` removed**: The config field is
   deleted from all 5 strategy configs + YAML presets. When the
   portfolio returns no account, `_read_account_balance` returns
   `Decimal("0")` (not a hardcoded fallback). The sizer already treats
   `Decimal("0")` as "insufficient capital" and skips the trade — so
   the behavioural change is: no more silent $100k lie, misconfigured
   runs surface as zero-trade runs rather than phantom-balance runs.

3. **AC3 — ORB boundary bar fix**: The ORB opening-range window is
   **half-open** `[session_open, session_open + opening_range_minutes)`.
   The bar at exactly `elapsed == opening_range_minutes` is **not**
   added to the OR high/low; instead it marks the OR complete and is
   eligible for breakout evaluation. Regression test asserts that on
   a 30-minute OR with M15 bars, only 2 bars contribute (08:00, 08:15),
   not 3.

4. **AC4 — Integration smoke tests for all strategies**:
   `tests/integration/backtesting/` has one smoke test per strategy
   (Supertrend, Donchian, RSI MR, Bollinger MR, ORB) that runs the
   strategy through the full `run_backtest` facade on 500 synthetic
   trending bars and asserts `BacktestResult` well-formed, equity curve
   populated, no Python exceptions raised. Each completes in <10 s.

5. **AC5 — HTML report writer**: `src/backtesting/reports/html_writer.py`
   exposes `write_html_report(result: BacktestResult, path: Path)`.
   Output is a single-file HTML document with:
   - Summary metrics table (strategy, window, balance, net PnL, trade
     count, breach count, profit_factor, sharpe, max_dd_pct)
   - Inline SVG equity curve (no external assets, no JS)
   - Trade table (first 100 rows)
   - Breach table if any
   Deterministic output — same `BacktestResult` yields byte-identical
   HTML.

6. **AC6 — Runbook**: `docs/runbooks/backtesting.md` covers
   - Prerequisites (uv install, TimescaleDB optional, Parquet cache
     location)
   - Authoring a `BacktestJobConfig` YAML (example + field glossary)
   - `trading-engine backtest run` walkthrough
   - `trading-engine backtest sweep` walkthrough (grid + random)
   - `trading-engine backtest walkforward` walkthrough
     (anchored + rolling)
   - Reading the HTML report
   - Common errors + fixes
   Runbook is ≤ 400 lines of Markdown with copy-pasteable commands.

7. **AC7 — Architecture.md backtest section**: `docs/architecture.md`
   gains a "Backtest framework" section that documents the
   `BacktestRunner → run_backtest facade → ParameterSweep / WalkForward
   → CLI` layering, with the rationale preserved from
   `docs/epic-8-context.md` decisions 1-7.

8. **AC8 — No regression**: Full unit suite (`pytest -m "not
   integration"`) passes. All Epic-8 integration smoke tests pass.
   Ruff clean. Metrics for ORB on an existing fixture may change ≤5 %
   due to AC3 — documented in the story body below.

## Tasks

### Task 1: Story doc + status
- [x] Create this file
- [ ] Update `docs/sprint-artifacts/sprint-status.yaml` → 8-9 `in-progress`

### Task 2: `BracketStrategyMixin` + refactor
- [ ] `src/strategies/bracket_strategy.py` with mixin + config mixin
- [ ] Refactor Supertrend, Donchian, RSI MR, Bollinger MR, ORB
- [ ] Remove `initial_balance_fallback` from all 5 configs + YAML
      presets under `configs/strategies/`
- [ ] Update existing unit tests that reference
      `initial_balance_fallback` (grep then fix)
- [ ] Tests: new `test_bracket_strategy_mixin.py` asserts
      `_read_account_balance` returns `Decimal(0)` on portfolio miss

### Task 3: ORB boundary bar fix
- [ ] Tighten the boundary check in `src/strategies/orb.py` so the
      bar at `elapsed == opening_range_minutes` does not contribute
      to OR high/low
- [ ] Regression test in `tests/unit/test_orb_strategy.py` (or the
      equivalent ORB test file) asserting the M15 scenario

### Task 4: Smoke tests for 4 strategies
- [ ] `tests/integration/backtesting/test_supertrend_smoke.py`
- [ ] `tests/integration/backtesting/test_donchian_smoke.py`
- [ ] `tests/integration/backtesting/test_rsi_mr_smoke.py`
- [ ] `tests/integration/backtesting/test_bollinger_mr_smoke.py`
- [ ] `tests/integration/backtesting/test_orb_smoke.py`

### Task 5: HTML report writer
- [ ] `src/backtesting/reports/__init__.py` + `html_writer.py`
- [ ] Unit test `tests/unit/test_html_writer.py` — content + determinism

### Task 6: Runbook + architecture.md
- [ ] `docs/runbooks/backtesting.md`
- [ ] `docs/architecture.md` — Backtest framework section added

### Task 7: Review + commit
- [ ] Full unit suite pass, integration pass, ruff clean
- [ ] `python-reviewer` — CRITICAL/HIGH addressed
- [ ] Update `docs/sprint-artifacts/sprint-status.yaml` 8-9 done
- [ ] Single commit: `Implement spec 8 story 8.9`

## Technical Notes

### BracketStrategyMixin design

The five bracket strategies differ in signal generation (Supertrend
trend flips, Donchian channel breakouts, etc.) but share identical
order-building. The mixin owns:

```python
class BracketStrategyMixin:
    def _last_bar(self) -> Bar | None: ...
    def _read_account_balance(self) -> Decimal: ...          # Decimal("0") on miss
    def _compute_bracket_params(self, *, side, entry_price, atr_value, account_balance) -> tuple[Decimal, Decimal, Decimal]: ...
    def _submit_bracket_for_entry(self, signal: SignalType) -> None:
        """Build + submit the bracket for a BUY/SELL signal; no-op on NONE."""
```

Each strategy's `_execute_signal` reduces to:
```python
def _execute_signal(self, signal: SignalType) -> None:
    if signal == SignalType.CLOSE:
        self._close_position()
        return
    self._close_opposite_on_reversal(signal)  # strategy-specific reversal policy
    self._submit_bracket_for_entry(signal)
```

Reversal policy (`_close_opposite_on_reversal`) stays in strategy
subclasses because semantics differ (Supertrend reverses; Donchian
doesn't; MR closes at middle-band; ORB one-entry-per-session).

### `_read_account_balance` on portfolio miss

Returning `Decimal("0")` instead of a hardcoded $100k:
- The existing `RiskBasedPositionSizer` computes
  `risk_amount = balance * risk_percent`; `0 * 1.0% = 0` → sizer path
  returns `Decimal("0")` → `_submit_bracket_order` skips the trade.
- In live trading the portfolio is always populated; this branch is
  only reachable in misconfigured backtests. A zero-trade run is a
  loud signal of misconfiguration, as opposed to a phantom $100k run
  that could pass a visual sanity check.

### ORB boundary semantics

Current bug: a 30-minute OR on M15 bars accumulates the 08:00, 08:15,
AND 08:30 bars because `elapsed >= 30` is checked *after* adding to
OR. The 08:30 bar is already past the window. Fix: check first, add
only if inside the half-open window.

```python
elapsed = (ts - self._or_open_ts).total_seconds() / 60
if elapsed >= self.config.opening_range_minutes:
    self._or_complete = True
    # Do NOT contribute this bar to OR — fall through to breakout eval.
else:
    # Accumulate this bar into OR.
    ...
    return SignalType.NONE
```

Existing backtest metrics for ORB on M15+ timeframes may shift by
≤5 % post-fix (fewer false breakouts when OR is tighter). This is a
correctness improvement, not a regression. Documented here so any
follow-up validation run flags the expected divergence.

### HTML report determinism

Template string with f-strings. The only possibly-nondeterministic
inputs are:
- `datetime.now()` timestamps — omitted; we use only the
  `BacktestResult.start / end` fields.
- Dict iteration order — we iterate over fixed field lists.

Unit test computes `hashlib.sha256(html.encode()).hexdigest()` for the
same input twice and asserts equality.

## Dependencies

- Story 8.0 (mixins, sizer) — DONE
- Stories 8.4-8.7 (bracket strategies) — DONE
- Story 8.8 (`run_backtest` facade) — DONE

## Risks

- **Refactor cascade**: the five strategies have close-but-not-
  identical `_execute_signal` logic (reversal vs. no-reversal vs. MR
  exit-first). Keeping the reversal policy in the strategy subclass
  avoids over-abstracting a common path that isn't actually common.
- **YAML preset compat**: removing `initial_balance_fallback` from
  preset YAMLs means old presets referencing it would error on load.
  Pydantic configs use `extra="ignore"` by default on StrategyConfig
  (verify); if not, we add `model_config = ConfigDict(extra="ignore")`
  for the transition. If extra fields raise, update presets in the
  same commit.
- **ORB test regressions**: existing ORB fixtures that encode the old
  (buggy) 3-bar accumulation will need updating. Count + update
  expected values; document diff in the commit.
