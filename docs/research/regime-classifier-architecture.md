# Regime Classifier — Phase 1 Architecture

**Date:** 2026-05-02
**Source research:** [regime-classifier.md](./regime-classifier.md)
**Scope:** Phase 1 only — rule-based classifier (no ML / HMM yet)
**Status:** Approved for implementation

---

## Confirmed Phase 1 Scope

- **Algorithm**: rule-based using ADX + BB width percentile + realized vol + EMA slope
- **4 regime states**: `TRENDING_UP`, `TRENDING_DOWN`, `RANGING`, `HIGH_VOLATILITY`
- **Per-regime routing**:
  - `TRENDING_UP/DOWN` → Supertrend, Donchian breakout, MA Crossover
  - `RANGING` → RSI MR, Bollinger MR
  - `HIGH_VOLATILITY` → **all trading stops** (global kill-switch)
- **Hysteresis**: 2 consecutive bars confirming new state before switch
- **Instruments**: XAUUSD only (M5 + M15 concurrent supported)
- **Thresholds**: load from `configs/firms/ftmo.yaml`, never hardcode
- **Audit**: write to `audit_logs` hypertable BEFORE routing decision

---

## 1. Module Layout

```
services/trading-engine/src/
├── regime/                                  # NEW package
│   ├── __init__.py                          # public API re-exports
│   ├── states.py                            # RegimeState enum
│   ├── features.py                          # RegimeFeatures dataclass + FeatureExtractor
│   ├── classifier.py                        # RuleBasedRegimeClassifier (pure)
│   ├── hysteresis.py                        # HysteresisFilter (stateful, per-BarType)
│   ├── decision.py                          # RegimeDecision frozen dataclass
│   ├── audit.py                             # RegimeAuditAdapter (wraps AuditLogger)
│   └── config.py                            # RegimeConfig pydantic model
├── strategies/
│   ├── data_router.py                       # MODIFIED — accepts optional classifier
│   ├── registry.py                          # MODIFIED — register_strategy adds regimes kwarg
│   └── regime_routing.py                    # NEW — RegimeAwareRouter wraps StrategyDataRouter
└── indicators/
    ├── bb_width.py                          # NEW — Bollinger band width %
    ├── realized_vol.py                      # NEW — log-return std (rolling)
    └── ema_slope.py                         # NEW — slope of EMA over N bars
```

ADX is reused from `src/indicators/adx.py` (do not duplicate).

---

## 2. Call Graph

```
Bar arrives (RedisAdapter.set_bar_callback)
        │
        ▼
RegimeAwareRouter.route_bar(bar)        ◄── drop-in for StrategyDataRouter
        │
        ├─► FeatureExtractor[bar_type].update(bar)        # rolling 200 bars
        │   returns RegimeFeatures (or None during warmup)
        │
        ├─► RuleBasedRegimeClassifier.decide(features)    # pure function
        │   returns raw RegimeState
        │
        ├─► HysteresisFilter[bar_type].apply(raw_state)   # 2-bar confirmation
        │   returns RegimeDecision (current_state, raw_state, bars_in_pending, …)
        │
        ├─► RegimeAuditAdapter.log(decision)              # fire-and-forget Redis write
        │   └─► AuditLogger._write_to_redis() ─┐
        │                                       │ (matches existing rule audit pattern)
        │                                       ▼
        │                       AuditDBWriter (60s batch flush → audit_logs hypertable)
        │
        └─► For each BoundAccount:
                if decision.current_state == HIGH_VOLATILITY:
                    skip routing (global kill-switch)
                elif account.strategy.allowed_regimes is None:    # opt-out (no regimes= kwarg)
                    StrategyDataRouter._route_bar_to_account(account, bar)   # always-allow
                elif decision.current_state in account.strategy.allowed_regimes:
                    StrategyDataRouter._route_bar_to_account(account, bar)
                else:
                    log filtered (DEBUG) and skip
```

Note `HIGH_VOLATILITY` is checked **before** the per-strategy regime match — implements global kill-switch matching the FTMO drawdown protection requirement.

---

## 3. Public API

### `regime/states.py`

```python
class RegimeState(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"  # warmup
```

### `regime/decision.py`

```python
@dataclass(frozen=True)
class RegimeDecision:
    timestamp: datetime
    bar_type: str                     # "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"
    current_state: RegimeState        # post-hysteresis, what router uses
    raw_state: RegimeState            # what classifier produced this bar
    pending_state: RegimeState | None # if mid-transition
    bars_in_pending: int
    features: RegimeFeatures
    confidence: float                 # 0.0–1.0, derived from threshold margins
```

### `regime/features.py`

```python
@dataclass(frozen=True)
class RegimeFeatures:
    adx: float
    plus_di: float
    minus_di: float
    bb_width_pct: float           # current BB width / rolling-100 BB width (0–1 percentile)
    realized_vol: float           # annualised σ of log returns
    ema_slope: float              # (ema[t] - ema[t-N]) / ema[t-N]
    is_warmed_up: bool

class FeatureExtractor:
    def __init__(self, bar_type: str, config: InstrumentRegimeConfig) -> None: ...
    def update(self, bar: Bar) -> RegimeFeatures | None: ...
    @property
    def warmup_progress(self) -> float: ...   # 0.0–1.0
```

### `regime/classifier.py`

```python
class RuleBasedRegimeClassifier:
    """Pure: same features in → same state out, no hidden state."""
    def __init__(self, thresholds: RegimeThresholds) -> None: ...
    def decide(self, features: RegimeFeatures) -> RegimeState: ...
```

### `regime/hysteresis.py`

```python
class HysteresisFilter:
    """Per-BarType stateful: tracks current + pending + bars_in_pending."""
    def __init__(self, confirmation_bars: int = 2) -> None: ...
    def apply(self, raw: RegimeState, ts: datetime, bar_type: str) -> RegimeDecision: ...
    def snapshot(self) -> dict: ...     # for logging / debug
```

### `regime/audit.py`

```python
class RegimeAuditAdapter:
    """Translates RegimeDecision → AuditEntry, delegates to existing AuditLogger."""
    def __init__(self, audit_logger: AuditLogger) -> None: ...
    async def log(self, decision: RegimeDecision) -> None: ...
```

### `strategies/regime_routing.py`

```python
class RegimeAwareRouter:
    def __init__(
        self,
        inner: StrategyDataRouter,
        classifier: RuleBasedRegimeClassifier,
        feature_extractors: dict[str, FeatureExtractor],   # by bar_type str
        hysteresis: dict[str, HysteresisFilter],
        audit: RegimeAuditAdapter,
        strategy_regime_map: Mapping[str, frozenset[RegimeState] | None],  # None = always-allow
    ) -> None: ...

    def route_bar(self, bar: Bar) -> None: ...
    async def route_bar_async(self, bar: Bar) -> None: ...
```

Same surface as `StrategyDataRouter` — `redis_adapter.set_bar_callback(router.route_bar)` works unchanged.

---

## 4. State Ownership

| State | Owner | Lifetime | Persisted? |
|---|---|---|---|
| Rolling 200-bar OHLCV deque | `FeatureExtractor` (one per bar_type) | Process | No |
| Indicator internals (ADX, BB) | `FeatureExtractor` | Process | No |
| Current/pending regime + bars_in_pending | `HysteresisFilter` (one per bar_type) | Process | No (Phase 1) |
| Thresholds | `RegimeConfig` (immutable, loaded from YAML) | Process | YAML on disk |
| Strategy → regimes map | `StrategyRegistry` (class-level) | Process | Decorator metadata |

Pure components: `RuleBasedRegimeClassifier.decide`, all of `regime/decision.py`. Stateful: `FeatureExtractor`, `HysteresisFilter`, `RegimeAwareRouter`.

**Hysteresis on restart**: Phase 1 accepts loss. First 2 bars after warmup may show flicker. Persisting to Redis (`regime:{bar_type}:state`) is a Phase 2 add.

---

## 5. Audit Log Integration

Matches the existing rule audit pattern from `src/rules/audit_logger.py`:

```python
AuditEntry(
    timestamp=decision.timestamp,
    account_id=None,                            # regime is per-symbol, not per-account
    event_type="regime_decision",               # NEW value, free-form VARCHAR(50)
    rule_name="rule_based_regime_classifier",
    rule_result=decision.current_state.value.upper(),
    current_value=float(decision.features.adx),
    threshold_value=float(thresholds.adx_trend_min),
    order_id=None,
    context={
        "bar_type": decision.bar_type,
        "raw_state": decision.raw_state.value,
        "pending_state": decision.pending_state.value if decision.pending_state else None,
        "bars_in_pending": decision.bars_in_pending,
        "bb_width_pct": decision.features.bb_width_pct,
        "realized_vol": decision.features.realized_vol,
        "ema_slope": decision.features.ema_slope,
        "plus_di": decision.features.plus_di,
        "minus_di": decision.features.minus_di,
        "confidence": decision.confidence,
    },
    source="regime-classifier",
    level="INFO",
    message=f"Regime: {decision.current_state.value}",
)
```

Audit-before-routing: `audit.log(decision)` is awaited (async path) / scheduled with `asyncio.create_task` (sync path) before the per-account dispatch loop. Same pattern as `RuleEngine` → see `engine.py` for precedent.

`audit_logs` hypertable already exists; no Alembic migration needed. Volume: ~288 entries/day per (symbol, timeframe) on M5 — well within `AuditDBWriter` batch capacity (100/60s).

---

## 6. Config Schema

Thresholds live in firm profile (`configs/firms/ftmo.yaml`) under a new `regime_classifier` block:

```yaml
regime_classifier:
  enabled: false                          # opt-in feature flag
  confirmation_bars: 2
  warmup_bars: 50
  feature_window: 200
  instruments:
    XAUUSD:
      timeframe: M5                       # also accepts M15
      adx_trend_min: 25.0
      adx_strong_trend: 40.0
      bb_width_low_pct: 0.30              # below → ranging-eligible
      bb_width_high_pct: 0.80             # above → high-vol-eligible
      realized_vol_high: 0.025            # 2.5% annualised σ → high-vol-eligible
      ema_slope_period: 20
      ema_slope_trend_threshold: 0.0005   # |slope| > → trending-eligible
      bb_period: 20
      bb_stddev: 2.0
      bb_baseline_window: 100             # for percentile normalisation
      adx_period: 14
      realized_vol_window: 20
```

Pydantic models in `src/regime/config.py`:
- `RegimeConfig` (top-level)
- `RegimeThresholds` (per-instrument)
- `InstrumentRegimeConfig` (instrument metadata)

All `frozen=True`. Extends `FirmProfile` with optional `regime_classifier: RegimeConfig | None = None`.

---

## 7. Strategy → Regime Mapping

**Chosen: extend `register_strategy` decorator with optional `regimes=` kwarg.**

```python
@register_strategy("supertrend", regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN])
class SupertrendStrategy(BaseStrategy): ...

@register_strategy("rsi_mean_reversion", regimes=[RegimeState.RANGING])
class RSIMeanReversionStrategy(BaseStrategy): ...

@register_strategy("ma_crossover")  # no regimes → always-allow
class MACrossoverStrategy(BaseStrategy): ...
```

Phase 1 mapping:
- Supertrend, Donchian, MA Crossover → `[TRENDING_UP, TRENDING_DOWN]`
- RSI MR, Bollinger MR → `[RANGING]`
- ORB → `[]` (Phase 1: opt-out, will be wired in Phase 2)

**Why not YAML field**: forces config edits for all 6 strategies, decouples regime constraint from code.
**Why not shared lookup table**: bad cohesion — single place that has to know every strategy.

`StrategyRegistry` gains `_strategy_regimes: dict[str, frozenset[RegimeState] | None]`. Missing entry = `None` = always-allow (safe rollout).

---

## 8. Backward Compatibility

Two layers of opt-in:

1. **Feature flag in YAML**: `regime_classifier.enabled: false` by default. When false, bootstrap constructs plain `StrategyDataRouter`. Zero overhead, zero behavior change.

2. **Per-strategy opt-out**: strategies without `regimes=` are routed in any non-`HIGH_VOLATILITY` regime. `HIGH_VOLATILITY` blocks **all** strategies (global kill-switch).

Composition: `enabled: true` + no strategies declaring `regimes=` → only `HIGH_VOLATILITY` blocks routing, plus audit log per bar. Useful for shadow-mode validation.

---

## 9. Integration / Wiring

Router construction sites identified:
- `services/trading-engine/src/strategies/account_binding.py:40` (single-account helper)
- `services/trading-engine/src/strategies/account_binding.py:136` (multi-account `bind_strategies_to_accounts`)
- `services/trading-engine/src/strategies/data_router.py:14-17, 66` (docstring examples)

Wiring change in `account_binding.py`:

```python
# BEFORE
router = StrategyDataRouter(bound_accounts)
redis_adapter.set_bar_callback(router.route_bar)

# AFTER
inner = StrategyDataRouter(bound_accounts)
if firm_profile.regime_classifier and firm_profile.regime_classifier.enabled:
    router = build_regime_aware_router(inner, firm_profile.regime_classifier, audit_logger)
else:
    router = inner
redis_adapter.set_bar_callback(router.route_bar)
```

`build_regime_aware_router` factory in `src/regime/__init__.py` constructs all dependencies.

---

## 10. Testing Strategy

| Layer | What to test | How |
|---|---|---|
| `classifier.py` | All 4 states + threshold edge cases | Pure unit tests, build `RegimeFeatures` literals, no mocks |
| `hysteresis.py` | 2-bar confirmation, flicker prevention | Drive sequences of `RegimeState`, assert decisions |
| `features.py` | Warmup, rolling window, indicator wiring | Synthetic OHLCV via `nautilus_trader.test_kit` |
| `audit.py` | `AuditEntry` field mapping | Mock `AuditLogger`, assert payload |
| `regime_routing.py` | E2E routing with regime gate | 3 fake strategies (trending, ranging, universal), assert dispatched set |
| `config.py` | Pydantic validation, missing-instrument fallback | Round-trip YAML → model |
| Integration | Bar pipeline → classifier → audit Redis → audit DB | `pytest -m integration`, real Redis + Postgres |

Fixtures:
- `tests/regime/fixtures/xauusd_trending_up.csv` (~300 M5 bars, clean uptrend)
- `tests/regime/fixtures/xauusd_ranging.csv`
- `tests/regime/fixtures/xauusd_high_vol.csv`
- `tests/regime/fixtures/xauusd_regime_transition.csv` (forces flicker scenario)

`fakeredis.aioredis` for Redis mocking (precedent: `tests/rules/test_audit_logger.py`).

Coverage target: 90%+ on `classifier.py` and `hysteresis.py` (pure logic), 80%+ elsewhere.

---

## Resolved Open Questions

| # | Question | Decision |
|---|---|---|
| 1 | Where is router constructed? | `account_binding.py:40, 136` — wrap by replacing constructor calls |
| 2 | Per-account vs per-symbol classifier? | Per-(symbol, timeframe) — keyed by `bar_type`, shared across accounts trading same instrument |
| 3 | Persist hysteresis on restart? | No (Phase 1) — accept first-2-bar flicker risk |
| 4 | `HIGH_VOLATILITY` blocks all? | **Yes** — global kill-switch including always-allow strategies |
| 5 | BB width baseline window? | 100 bars rolling |
| 6 | Audit volume? | OK — within `AuditDBWriter` capacity |
| 7 | Multi-timeframe key? | `BarType` (string), e.g. `XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL` |

No remaining blocking questions for Phase 1.
