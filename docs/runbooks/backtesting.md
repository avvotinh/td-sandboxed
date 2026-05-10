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

## Validation campaign harness (Epic 12)

The Epic 8 commands above answer "how does my one strategy do on this
data?" The Epic 12 harness wrappers answer "how does this strategy
perform across a documented dataset, with FTMO compliance applied,
ranked against a baseline, and reproducible from the manifest?" They
all live under `src/backtesting/dataset/` and each has a single
canonical entry point.

| What you want | Wrapper | File | Story |
|---|---|---|---|
| Anchor a strategy run to a dataset window from `configs/datasets/*.yaml` | `run_baseline(spec, config)` | `baseline_harness.py` | 12-2 |
| Decide go/no-go vs. a baseline (drawdown, profit factor, etc.) | `BaselineFilter` + `evaluate_filter` | `comparison_report.py` | 12-3 |
| Render the markdown comparison table for the report | `render_comparison_report(...)` | `comparison_report.py` | 12-3 |
| Attach an FTMO-shaped compliance actor (timezone-aware Daily / Max-DD / Consistency) | `ComplianceProfile.for_ftmo()` + `build_compliance_rule_engine(...)` | `compliance.py` | 12-4 |
| Convert a `BacktestResult` into a `BreachSummary` and gate on it | `summarize_breaches`, `assert_no_breaches` | `compliance.py` | 12-4 |
| Slice a dataset window into walk-forward folds | `FoldGenerationConfig` + `generate_folds_from_manifest` | `walk_forward_harness.py` | 12-5 |
| Run a fold-isolated walk-forward with a fixed parameter set | `run_walk_forward_fixed_params(...)` | `walk_forward_harness.py` | 12-5 |
| OOS aggregation + acceptance verdict (NaN-safe) | `aggregate_oos`, `OOSAcceptance`, `evaluate_oos` | `walk_forward_harness.py` | 12-5 |
| Render the markdown walk-forward section | `render_walk_forward_section(...)` | `walk_forward_harness.py` | 12-5 |
| Parameter sweep with a budget cap + early-stop on max-DD | `ParamSpace.from_yaml` + `run_parameter_sweep(...)` | `sweep_harness.py` | 12-6 |
| Render the markdown sweep section | `render_sweep_section(...)` | `sweep_harness.py` | 12-6 |

**Decision references** — every wrapper has a docstring citing the
specific Decision §N from the Epic 12 spec. Read those before tweaking
defaults: `OOSAcceptance` (§4 ratio≥0.7, CV≤0.5, min 3 folds),
`SweepBudget` (§3 cap 200 trials), `BaselineFilter` (§2 metric
thresholds), `default_max_dd_early_stop` (Risk R3 +inf sentinel for
missing metrics).

## Dataset fingerprinting + reproducibility

Epic 12 wrappers consume `DatasetManifest` JSON sidecars (one per
parquet file). The manifest pins **what data was used** so a validation
report can be re-verified from primary sources alone — no "run again on
the same machine to compare" rituals.

```text
configs/datasets/xauusd-validation.yaml
   ↓ DatasetSpec / DatasetPipeline (Epic 12 stories 12.1–12.7.0d)
data/historical/XAUUSD/M5/in_sample.parquet
data/historical/XAUUSD/M5/in_sample.parquet.manifest.json   ← cited by reports
```

Inside the manifest, each `DatasetEntry` carries:

| Field | Why it matters |
|---|---|
| `fingerprint.sha256_short` (first 16 hex chars of `sha256("{min_ts}|{max_ts}|{row_count}")`, see `data_cache.py:54`) | Cross-language parity: Go's `tv-cli backtest-fetch` (`Sha256Short` in `internal/store`) and the Python pipeline produce the same 16-char hex, so a Go-fetched campaign cited in a Python report can be re-verified against either side. |
| `fingerprint.min_ts` / `max_ts` / `row_count` | The three primary fields the SHA hash is computed over — keep them in the manifest so downstream code can re-derive the fingerprint without re-reading the parquet. |
| `start`, `end` | Sanity-check the window matches the fingerprint before running. |
| `gaps[]` | Bar-level gap report (start, end, duration_hours). Reports surface `max_gap_hours` and a count. |
| `parquet_path` | The artefact the harness loads. |

`BacktestResult.config_snapshot` is the round-trip artefact: when a
wrapper runs through `run_baseline(...)` it stamps the manifest entry's
fingerprint, the strategy params, and the venue/fee settings into
`config_snapshot`. The validation report renders that snapshot
verbatim — anyone reading the report can see exactly which dataset
fingerprint produced each row, then re-fetch + re-fingerprint the
parquet with the Go CLI (see [`backtest-data-fetch.md`](backtest-data-fetch.md))
to confirm the dataset they hold is byte-identical.

Practical workflow:

1. Author or update `configs/datasets/<symbol>-validation.yaml`
   declaring spec name, dataset version, and per-window timeframe.
2. Run the fetch campaign via `tv-cli backtest-fetch` per
   [`backtest-data-fetch.md`](backtest-data-fetch.md). Each run
   produces a single-window manifest sidecar.
3. Merge the per-window manifests into one canonical
   `DatasetManifest` via `merge_go_manifests` (story 12.7.0d).
4. Drive the harness wrappers above; they look up windows by name and
   open the parquet via the manifest's `parquet_path`.

A fingerprint mismatch — between what the manifest claims and what the
parquet actually computes — is a hard error (`FingerprintMismatchError`,
`comparison_report.py:38`). Treat that as a corruption signal, not a
warning to silence.

## Related documents

- `docs/architecture.md` — Backtest Framework section (Epic 8 + Epic 12 dataset layer)
- `docs/epic-8-context.md` — Epic 8 architectural decisions + risk register
- `docs/epic-12-context.md` — Epic 12 dataset-driven validation campaign + Decisions §1–§7
- `docs/runbooks/backtest-data-fetch.md` — Go-side `tv-cli backtest-fetch` campaign for OHLC fetch + manifest production
- `docs/sprint-artifacts/8-2-*.md` — BacktestRunner + FTMO actor
- `docs/sprint-artifacts/8-8-*.md` — Sweep / walk-forward CLI
- `docs/sprint-artifacts/8-9-*.md` — Bracket refactor
