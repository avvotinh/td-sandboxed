# Story 8.8: Walk-Forward + Parameter Sweep CLI

Status: Backlog

## Story

As a **strategy researcher**,
I want **CLI-driven parameter sweeps and walk-forward analysis against
the same `BacktestRunner` used for point backtests**,
So that **I can identify robust parameter sets for a strategy and
validate out-of-sample performance before promoting it to a live
account**.

## Acceptance Criteria

1. **AC1 — `BacktestJobConfig` composes a full backtest from one object**:
   `src/backtesting/job_config.py::BacktestJobConfig` is a Pydantic frozen
   model covering venue, instrument, data source, strategy + params, FTMO
   preset, and account sizing. `job.with_strategy_params(**overrides)`
   returns a new job with the overrides merged (immutability preserved).

2. **AC2 — `run_backtest(job) -> BacktestResult` helper hides Nautilus
   plumbing**: `src/backtesting/runner_facade.py::run_backtest` builds the
   `BacktestRunner`, wires venue + instrument + data + strategy + (optional)
   FTMO actor, calls `.run()`, then returns `BacktestResult`. The CLI and
   sweep/walk-forward call **only** this helper — no direct Nautilus type
   imports in new modules (`cli.py`, `parameter_sweep.py`, `walk_forward.py`).
   `BacktestRunner`'s public API is unchanged (backward-compat).

3. **AC3 — Strategy registry is explicit and extensible**:
   `src/backtesting/strategy_registry.py` exposes `STRATEGY_REGISTRY:
   dict[str, StrategyEntry]` mapping `ma_crossover`, `supertrend`,
   `donchian_breakout`, `rsi_mean_reversion`, `bollinger_mean_reversion`,
   `orb` to `(config_cls, strategy_cls)`. Unknown name raises
   `UnknownStrategyError` with the list of known names.

4. **AC4 — Synthetic data source for fast unit/integration tests**:
   `BacktestJobConfig` with `data: SyntheticDataSpec(pattern="trending",
   count=500, seed=42, start_price=1.10)` yields 500 deterministic bars.
   Same config = same bars across runs. This path has zero I/O.

5. **AC5 — `ParameterSweep` supports `grid` and `random` search**:
   `src/backtesting/parameter_sweep.py::ParameterSweep(job, param_grid,
   search="grid" | "random", n_iter=None, seed=None)`. Grid enumerates
   the Cartesian product; random draws `n_iter` combos uniformly without
   replacement when possible. Identical `(param_grid, search, n_iter,
   seed)` ⇒ identical combo order.

6. **AC6 — Parallel execution via `ProcessPoolExecutor`**:
   `sweep.run(max_workers=N)` dispatches each combo to a worker subprocess
   that reconstructs the `BacktestRunner` (Nautilus engines are not
   pickle-safe). Returns `SweepResult(combos=[...], results=[BacktestResult,
   ...], ranked_by: str)` sorted by the configured objective (default
   `net_pnl` descending). Workers that raise are surfaced as failed combos
   rather than aborting the whole sweep.

7. **AC7 — Sweep early-stop on FTMO breach**:
   `sweep.run(early_stop=EarlyStopConfig(metric="max_overall_dd_pct",
   threshold=10.0, mode="gt"))` skips *recording* combos that exceed the
   threshold but still records them as `status="early_stop"` with the
   breach value. (Unit-tested with a mock `run_backtest` so we don't need
   real FTMO simulation.)

8. **AC8 — `WalkForward` supports anchored + rolling folds**:
   `src/backtesting/walk_forward.py::WalkForward(job, folds, mode)` where
   `mode ∈ {"anchored", "rolling"}`. `folds` is a list of
   `FoldSpec(train_start, train_end, test_start, test_end)` or can be
   generated from `WalkForwardFolds.generate(total_start, total_end,
   train_window, test_window, step, mode)`. Anchored: `train_start` is
   constant. Rolling: `train_start` slides by `step`. Both modes emit
   non-overlapping test windows.

9. **AC9 — Walk-forward re-optimizes per fold + reports OOS metrics**:
   `wf.run(param_grid, search, n_iter)` runs a `ParameterSweep` on each
   fold's **train** window, takes the best combo by objective, then
   evaluates that combo on the fold's **test** window. Returns
   `WalkForwardResult(folds=[FoldResult(fold, best_params,
   train_metrics, test_metrics), ...])`. An **aggregate OOS** line
   concatenates per-fold test equity curves and recomputes metrics.

10. **AC10 — CLI `backtest run|sweep|walkforward`**:
    `src/backtesting/cli.py` is a `typer` app wired into `src/cli/main.py`
    as `app.add_typer(backtest_app, name="backtest")`. Subcommands:
    - `trading-engine backtest run --job configs/backtests/quick.yaml
      [--json] [--out reports/]`
    - `trading-engine backtest sweep --job quick.yaml --grid grid.yaml
      [--search grid|random] [--n-iter 200] [--workers N]
      [--early-stop-metric max_overall_dd_pct --early-stop-threshold 10.0]
      [--objective net_pnl] [--out reports/]`
    - `trading-engine backtest walkforward --job quick.yaml --grid grid.yaml
      [--mode anchored|rolling] [--train 90d] [--test 30d] [--step 30d]
      [--out reports/]`
    Exit code `0` on success, `1` on config/load error, `2` on runtime
    failure (≥1 combo failed). `--json` writes machine-readable result
    (sweep: ranked list; walkforward: per-fold + aggregate).

11. **AC11 — Sweep/walk-forward integration smoke test**:
    2×2 grid on MACrossover + synthetic trending bars (500 bars) completes
    in <15 s with `max_workers=2`, returns 4 results, none in
    `status="failed"`. Walk-forward with 2 anchored folds on the same
    synthetic bars completes in <20 s and emits `FoldResult` with
    `best_params` populated.

12. **AC12 — Lookahead-free (no peeking from train into test)**: A unit
    test asserts that when `WalkForward.generate_folds(...)` is called,
    `fold.test_start >= fold.train_end` for every fold and no two test
    windows overlap (mode=anchored or rolling).

## Tasks

### Task 1: Story doc + story registration
- [x] Create this file
- [ ] Update `docs/sprint-artifacts/sprint-status.yaml`
      `8-8-walk-forward-parameter-sweep-cli: in-progress` at task start

### Task 2: `BacktestJobConfig` + data source specs
- [ ] `src/backtesting/job_config.py` — `BacktestJobConfig`,
      `SyntheticDataSpec`, `TimescaleDataSpec`, `ParquetDataSpec`,
      `VenueSpec`, `FtmoSpec`
- [ ] `src/backtesting/strategy_registry.py` — `STRATEGY_REGISTRY`,
      `StrategyEntry`, `UnknownStrategyError`
- [ ] YAML loader: `BacktestJobConfig.from_yaml(path: Path)`
- [ ] Tests: `test_job_config.py`, `test_strategy_registry.py`

### Task 3: `run_backtest` facade
- [ ] `src/backtesting/runner_facade.py` — `run_backtest(job, *,
      strategy_overrides=None) -> BacktestResult`
- [ ] Wires: venue → instrument (via `TestInstrumentProvider` or user-
      provided factory) → data (synthetic | timescale-cached | parquet) →
      strategy (from registry + params + overrides) → FTMO actor
      (optional) → run → get_result → dispose (always)
- [ ] Tests: `test_runner_facade.py` with mocked `BacktestRunner` to
      verify composition order + override merging

### Task 4: `ParameterSweep`
- [ ] `src/backtesting/parameter_sweep.py` — `ParameterSweep`,
      `SweepResult`, `CombinationResult`, `EarlyStopConfig`
- [ ] Combo expansion: grid = Cartesian; random = deterministic sample
      with seed
- [ ] Parallel dispatch via `concurrent.futures.ProcessPoolExecutor`;
      worker entry `_run_single(job, overrides)` reconstructs runner
- [ ] Early-stop filtering, objective-based ranking, failure capture
- [ ] Tests: `test_parameter_sweep.py` with mocked `run_backtest`
      (monkeypatch the module-level function) — grid/random parity,
      seed determinism, early-stop, failure capture, ranking

### Task 5: `WalkForward`
- [ ] `src/backtesting/walk_forward.py` — `FoldSpec`, `FoldResult`,
      `WalkForwardFolds.generate`, `WalkForward`, `WalkForwardResult`
- [ ] Fold generation for anchored + rolling with no-overlap invariant
- [ ] Per-fold re-optimize then OOS evaluation via `run_backtest` with
      narrowed `start`/`end`
- [ ] Aggregate OOS metrics from concatenated test equity curves
- [ ] Tests: `test_walk_forward.py` — fold-generation invariants
      (anchored, rolling, edge cases), mocked-sweep fold execution

### Task 6: CLI `backtest` subcommand
- [ ] `src/backtesting/cli.py` — typer `backtest_app` with
      `run|sweep|walkforward`
- [ ] `parse_duration("90d")` helper (reuse `_parse_time_delta` pattern
      from `src/cli/main.py` — extract to
      `src/backtesting/_cli_utils.py` to keep boundary clean)
- [ ] JSON output writer for each subcommand
- [ ] Wire into `src/cli/main.py` via `app.add_typer`
- [ ] Tests: `test_cli_backtest.py` using `typer.testing.CliRunner`
      with mocked `run_backtest` / `ParameterSweep.run` /
      `WalkForward.run`

### Task 7: Integration smoke test
- [ ] `tests/integration/backtesting/test_sweep_smoke.py` —
      2×2 MACrossover grid on 500 synthetic bars, `max_workers=2`,
      <15 s wall-clock, no failed combos
- [ ] `tests/integration/backtesting/test_walkforward_smoke.py` —
      2 anchored folds, <20 s, populated `best_params`

### Task 8: Review + commit
- [ ] `uv run pytest -m "not integration"` — all pass
- [ ] `uv run pytest -m integration tests/integration/backtesting/` — pass
- [ ] `uv run ruff check .` — clean
- [ ] `python-reviewer` subagent — address CRITICAL/HIGH
- [ ] Update `docs/sprint-artifacts/sprint-status.yaml` →
      `8-8-walk-forward-parameter-sweep-cli: done`
- [ ] Single commit: `Implement spec 8 story 8.8`

## Technical Notes

### Module layout

```
src/backtesting/
├── job_config.py          # NEW — BacktestJobConfig + data specs
├── strategy_registry.py   # NEW — name -> (config_cls, strategy_cls)
├── runner_facade.py       # NEW — run_backtest(job) single entry
├── parameter_sweep.py     # NEW — ParameterSweep + SweepResult
├── walk_forward.py        # NEW — WalkForward + folds
├── cli.py                 # NEW — typer subapp
├── _cli_utils.py          # NEW — parse_duration, output helpers
├── engine.py              # UNCHANGED — BacktestRunner (8.2)
├── data_loader.py         # UNCHANGED — CachedBarLoader (8.3)
└── ...
```

### Instrument handling

The facade uses `TestInstrumentProvider` for common symbols
(EUR/USD, XAUUSD). Unknown symbols raise `UnsupportedInstrumentError`
with a helpful message. Building real prop-firm instruments from MT5
metadata is out of scope for 8.8 — deferred to a follow-up when we
integrate live MT5 broker details.

### Worker-safe job serialization

`BacktestJobConfig` is Pydantic-frozen and serializable to JSON /
primitives. Workers receive `(job_dict, overrides_dict)`, reconstruct
the job inside the subprocess, and call `run_backtest`. Nautilus
objects (InstrumentId, BarType, etc.) are created inside the worker,
never crossing the process boundary.

### Early-stop semantics

Early-stop is **skip-record**, not **abort-sweep**: failing combos land
in the result set with `status="early_stop"` so the user can still see
the full parameter coverage. Aborting the whole sweep on a single
breach would hide mostly-good parameter regions.

### Walk-forward aggregate OOS

The aggregate line concatenates per-fold **test** equity curves (not
train) and recomputes FTMO metrics. For anchored mode this means test
windows chain forward in time — the combined curve reflects how an
adaptive-re-tuning strategy would have performed.

## Dependencies

- Story 8.2 — `BacktestRunner`, `BacktestResult`, `FtmoMetricsSchema` ✓
- Story 8.3 — `CachedBarLoader` (used by `TimescaleDataSpec` path) ✓
- ≥1 strategy — MACrossover (2.8) ✓; others from 8.4-8.7 ✓
- `typer` (already in project)
- stdlib: `concurrent.futures`, `itertools`, `random`

## Risks

- **Nautilus engine pickling** — mitigated by reconstructing `BacktestRunner`
  inside each worker subprocess; `BacktestJobConfig` is the only thing
  crossing the boundary and it's Pydantic-serializable.
- **Instrument symbol coverage** — `TestInstrumentProvider` only supports
  a curated set. If a strategy preset references an unknown symbol, the
  facade raises `UnsupportedInstrumentError` with the list of supported
  symbols. Real-broker instrument loading is deferred.
- **Sweep explosion** — Epic 8 risk #6: default `search=random`,
  `n_iter=200`; early-stop protects wall-clock on catastrophic DD runs.
- **Test flakiness from pool startup** — cap workers at `min(2,
  os.cpu_count())` for tests; deterministic seed for random sampling.

## Known debt intentionally deferred

- `initial_balance_fallback` hardcoded in strategy YAML presets →
  addressed in 8.9
- ORB boundary bar over-accumulation → addressed in 8.9
- Real-broker instrument loading (MT5 metadata) → post-epic
