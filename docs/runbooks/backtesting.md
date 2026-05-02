# Backtesting Runbook

Step-by-step guide for running point backtests, parameter sweeps, and
walk-forward analyses on the Sandboxed trading-engine.

## Prerequisites

```bash
# Install dependencies (uv, not poetry — project-wide convention)
cd services/trading-engine
uv sync
```

Optional for real historical data:

- TimescaleDB running (`docker compose up -d timescaledb`) with
  `candles` hypertable populated.
- Parquet cache directory writable (default: `./cache/parquet/`).

Without either, you can still run the synthetic-data path end-to-end —
useful for smoke tests and CI.

## Core concepts

| Thing | What it is |
|---|---|
| `BacktestJobConfig` | Declarative YAML/Pydantic object describing one backtest: venue, instrument, data source, strategy + params, optional FTMO preset. |
| `run_backtest(job)` | Pure helper — takes a job, returns a `BacktestResult`. The CLI and sweep/walk-forward all go through this. |
| `ParameterSweep` | Grid or random search over a param grid, parallel via `ProcessPoolExecutor`. |
| `WalkForward` | Anchored or rolling fold generation + per-fold re-optimization + out-of-sample evaluation. |
| `BacktestResult` | Immutable dataclass with equity curve, trades, breaches, and `FtmoMetricsSchema` metrics. |

## Authoring a job YAML

`configs/backtests/quick.yaml`:

```yaml
strategy: ma_crossover
instrument_symbol: EUR/USD
bar_type_suffix: 1-MINUTE-BID-EXTERNAL
venue:
  name: SIM
  starting_balance: "100000"
  currency: USD
strategy_params:
  fast_period: 5
  slow_period: 20
  trade_size: "10000"
data:
  kind: synthetic
  pattern: trending
  count: 500
  start_price: 1.10
  seed: 42
# Optional — attach FTMO compliance actor
# ftmo:
#   preset_path: configs/ftmo-preset.yaml
#   account_id: ftmo-sim
```

Field glossary:

| Field | Type | Notes |
|---|---|---|
| `strategy` | str | One of `ma_crossover`, `supertrend`, `donchian_breakout`, `rsi_mean_reversion`, `bollinger_mean_reversion`, `orb`. |
| `instrument_symbol` | str | Whitelisted: `EUR/USD`, `GBP/USD`, `USD/JPY`, `USD/CAD`, `AUD/USD`, `XAUUSD`. |
| `bar_type_suffix` | str | Nautilus BarType suffix — `<N>-<unit>-<price_type>-<aggregation>`. |
| `venue.starting_balance` | Decimal-string | Initial account balance. |
| `strategy_params` | mapping | Strategy-specific params (see strategy module docstrings). |
| `data.kind` | `synthetic \| timescale \| parquet` | Data source discriminator. |
| `data.pattern` | `trending \| mean_reverting \| flat` | Synthetic-only. |

## Run a single backtest

```bash
# Human-readable summary
uv run trading-engine backtest run --job configs/backtests/quick.yaml

# Machine-readable JSON on stdout
uv run trading-engine backtest run --job configs/backtests/quick.yaml --json

# Write a JSON or HTML report
uv run trading-engine backtest run --job quick.yaml --out reports/run.json
uv run trading-engine backtest run --job quick.yaml --out reports/run.html
```

Example output:

```
Backtest Result
===============
Strategy:        ma_crossover
Window:          2024-01-01 00:00:00+00:00 → 2024-01-01 08:19:00+00:00
Initial balance: 100000
Final balance:   100123.45
Net PnL:         123.45
Trades:          3
Breaches:        0
```

Exit codes: `0` success, `1` config error, `2` runtime failure.

## Parameter sweep

`configs/backtests/grid.yaml` — just a mapping of `param_name -> list`:

```yaml
fast_period: [3, 5, 7]
slow_period: [10, 20, 30]
```

```bash
# Full Cartesian grid on 4 workers
uv run trading-engine backtest sweep \
  --job configs/backtests/quick.yaml \
  --grid configs/backtests/grid.yaml \
  --search grid \
  --workers 4 \
  --out reports/

# Random search — 50 combos out of the full space
uv run trading-engine backtest sweep \
  --job quick.yaml --grid big_grid.yaml \
  --search random --n-iter 50 --seed 42 \
  --workers 8
```

### Early-stop on drawdown

Skip-record combos that breach a metric threshold (still recorded with
`status="early_stop"`, just not ranked as "ok"):

```bash
uv run trading-engine backtest sweep \
  --job quick.yaml --grid grid.yaml \
  --early-stop-metric max_overall_dd_pct \
  --early-stop-threshold 10.0
```

Example ranked output:

```
Parameter Sweep — Top Results
==============================
  Rank    Score  Params
------  -------  -----------------------------
     1   523.40  fast_period=5, slow_period=20
     2   401.10  fast_period=5, slow_period=30
     3   289.00  fast_period=3, slow_period=30
...

Total: 9  OK: 9  Failed: 0  Early-stop: 0
```

## Walk-forward

Re-optimize parameters per fold, then evaluate out-of-sample:

```bash
uv run trading-engine backtest walkforward \
  --job quick.yaml --grid grid.yaml \
  --start 2024-01-01 --end 2024-07-01 \
  --train 90d --test 30d --step 30d \
  --mode anchored \
  --workers 4
```

Duration format: `Nd` (days), `Nh` (hours), `Nm` (minutes), `Ns`
(seconds).

**Modes:**

- `anchored` — `train_start` is fixed at the total range start; each
  fold extends `train_end` by `step`. Models get more history over time.
- `rolling` — the full train window slides forward by `step`. Models
  always see `train` worth of recent history, no more.

Example output:

```
Walk-Forward (anchored)
=========================
  Fold  Train Start  Train End    Test End    Best Params                   OOS PnL
------  -----------  -----------  ----------  ----------------------------  -------
     1  2024-01-01   2024-04-01   2024-05-01  fast_period=5, slow_period=20  401.2
     2  2024-01-01   2024-05-01   2024-06-01  fast_period=7, slow_period=30  289.5
     3  2024-01-01   2024-06-01   2024-07-01  fast_period=5, slow_period=20  512.8
```

## Reading the HTML report

`backtest run --out report.html` produces a single-file document with:

1. **Summary metrics** — strategy, window, balances, net PnL, trade /
   breach counts, profit factor, Sharpe, max DD %, win rate.
2. **Equity curve** — inline SVG, no external assets, no JS.
3. **Trade list** — first 100 trades (timestamp, side, prices, qty, PnL
   with red/green colouring).
4. **Breach list** — any FTMO rule breaches with timestamps and
   messages. Empty if no FTMO actor is attached.

The output is deterministic: same `BacktestResult` → byte-identical
HTML. Safe to diff across commits as a regression signal.

## Common errors

| Symptom | Cause | Fix |
|---|---|---|
| `UnknownStrategyError: Unknown strategy 'foo'` | Typo in `strategy:` field | Use one of the 6 registered names listed above. |
| `UnsupportedInstrumentError` | `instrument_symbol` not in whitelist | Expand `_SUPPORTED_SYMBOLS` in `job_config.py` + add smoke test. |
| `max_workers must be >= 1` | Passed `--workers 0` | Use a positive integer. |
| `Invalid job config: ...` at CLI start | YAML syntax or Pydantic validation error | Exit code 1 — read stderr message, fix YAML. |
| `All combos failed.` at sweep end | Every combo raised | Exit code 2 — check worker logs; likely a config mistake propagated to every combo. |
| Phantom zero-trade run | Misconfigured venue — no FTMO actor, no portfolio | `_read_account_balance` returns `Decimal("0")` → sizer skips trades. Expected when the venue is not wired. Ensure `venue.starting_balance` is set and the instrument matches. |

## Layered test suite

```bash
# All unit tests, fast — no external deps
uv run pytest -m "not integration"

# Integration smoke tests (backtest + sweep)
uv run pytest tests/integration/test_backtest_smoke.py \
              tests/integration/test_sweep_smoke.py \
              tests/integration/test_bracket_strategies_smoke.py

# Full pre-commit gate
uv run pytest && uv run ruff check .
```

## Related documents

- `docs/architecture.md` — Backtest Framework section (Epic 8)
- `docs/epic-8-context.md` — architectural decisions + risk register
- `docs/sprint-artifacts/8-2-*.md` — BacktestRunner + FTMO actor
- `docs/sprint-artifacts/8-8-*.md` — Sweep / walk-forward CLI
- `docs/sprint-artifacts/8-9-*.md` — Bracket refactor + this runbook
