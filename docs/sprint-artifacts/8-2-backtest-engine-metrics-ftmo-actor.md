# Story 8.2: Backtest Engine + Metrics + FtmoComplianceActor

Status: Done

## Story

As a **trader**,
I want **a backtest runner that replays bars through the same FTMO rule engine used in live trading**,
So that **backtest results faithfully reflect what a live account would experience and FTMO breaches surface before a live account fails**.

## Acceptance Criteria

1. **AC1 — BacktestRunner wraps Nautilus BacktestEngine**: `src/backtesting/engine.py::BacktestRunner` exposes `add_venue`, `add_instrument`, `add_data`, `add_strategy`, `attach_ftmo_compliance`, `run`, and `get_result`. `run()` returns a `BacktestResult` whose `equity_curve` length equals the bar count (1 snapshot per bar).

2. **AC2 — FtmoComplianceActor is a Nautilus Actor (not a Strategy hook)**: `src/backtesting/ftmo_actor.py::FtmoComplianceActor(Actor)`. `isinstance(actor, nautilus_trader.common.actor.Actor)` is True. Actor reads `portfolio` + `cache` to build account state, invokes the existing `RuleEngine` from `src/rules/engine.py` (unchanged), cancels orders on `RuleAction.BLOCK`, and appends breach events to an in-memory list exposed as `actor.breaches`.

3. **AC3 — Breach deduplication**: A losing day that triggers the daily-loss rule on every bar of that day registers exactly one `(date, rule_name)` breach, not one per bar.

4. **AC4 — FtmoMetricsSchema (Pydantic)**: `src/backtesting/metrics/schema.py::FtmoMetricsSchema` covers pnl (profit_factor, expectancy, avg_r_multiple, net_pnl, return_pct), drawdown (max_overall_dd_pct, max_daily_dd_pct, recovery_factor), risk (sharpe, sortino, max_consecutive_losses), trades (win_rate, avg_win, avg_loss, total_trades), and ftmo_compliance (daily_loss_breaches, max_dd_breach, profit_target_hit, min_trading_days_met). Schema validates JSON output.

5. **AC5 — Metrics correctness on fixtures**: For a known-input fixture (mean=0.1%, std=1%, n=252) Sharpe matches reference `(0.1/1) * sqrt(252) ≈ 1.587` within ±0.05. Profit factor = `inf` when all trades win; `0.0` when all trades lose. Max overall DD % computed from peak-to-trough on equity curve.

6. **AC6 — Synthetic bar generator**: `src/backtesting/synthetic_bars.py::generate_bars(pattern, count, ...)` supports `pattern in {"trending", "mean_reverting", "flat"}` for deterministic tests. Same seed + params always yields identical bar series.

7. **AC7 — BarDataWrangler integration**: `src/backtesting/bar_converter.py::dataframe_to_bars(df, bar_type, instrument)` converts a pandas OHLCV DataFrame to `list[Bar]` via `nautilus_trader.persistence.wranglers.BarDataWrangler`. Output length equals DataFrame length.

8. **AC8 — AccountState builder**: `src/backtesting/account_state_builder.py::build_account_state(portfolio, venue, initial_balance, peak_balance, daily_metrics)` returns a dict matching `RuleContextBuilder` expectations (`balance`, `equity`, `initial_balance`, `peak_balance`, `daily_pnl`, `daily_pnl_percent`, `total_drawdown_percent`, `open_positions_count`, `total_exposure`).

9. **AC9 — Integration smoke test**: MACrossover strategy runs on 500 synthetic trending bars through the full `BacktestRunner` with FTMO actor attached; produces a `BacktestResult` where `result.metrics.total_trades > 0` and `len(result.equity_curve) == 500`. Completes in <10s locally.

10. **AC10 — Order cancellation on BLOCK**: When the rule engine returns `RuleAction.BLOCK` during actor validation of an `OrderSubmitted`, Nautilus receives a cancel call. A test verifies via a mock rule engine that the actor invokes `self.cancel_order()` (or equivalent Nautilus cancel API) at least once.

## Tasks

### Task 1: Data types — BacktestResult + FtmoMetricsSchema
- [ ] `src/backtesting/result.py` — `@dataclass(frozen=True) class BacktestResult` (config_snapshot, equity_curve, trades, breaches, metrics, start, end)
- [ ] `src/backtesting/metrics/schema.py` — Pydantic `FtmoMetricsSchema`
- [ ] Tests: `test_backtest_result.py`, `test_ftmo_metrics_schema.py`

### Task 2: Synthetic bar generator
- [ ] `src/backtesting/synthetic_bars.py` — `generate_bars(pattern, count, start_ts, ...)`
- [ ] Test: `test_synthetic_bars.py`

### Task 3: Bar converter (DataFrame → Bar)
- [ ] `src/backtesting/bar_converter.py` — `dataframe_to_bars(df, bar_type, instrument)` via `BarDataWrangler`
- [ ] Test: `test_bar_converter.py`

### Task 4: AccountState builder
- [ ] `src/backtesting/account_state_builder.py` — `build_account_state(portfolio, venue, ...)`
- [ ] Test: `test_account_state_builder.py`

### Task 5: Metrics calculator
- [ ] `src/backtesting/metrics/trade_metrics.py` — profit_factor, sharpe, sortino, win_rate, expectancy, avg_r_multiple
- [ ] `src/backtesting/metrics/ftmo_metrics.py` — daily_dd, max_dd, breach_count, profit_target_hit
- [ ] `src/backtesting/metrics/calculator.py` — orchestrator producing `FtmoMetricsSchema`
- [ ] Tests: `test_trade_metrics.py`, `test_ftmo_metrics.py`, `test_metrics_calculator.py`

### Task 6: FtmoComplianceActor
- [ ] `src/backtesting/ftmo_actor.py` — subscribe to order/position events, call rule engine, cancel on BLOCK, dedupe breaches
- [ ] Test: `test_ftmo_actor.py` (unit with mock rule engine + mock portfolio)

### Task 7: BacktestRunner
- [ ] `src/backtesting/engine.py` — `BacktestRunner` wrapping `BacktestEngine`; config-driven; `attach_ftmo_compliance(preset_path)` wires actor
- [ ] Test: `test_backtest_runner.py` (unit — mock `BacktestEngine` internals)

### Task 8: Integration smoke test
- [ ] `tests/integration/backtesting/test_engine_smoke.py` — MACrossover + synthetic trending bars + FTMO actor, end-to-end

### Task 9: Review + Commit
- [ ] Run full unit test suite (`pytest -m "not integration"`) — all pass
- [ ] Run integration smoke test — passes in <10s
- [ ] `ruff check` clean on all new files
- [ ] `python-reviewer` agent — address CRITICAL/HIGH
- [ ] Update `docs/sprint-artifacts/sprint-status.yaml` → 8-2 done
- [ ] Single commit: `Implement spec 8 story 8.2`

## Technical Notes

### FtmoComplianceActor design

Nautilus `Actor` (not `Strategy`) subscribes to the message bus. We use `self.msgbus.subscribe(...)` for events we care about, and `self.portfolio` + `self.cache` to read live state.

Pseudocode:
```python
class FtmoComplianceActor(Actor):
    def __init__(self, config: FtmoActorConfig):
        super().__init__(config)
        self._rule_engine: RuleEngine = ...           # injected
        self._context_builder = RuleContextBuilder()
        self._breaches: list[BreachEvent] = []
        self._dedup: set[tuple[date, str]] = set()    # (date, rule_name)
        self._initial_balance: Decimal = ...
        self._peak_balance: Decimal = ...
        self._equity_curve: list[tuple[ts, equity]] = []

    def on_start(self):
        self.msgbus.subscribe("events.order.submitted", self._on_order_submitted)
        self.msgbus.subscribe("events.position.*", self._on_position_event)

    def on_bar(self, bar):
        equity = self.portfolio.net_exposure(...)  # or account.balance_total()
        self._equity_curve.append((bar.ts_init, equity))
        # Re-evaluate daily-loss / max-DD rules; record breach (deduped)
```

### Portfolio + account access

```python
account = self.portfolio.account(self._venue)
balance = account.balance_total(currency)
equity = self.portfolio.total_pnl(...) + balance  # or similar — verify API
```

Nautilus `PortfolioAnalyzer` exposes post-run stats; but mid-run we need realtime equity for FTMO rule checks, so we compute manually on each bar.

### Dedup key

`(date, rule_name)` — a daily-loss rule blocking on many bars in one day = one breach.

### BacktestRunner config

Pydantic `BacktestRunnerConfig` (frozen) with:
- `venue_config`, `instrument`, `starting_balance`, `currency`
- `bar_type`, `start`, `end`
- `strategies: list[StrategyConfig]`
- Optional `ftmo_preset_path: Path | None`

## Dependencies

- Story 8.0 (BaseStrategy helpers, mixins, RiskBasedPositionSizer) — DONE
- Epic 4 rule engine (`src/rules/engine.py`, `src/rules/context_builder.py`, `src/rules/base_rule.py`) — DONE, unchanged
- Nautilus 1.200+ (`BacktestEngine`, `Actor`, `BarDataWrangler`, `PortfolioAnalyzer`)

## Risks

- **Nautilus Actor `msgbus.subscribe` topic names** may differ from docs. Plan: inspect via runtime introspection before wiring; fall back to `Strategy` hook if Actor API is unexpectedly different. (Recorded in epic-8-context.md risk #1.)
- **Mid-run equity calc** may not match `PortfolioAnalyzer` post-run values exactly. Plan: document the formula in Actor; verify against `PortfolioAnalyzer.get_performance_stats_pnls()` post-run.
- **Integration smoke test flakiness** if Nautilus engine setup order is wrong (add_venue before add_instrument, etc.). Plan: assert setup order in `BacktestRunner`.
