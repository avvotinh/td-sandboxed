# Epic 8: Strategies & Backtesting Framework — Technical Context

**Created:** 2026-04-17
**Status:** In Progress (Stories 8.0 + 8.1 done)
**Epic:** 8 of 9+
**Stories:** 10

---

## Overview

### Problem Statement

Epic 2 shipped a single reference strategy (MA Crossover) and a stub
`src/backtesting/` module. Prop-firm trading (FTMO) needs:

1. A library of battle-tested strategies covering both trend (Supertrend,
   Donchian Breakout) and range (RSI / Bollinger mean reversion) regimes,
   plus session-anchored intraday (Opening Range Breakout).
2. A **backtest framework** that replays historical bars through the
   **same rule engine** used in live trading, so backtest PnL tracks live
   PnL and FTMO breaches surface before a live account fails.
3. Position sizing aware of daily-loss + trailing-drawdown constraints.

### Solution

Build strategies on top of Epic 4's rule engine (unchanged) and
NautilusTrader's `BacktestEngine`. The rule engine plugs into the backtest
via a Nautilus `Actor` subclass — same code path as live, no duplication.
Lightweight composable mixins (ATR stop, session filter, risk-based
sizing) let each new strategy stay under ~250 LoC.

### Scope

**In Scope:**
- Foundation: protocol-based position sizers, strategy mixins, bracket
  order helper on `BaseStrategy` (Story 8.0)
- Indicator module: re-exports + custom Supertrend, ADX, SessionVWAP
  (Story 8.1)
- Backtest engine wrapper + FTMO-compliance Actor + metrics (Story 8.2)
- TimescaleDB + Parquet cache-aside data loader (Story 8.3)
- Five strategies: Supertrend, Donchian Breakout, RSI MR, Bollinger MR,
  ORB (Stories 8.4-8.7)
- Walk-forward analysis + parameter sweep CLI (Story 8.8)
- Strategy + backtest documentation (Story 8.9)

**Out of Scope:**
- Multi-asset correlation / portfolio-level backtests
- ML-based strategies (separate future epic)
- Real-money paper trading integration (separate ops concern)
- Strategy-result dashboards (Grafana / web UI — separate epic)

---

## Architectural Decisions

### 1. Indicators wrap Nautilus `Indicator` base (not standalone numpy)

Nautilus strategies register indicators via
`register_indicator_for_bars()`, which requires a Nautilus `Indicator`
subclass. Writing standalone numpy indicators would either
(a) lose the auto-update integration, or (b) duplicate into parallel
live and backtest code paths. All custom indicators subclass
`nautilus_trader.indicators.base.Indicator`. This preserves
**backtest-reality alignment** — the same code runs in both.

### 2. FTMO rules inject via Nautilus `Actor` (not Strategy hook)

Backtest compliance checking is implemented as
`FtmoComplianceActor(Actor)` — a cross-cutting Nautilus Actor that:

- Subscribes to `OrderSubmitted`, `PositionOpened`, `PositionClosed`, bars
- On each event, builds an `AccountState` context from
  `Portfolio` + `Cache` and calls the **existing** `RuleEngine` from Epic 4
- Cancels orders on `RuleAction.BLOCK`, records breach events

Placing the rule-engine call inside strategies (Strategy hook) would
violate SRP and force every new strategy to re-wire compliance. The Actor
approach is symmetric with how live `signal_router` calls the same rule
engine between strategy and MT5 bridge.

### 3. Cache-aside Parquet over TimescaleDB for backtest data

TimescaleDB is the source of truth (Epic 3 ingestion), but reading the
same year of M1 bars 200× for a parameter sweep is wasteful. Solution:
`CachedBarLoader` composes `TimescaleBarLoader` + `ParquetBarLoader`:
first call hits TimescaleDB and writes a Parquet shard; subsequent calls
read from Parquet. Cache key includes symbol, bar spec, range, and a
content-hash (SHA256 of min/max/count from a TimescaleDB metadata query)
so retroactive bar corrections invalidate the cache automatically.

### 4. `RiskBasedPositionSizer` returns `Decimal("0")` on underflow

When the computed raw lot size is below `min_lot_size`, naïvely promoting
to the minimum silently inflates realised risk far above the configured
`risk_percent` target. On a small account with a wide stop this would
breach the FTMO daily-loss limit on a single trade. Instead, the sizer
returns `Decimal("0")` to signal *"cannot size safely"*. Callers and
`BaseStrategy._submit_bracket_order` skip the trade gracefully rather
than raise.

### 5. Legacy `PositionSizer` now uses `ROUND_DOWN` (not `round()`)

`round()` on `Decimal` uses banker's rounding (`ROUND_HALF_EVEN`), which
can **upsize** a raw lot to a higher quantity — the opposite of what
prop-firm risk discipline requires. Changed to
`quantize(Decimal("0.01"), rounding=ROUND_DOWN)` so realised risk never
exceeds the target.

### 6. Supertrend first-bar trend seeds to `+1`

Pine Script and most TA references seed `direction = nz(direction[1], 1)`
on the first valid bar. Our implementation previously seeded `-1` when
`close <= final_upper`, which made the indicator inverted for any bar
whose close landed between the two bands (the common case). Now defaults
to `+1` unless `close < final_lower`.

### 7. Walk-forward folds run in `ProcessPoolExecutor`

Nautilus `BacktestEngine` instances are not reusable across sequential
runs — each fold gets a fresh subprocess with a freshly constructed
engine. Process-pool workers receive plain config dicts + a strategy
class path (both picklable); the engine is reconstructed per worker.

---

## Module Layout

```
services/trading-engine/
├── src/
│   ├── indicators/                       # Story 8.1 — DONE
│   │   ├── __init__.py                   # re-exports ATR, RSI, Bollinger, Donchian
│   │   ├── supertrend.py                 # custom
│   │   ├── adx.py                        # custom (Wilder smoothing)
│   │   └── session_vwap.py               # custom (session-anchored)
│   ├── strategies/                       # Story 8.0 foundation + 8.4-8.7 strategies
│   │   ├── base_strategy.py              # (modified) bracket helpers, mixin facades
│   │   ├── sizing.py                     # PositionSizerProtocol
│   │   ├── position_sizer.py             # (modified) ROUND_DOWN + protocol adapter
│   │   ├── risk_based_position_sizer.py  # RiskBasedPositionSizer
│   │   ├── mixins/
│   │   │   ├── atr_stop_mixin.py
│   │   │   ├── session_filter_mixin.py
│   │   │   └── risk_sized_mixin.py
│   │   ├── supertrend.py                 # Story 8.4
│   │   ├── donchian_breakout.py          # Story 8.5
│   │   ├── rsi_mean_reversion.py         # Story 8.6
│   │   ├── bollinger_mean_reversion.py   # Story 8.6
│   │   └── orb.py                        # Story 8.7
│   ├── backtesting/                      # Story 8.2 + 8.3 + 8.8
│   │   ├── engine.py                     # BacktestRunner (wraps Nautilus BacktestEngine)
│   │   ├── data_loader.py                # Timescale + Parquet + cached composites
│   │   ├── data_cache.py                 # content-hash cache key
│   │   ├── bar_converter.py              # DataFrame → Nautilus Bar via BarDataWrangler
│   │   ├── ftmo_actor.py                 # FtmoComplianceActor(Actor)
│   │   ├── account_state_builder.py      # Portfolio → AccountState for rule engine
│   │   ├── metrics/
│   │   │   ├── schema.py                 # Pydantic FtmoMetricsSchema
│   │   │   ├── calculator.py
│   │   │   ├── trade_metrics.py          # profit factor, Sharpe, expectancy
│   │   │   └── ftmo_metrics.py           # daily DD breaches, max DD breach
│   │   ├── reports/                      # JSON + HTML report writers
│   │   ├── walk_forward.py               # Story 8.8
│   │   ├── parameter_sweep.py            # Story 8.8
│   │   └── cli.py                        # Story 8.8 — `backtest run|sweep|walkforward`
│   └── ...
├── configs/strategies/                   # YAML presets per strategy (Stories 8.4-8.7)
└── tests/unit/
    ├── conftest.py                       # shared make_bar / bar_series fixtures
    ├── test_indicator_*.py, test_*strategy.py, test_backtest_*.py
    └── ...
```

---

## NautilusTrader Integration Notes

### Indicator inventory (verified 2026-04-17 via `uv run python`)

| Indicator | Source | Strategy |
|-----------|--------|----------|
| `AverageTrueRange` | `nautilus_trader.indicators.volatility` | Re-export as `ATR` |
| `RelativeStrengthIndex` | `nautilus_trader.indicators.momentum` | Re-export as `RSI` (note: 0–1 scale, not 0–100) |
| `BollingerBands` | `nautilus_trader.indicators.volatility` | Re-export as `Bollinger` |
| `DonchianChannel` | `nautilus_trader.indicators.volatility` | Re-export as `Donchian` |
| `VolumeWeightedAveragePrice` | `nautilus_trader.indicators.volume` | Cumulative-only — we build session-anchored `SessionVWAP` |
| ADX / AverageDirectionalIndex | — | **Not in Nautilus** — custom impl |
| Supertrend | — | **Not in Nautilus** — custom impl |

### Custom indicator contract

All custom indicators subclass `nautilus_trader.indicators.base.Indicator`:

- `super().__init__([params_list])` in `__init__`
- Override `handle_bar(bar)` for per-bar logic
- Implement `_reset()` to clear internal state
- Use protected setters `_set_has_inputs(True)` and `_set_initialized(True)` (or `False`) to manage lifecycle state
- Expose computed values as properties (`.value`, and for multi-component indicators, `.upper`/`.lower`/`.trend`/`.plus_di`/`.minus_di` etc.)

### BacktestEngine API (verified)

```python
engine = BacktestEngine(config=BacktestEngineConfig())
engine.add_venue(...)            # MUST precede add_instrument
engine.add_instrument(instrument)
engine.add_data(bars)            # list of Nautilus Bar objects
engine.add_actor(ftmo_actor)     # our FtmoComplianceActor
engine.add_strategy(strategy)
engine.run(start=..., end=...)

# Post-run
stats = engine.portfolio.analyzer.get_performance_stats_pnls()
positions_closed = engine.cache.positions_closed()
```

Bar ingestion goes through
`nautilus_trader.persistence.wranglers.BarDataWrangler` —
DataFrame `(open, high, low, close, volume)` → `list[Bar]`.

`OrderFactory.bracket(...)` is **available in 1.200+** (contrary to the
docs-lookup agent's initial guess). It composes entry + linked SL + linked
TP in a single `OrderList`. Default order types: entry=MARKET (1),
tp=LIMIT (2), sl=STOP_MARKET (3).

---

## Stories Overview

| # | Story | Status | Effort | Depends |
|---|-------|--------|--------|---------|
| 8.0 | Foundation: mixins + RiskBasedPositionSizer + deps | done | M | — |
| 8.1 | Indicator module | done | L | 8.0 |
| 8.2 | Backtest engine + metrics + FtmoComplianceActor | backlog | XL | 8.0 |
| 8.3 | Backtest data loader (TimescaleDB + Parquet cache) | backlog | M | 8.2 |
| 8.4 | Supertrend strategy | backlog | M | 8.0, 8.1, 8.2 |
| 8.5 | Donchian Breakout strategy | backlog | M | 8.0, 8.1, 8.2 |
| 8.6 | RSI + Bollinger Mean Reversion (merged) | backlog | M | 8.0, 8.1, 8.2 |
| 8.7 | Opening Range Breakout (ORB) | backlog | L | 8.0, 8.1, 8.2 |
| 8.8 | Walk-forward + parameter sweep CLI | backlog | L | 8.2, 8.3, ≥1 strategy |
| 8.9 | Documentation (architecture.md, runbook, HTML report) | backlog | S | all |

Stories 8.4-8.7 are fully parallelizable once 8.2 lands. Total epic
effort: ~12-16 working days for one developer.

Lightweight-doc policy: only **8.2** and **8.8** get their own
`docs/sprint-artifacts/8-*.md` files (XL stories). Others are documented
by their commit messages + code + tests (which already carry the AC).

---

## Risk Register

| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| 1 | Nautilus API drift between 1.190 → 1.200+ (indicator paths, bracket signature) | HIGH | Pin `nautilus_trader>=1.200`; Story 8.1 smoke test imports every wrapped indicator; Story 8.2 inspects `BacktestEngine` API at runtime |
| 2 | `ProcessPoolExecutor` can't pickle Nautilus `BacktestEngine` for walk-forward | HIGH | Each fold receives plain config + strategy class path; constructs engine inside the worker subprocess |
| 3 | `FtmoComplianceActor` double-counts daily-loss breach on every bar of a losing day | MEDIUM | Actor keeps a `(date, rule_name)` set and deduplicates within the day |
| 4 | Parquet cache serves stale data after late-arriving bar corrections | MEDIUM | Content hash in cache key (SHA256 of min/max/count from TimescaleDB metadata query) invalidates automatically; `--no-cache` CLI flag for forced refresh |
| 5 | Lookahead bias: strategy entries using *current* bar close-derived indicator value live can only use previous-bar close | MEDIUM | Contract: signal generation uses `_prev_*` shadowed values (pattern already in `MACrossoverStrategy._prev_fast`); consider a lint test scanning strategies for `bar.close` inside `generate_signal` without a prior-bar shadow |
| 6 | Sweep explosion (5 params × 6 values × 1 year M1 = days of CPU) | LOW | Default `search=random` with `n_iter=200`; Parquet cache + `ProcessPoolExecutor(max_workers=os.cpu_count()-1)`; `--early-stop-metric max_overall_dd_pct --early-stop-threshold 10.0` |
| 7 | Session-VWAP DST bug on London/NY transitions | MITIGATED (8.1) | Uses `zoneinfo` via `SessionFilterMixin.session_id`; reviewer-prompted regression test added |

---

## Key References

- `docs/architecture.md` — system-level architecture (backtest section
  added in Story 8.9)
- `docs/prd.md` — product requirements (FR coverage for Epic 8: trading
  strategies + backtesting post-MVP vision)
- `.claude/rules/common/sandboxed-domain.md` — FTMO + monorepo boundary
  rules
- `src/rules/` — Epic 4 rule engine (reused unchanged by
  `FtmoComplianceActor`)
- `configs/ftmo-presets.yaml` — FTMO constraints (daily loss, max DD,
  scaling)
- NautilusTrader docs consulted 2026-04-17 via Context7:
  `BacktestEngine`, `BarDataWrangler`, `Indicator` base, `OrderFactory`
