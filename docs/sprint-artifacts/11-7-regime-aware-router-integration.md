# Story 11.7: RegimeAwareRouter Integration — Wire classifier into bar pipeline

Status: Backlog

**Effort:** XL
**Phase:** 11.D — Integration
**Predecessor:** Stories 11.4 (`HysteresisFilter`), 11.5 (`RegimeAuditAdapter`), 11.6 (decorator)
**Successor:** Phase 2 HMM classifier (deferred)
**Source:** `docs/research/regime-classifier-architecture.md` §2 (call graph), §9 (integration)

## Story

As a **maintainer of the Sandboxed trading engine**,
I want **bar pipeline đi qua `RegimeAwareRouter` để classify market regime trước khi route tới strategies, với feature flag `regime_classifier.enabled` mặc định false để rollout an toàn**,
So that **strategies chỉ nhận bar khi market regime phù hợp (e.g. Supertrend chỉ trade khi TRENDING, RSI MR chỉ trade khi RANGING), HIGH_VOLATILITY block toàn bộ trading như kill-switch FTMO daily-loss, và rollback bằng cách flip một dòng YAML thành false**.

## Background

Sau Stories 11.1–11.6, các thành phần đã sẵn:

- `FeatureExtractor`, `RuleBasedRegimeClassifier`, `HysteresisFilter`, `RegimeAuditAdapter` đều test được độc lập.
- `register_strategy(regimes=...)` decorator hoạt động, `StrategyRegistry._strategy_regimes` map đã có.
- `RegimeConfig` pydantic loaded từ `configs/firms/ftmo.yaml` (`enabled: false` mặc định).

Còn thiếu **integration point** giữa các thành phần đó với `StrategyDataRouter` hiện hữu. Architecture §9 chỉ ra wiring sites:

- `services/trading-engine/src/strategies/account_binding.py:40` (single-account helper `bind_strategy_to_account`)
- `services/trading-engine/src/strategies/account_binding.py:136` (multi-account `bind_strategies_to_accounts`)

Cả hai đều construct `StrategyDataRouter(...)` rồi gọi `redis_adapter.set_bar_callback(router.route_bar)`. Story này:

1. Tạo `RegimeAwareRouter` wrap `StrategyDataRouter` — drop-in compatible (cùng surface `route_bar` / `route_bar_async`).
2. Tạo factory `build_regime_aware_router(inner, regime_config, audit_logger)` ở `src/regime/__init__.py` instantiate per-`bar_type` extractors + filters.
3. Sửa 2 wiring sites: nếu `regime_config.enabled=True` thì wrap, ngược lại return inner unchanged.
4. Thêm `regimes=[...]` vào `@register_strategy` calls của 6 strategies hiện hữu (one-line change per file).
5. E2E tests với 4 CSV fixtures (trending up / ranging / high_vol / transition).

## Acceptance Criteria

### AC1 — `RegimeAwareRouter` API drop-in compatible

`src/strategies/regime_routing.py`:

```python
class RegimeAwareRouter:
    def __init__(
        self,
        inner: StrategyDataRouter,
        classifier: RuleBasedRegimeClassifier,
        feature_extractors: dict[str, FeatureExtractor],
        hysteresis: dict[str, HysteresisFilter],
        audit: RegimeAuditAdapter,
        strategy_regime_map: Mapping[str, frozenset[RegimeState] | None],
    ) -> None: ...

    def route_bar(self, bar: Bar) -> None: ...
    async def route_bar_async(self, bar: Bar) -> None: ...
```

`redis_adapter.set_bar_callback(router.route_bar)` work unchanged — không cần thay đổi `RedisAdapter`.

### AC2 — Call graph đúng order

Trong `route_bar` (sync) và `route_bar_async`:

```
1. extractor = feature_extractors[bar.bar_type]   # KeyError → log WARNING + skip
2. features = extractor.update(bar)
3. if features is None or not features.is_warmed_up:  # warmup
       return  # không log audit, không route
4. raw_state = classifier.decide(features)
5. decision = hysteresis[bar.bar_type].apply(raw_state, bar.ts_event, str(bar.bar_type), features)
6. # AUDIT BEFORE ROUTING (FTMO compliance pattern)
   audit.log(decision)  # async path: await; sync path: asyncio.create_task
7. if decision.current_state == RegimeState.HIGH_VOLATILITY:
       return  # global kill-switch
8. for bound_account in inner.bound_accounts:
       allowed = strategy_regime_map.get(bound_account.strategy_name)
       if allowed is None:                       # always-allow strategies
           inner._route_bar_to_account(bound_account, bar)
       elif decision.current_state in allowed:
           inner._route_bar_to_account(bound_account, bar)
       else:
           pass  # skip silently (log DEBUG)
```

### AC3 — Feature flag parity

Với `firm_profile.regime_classifier.enabled = False`:

- Bootstrap (factory) returns plain `StrategyDataRouter`, không wrap.
- Test parity: 100-bar fixture → byte-identical routing decisions vs baseline `8f42b5c` (Epic 10 head).
- Zero overhead per bar (không tạo classifier, không alloc deque).

### AC4 — HIGH_VOLATILITY global kill-switch

Even strategies với `regimes=None` (always-allow contract từ Story 11.6) **vẫn bị block** khi `current_state=HIGH_VOLATILITY`. Test:

```python
def test_high_vol_blocks_all_strategies_including_always_allow():
    # bound_accounts: 1 with regimes=[TRENDING_UP], 1 with regimes=None (MA Crossover)
    # feed bar with features triggering HIGH_VOL
    # expect: BOTH accounts skipped, neither receives bar
```

### AC5 — Multi-`BarType` isolation

`feature_extractors` và `hysteresis` keyed bằng `str(bar.bar_type)` (e.g., `XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL` vs `XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL`). Concurrent M5 + M15 bars **không cross-contaminate** state. Test:

```python
def test_multi_bar_type_isolation():
    # feed 100 M5 bars (trending up) and 100 M15 bars (ranging) interleaved
    # assert: M5 hysteresis ends in TRENDING_UP, M15 ends in RANGING
    # assert: 2 distinct extractor instances, 2 distinct hysteresis instances
```

### AC6 — 6 strategy decorator updates

Sửa 6 file strategy thêm `regimes=[...]`. Diff = 1 line per file:

```python
# src/strategies/supertrend.py
@register_strategy("supertrend", regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN])
class SupertrendStrategy(BaseStrategy): ...

# src/strategies/donchian_breakout.py
@register_strategy("donchian_breakout", regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN])

# src/strategies/ma_crossover.py
@register_strategy("ma_crossover", regimes=[RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN])

# src/strategies/rsi_mean_reversion.py
@register_strategy("rsi_mean_reversion", regimes=[RegimeState.RANGING])

# src/strategies/bollinger_mean_reversion.py
@register_strategy("bollinger_mean_reversion", regimes=[RegimeState.RANGING])

# src/strategies/orb.py
@register_strategy("orb", regimes=[])  # Phase 1: explicit opt-out, wires lại Phase 2
```

**Không thay đổi behavior** bên trong strategy class.

### AC7 — E2E test với CSV fixtures

`tests/regime/fixtures/`:

- `xauusd_trending_up.csv` (~300 M5 bars, clean uptrend, ADX>30, +DI>>−DI)
- `xauusd_ranging.csv` (~300 M5 bars, sideways, ADX<20, BB width pct < 0.3)
- `xauusd_high_vol.csv` (~300 M5 bars, large gaps, BB width pct > 0.85)
- `xauusd_regime_transition.csv` (~300 M5 bars: 100 ranging → 100 trending up → 100 high_vol; tests hysteresis)

Each fixture asserts:
- Final `current_state` matches expected.
- Audit row count = bar count − warmup_bars.
- Routing decisions match expected per-state strategy set (3 fake strategies: trending-only, ranging-only, always-allow).

### AC8 — Bootstrap factory

`src/regime/__init__.py`:

```python
def build_regime_aware_router(
    inner: StrategyDataRouter,
    regime_config: RegimeConfig,
    audit_logger: AuditLogger,
) -> RegimeAwareRouter | StrategyDataRouter:
    """Returns wrapped router if regime_config.enabled, else inner unchanged."""
    if not regime_config.enabled:
        return inner

    # Build per-bar_type extractors + hysteresis from bound_accounts' bar_types
    bar_types = {str(b.strategy.bar_type) for b in inner.bound_accounts}
    extractors = {bt: FeatureExtractor(bt, regime_config.instruments[symbol_of(bt)])
                  for bt in bar_types}
    hysteresis = {bt: HysteresisFilter(regime_config.confirmation_bars)
                  for bt in bar_types}
    classifier = RuleBasedRegimeClassifier(...)
    audit_adapter = RegimeAuditAdapter(audit_logger)
    strategy_map = StrategyRegistry.get_all_regime_maps()

    return RegimeAwareRouter(
        inner=inner,
        classifier=classifier,
        feature_extractors=extractors,
        hysteresis=hysteresis,
        audit=audit_adapter,
        strategy_regime_map=strategy_map,
    )
```

### AC9 — Wiring change in `account_binding.py`

Both `bind_strategy_to_account` (line ~40) và `bind_strategies_to_accounts` (line ~136) sửa:

```python
# BEFORE
router = StrategyDataRouter(bound_accounts)
redis_adapter.set_bar_callback(router.route_bar)

# AFTER
inner = StrategyDataRouter(bound_accounts)
regime_config = firm_profile.regime_classifier  # may be None
if regime_config and regime_config.enabled:
    router = build_regime_aware_router(inner, regime_config, audit_logger)
else:
    router = inner
redis_adapter.set_bar_callback(router.route_bar)
```

Audit logger inject qua existing `EngineConfig` DI (Story 10.2). `firm_profile` đã có sẵn ở wiring site.

### AC10 — Regression baseline

- `tests/integration/test_multi_firm_e2e.py` (Epic 9 baseline 22 tests) **vẫn pass** với `regime_classifier.enabled: false` (default).
- Với `enabled: true` chỉ trên FTMO profile: the5ers profiles unaffected, multi-firm parity tests pass.
- Full unit suite (pre-Epic-11 count + new tests) green.
- Coverage ≥ 80% trên `regime_routing.py` và modified lines của `account_binding.py`.

## Test Plan

### Unit tests (`tests/unit/strategies/test_regime_aware_router.py`)

- `test_route_bar_calls_classifier_then_audit_then_dispatch`
- `test_high_vol_blocks_all_strategies_including_always_allow` (AC4)
- `test_multi_bar_type_isolation` (AC5)
- `test_audit_called_before_per_account_dispatch`
- `test_warmup_period_blocks_routing` (UNKNOWN state, no audit)
- `test_strategy_with_empty_regimes_never_routes` (ORB Phase 1)
- `test_strategy_with_none_regimes_routes_in_all_non_high_vol`
- `test_async_path_awaits_audit`
- `test_sync_path_creates_task_for_audit`

### Integration tests (`tests/integration/regime/test_router_e2e.py`)

- `test_trending_up_routes_to_trend_strategies` (AC7 fixture 1)
- `test_ranging_routes_to_mr_strategies` (AC7 fixture 2)
- `test_high_vol_routes_to_nothing` (AC7 fixture 3)
- `test_regime_transition_with_hysteresis` (AC7 fixture 4)
- `test_feature_flag_off_byte_identical_to_baseline` (AC3)
- `test_audit_row_count_matches_bar_count_post_warmup`

### Existing test parity (regression)

- `tests/integration/test_multi_firm_e2e.py` (22 tests) green with `enabled: false`.

## Files Created

```
services/trading-engine/src/strategies/regime_routing.py     # RegimeAwareRouter
services/trading-engine/src/regime/__init__.py               # full version + factory
tests/unit/strategies/test_regime_aware_router.py
tests/integration/regime/test_router_e2e.py
tests/regime/fixtures/xauusd_trending_up.csv
tests/regime/fixtures/xauusd_ranging.csv
tests/regime/fixtures/xauusd_high_vol.csv
tests/regime/fixtures/xauusd_regime_transition.csv
tests/regime/fixtures/__init__.py                            # fixture loader helper
```

## Files Modified

```
services/trading-engine/src/strategies/account_binding.py   # 2 wiring sites (lines ~40, 136)
services/trading-engine/src/strategies/data_router.py       # docstring only — _route_bar_to_account is now part of stable contract
services/trading-engine/src/strategies/supertrend.py        # +1 line (regimes=)
services/trading-engine/src/strategies/donchian_breakout.py # +1 line
services/trading-engine/src/strategies/ma_crossover.py      # +1 line
services/trading-engine/src/strategies/rsi_mean_reversion.py # +1 line
services/trading-engine/src/strategies/bollinger_mean_reversion.py # +1 line
services/trading-engine/src/strategies/orb.py               # +1 line (regimes=[])
```

## Out of Scope

- HMM classifier (Phase 2)
- Hurst exponent feature (Phase 2)
- Redis hysteresis state persistence (Phase 2 — accept first-2-bar flicker post-restart)
- Per-account regime override
- Multi-instrument beyond XAUUSD (FX majors deferred)
- the5ers.yaml regime config block (FTMO only Phase 1)
- ORB regime mapping (Phase 1 = `regimes=[]`, Phase 2 wires ORB into `[HIGH_VOLATILITY]` after volatility-targeted strategy validation)
- Atomic model swap mid-session (Phase 2)
- Per-strategy regime threshold override (everyone uses same `RegimeThresholds` from firm config)

## Rollout Plan

1. Ship Story 11.7 with `enabled: false` ở `configs/firms/ftmo.yaml` → no production behavior change.
2. **Shadow mode** (optional, post-merge): bật `enabled: true` trên FTMO test account → quan sát audit logs trong 48h, verify regime classifications match manual chart inspection.
3. **Cutover**: bật `enabled: true` cho production FTMO accounts một cách progressive (1 account → 3 accounts → all).
4. **Rollback**: flip `enabled: false`, restart engine. No state migration needed (Phase 1 hysteresis là process-local).

## Reviewer Sign-off Checklist

- [ ] `python-reviewer`: type hints, docstrings, immutability where claimed
- [ ] `security-reviewer`: financial routing path — confirm audit-before-routing, no PII leakage in `context`, no credential leakage, fail-closed semantics on KeyError
- [ ] Coverage ≥ 80% on `regime_routing.py`
- [ ] AST grep test confirms no hardcoded thresholds in `regime_routing.py`
- [ ] `tests/integration/test_multi_firm_e2e.py` 22 tests still pass

## References

- **Epic context:** `docs/epic-11-context.md`
- **Architecture:** `docs/research/regime-classifier-architecture.md` §2 (call graph), §3 (API), §9 (integration)
- **Research:** `docs/research/regime-classifier.md` §Recommended Feature Set, §Pitfalls
- **Existing audit pattern precedent:** `services/trading-engine/src/engine/...` (RuleEngine audit-before-decide), Story 10.3 commit `4e0c76d`
- **Account binding sites:** `services/trading-engine/src/strategies/account_binding.py:40, 136`
