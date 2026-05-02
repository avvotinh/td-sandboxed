"""Unit tests for ``RegimeAwareRouter`` (Epic 11 story 11.7).

The router sits between the bar callback (``redis_adapter.set_bar_callback``)
and ``StrategyDataRouter._route_bar_to_account``. For each bar it:

1. Updates the per-``BarType`` :class:`FeatureExtractor`
2. Runs the pure :class:`RuleBasedRegimeClassifier`
3. Confirms via :class:`HysteresisFilter`
4. **Awaits** the audit hop (FTMO compliance: audit before routing)
5. Skips routing entirely when ``current_state == HIGH_VOLATILITY``
6. Otherwise delegates to ``inner._route_bar_to_account`` for each bound
   account whose declared regimes admit the current state

These tests stub the feature extractor (which has heavy warmup behaviour)
and exercise the orchestration logic against real classifier, hysteresis,
and audit components.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import Mock

import pytest

from src.config.firm_profile import RegimeThresholds
from src.regime.audit import RegimeAuditAdapter
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import RegimeFeatures
from src.regime.hysteresis import HysteresisFilter
from src.regime.states import RegimeState
from src.rules.audit_logger import AuditEntry
from src.strategies.regime_routing import RegimeAwareRouter

M5_BAR_TYPE = "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"
M15_BAR_TYPE = "XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubExtractor:
    """Returns a fixed ``RegimeFeatures`` (or None) per ``update`` call."""

    def __init__(self, emits: RegimeFeatures | None) -> None:
        self.emits = emits
        self.calls: list[Any] = []

    def update(self, bar: Any) -> RegimeFeatures | None:
        self.calls.append(bar)
        return self.emits


class _RecordingInner:
    """Inner router stand-in: records (account, bar) dispatches."""

    def __init__(self, accounts: list[Any]) -> None:
        self._accounts = accounts
        self.dispatches: list[tuple[Any, Any]] = []
        self.tick_dispatches: list[Any] = []

    @property
    def bound_accounts(self) -> list[Any]:
        return list(self._accounts)

    def _route_bar_to_account(self, account: Any, bar: Any) -> None:
        self.dispatches.append((account, bar))

    def route_tick(self, tick: Any) -> None:
        self.tick_dispatches.append(tick)

    async def route_tick_async(self, tick: Any) -> None:
        self.tick_dispatches.append(tick)


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log_async(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _thresholds() -> RegimeThresholds:
    return RegimeThresholds(
        adx_trend_min=25.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.30,
        bb_width_high_pct=0.80,
        realized_vol_high=0.025,
        ema_slope_trend_threshold=0.0005,
    )


def _features(**overrides: object) -> RegimeFeatures:
    base: dict[str, Any] = dict(
        adx=30.0,
        plus_di=30.0,
        minus_di=15.0,
        bb_width_pct=0.50,
        realized_vol=0.012,
        ema_slope=0.001,
        is_warmed_up=True,
    )
    base.update(overrides)
    return RegimeFeatures(**base)


def _trend_up_features() -> RegimeFeatures:
    return _features(adx=30.0, plus_di=30.0, minus_di=15.0, ema_slope=0.001)


def _ranging_features() -> RegimeFeatures:
    return _features(
        adx=15.0, plus_di=20.0, minus_di=20.0, bb_width_pct=0.20, ema_slope=0.0
    )


def _high_vol_features() -> RegimeFeatures:
    return _features(bb_width_pct=0.95, realized_vol=0.05)


def _bar(bar_type: str = M5_BAR_TYPE) -> Mock:
    """Minimal bar carrying ``bar_type`` and ``ts_event`` (tz-aware)."""
    bar = Mock()
    bar.bar_type = bar_type
    bar.ts_event = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    return bar


def _account(strategy_name: str) -> Mock:
    a = Mock()
    a.strategy = strategy_name
    return a


def _build_router(
    *,
    extractors: dict[str, _StubExtractor],
    inner: _RecordingInner,
    strategy_regime_map: dict[str, frozenset[RegimeState] | None],
    confirmation_bars: int = 1,
) -> tuple[RegimeAwareRouter, _RecordingAuditWriter]:
    """Construct a router with real classifier + hysteresis + audit
    adapter; ``confirmation_bars=1`` removes hysteresis lag in tests."""
    thresholds = _thresholds()
    classifier = RuleBasedRegimeClassifier(thresholds)
    hysteresis = {
        bt: HysteresisFilter(
            bar_type=bt,
            confirmation_bars=confirmation_bars,
            thresholds=thresholds,
        )
        for bt in extractors
    }
    writer = _RecordingAuditWriter()
    audit = RegimeAuditAdapter(writer)
    router = RegimeAwareRouter(
        inner=inner,
        classifier=classifier,
        feature_extractors=extractors,  # type: ignore[arg-type]
        hysteresis=hysteresis,
        audit=audit,
        strategy_regime_map=strategy_regime_map,
    )
    return router, writer


# ---------------------------------------------------------------------------
# Warmup / unknown bar_type
# ---------------------------------------------------------------------------


class TestWarmupAndMissingBarType:
    @pytest.mark.asyncio
    async def test_warmup_skips_audit_and_routing(self):
        # Extractor returns None during warmup → nothing is emitted: no
        # audit row, no per-account dispatch. The kill-switch is undefined
        # while features are undefined.
        inner = _RecordingInner([_account("ma_crossover")])
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=None)}
        router, writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={"ma_crossover": None},
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert writer.entries == []
        assert inner.dispatches == []

    @pytest.mark.asyncio
    async def test_unknown_bar_type_logs_and_skips(
        self, caplog: pytest.LogCaptureFixture
    ):
        # An incoming bar whose bar_type is not in feature_extractors must
        # not crash the router. Story 11.7 AC2: log WARNING and skip.
        inner = _RecordingInner([_account("ma_crossover")])
        extractors: dict[str, _StubExtractor] = {}
        router, writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={"ma_crossover": None},
        )
        with caplog.at_level("WARNING"):
            await router.route_bar_async(_bar("UNKNOWN-BAR-TYPE"))
        assert writer.entries == []
        assert inner.dispatches == []
        assert any("UNKNOWN-BAR-TYPE" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# HIGH_VOLATILITY kill-switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    @pytest.mark.asyncio
    async def test_high_vol_blocks_every_strategy_including_always_allow(self):
        # Critical FTMO contract: HIGH_VOL must block routing for every
        # account, including those registered with regimes=None
        # (always-allow). The kill-switch is global.
        accounts = [_account("supertrend"), _account("ma_crossover")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_high_vol_features())}
        router, writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={
                "supertrend": frozenset(
                    {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
                ),
                "ma_crossover": None,  # always-allow
            },
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert inner.dispatches == []
        # Kill-switch fired but the audit row still landed — auditability
        # requires every regime call to surface, including blocked ones.
        assert len(writer.entries) == 1
        assert writer.entries[0].rule_result == "high_volatility"
        assert writer.entries[0].level == "WARNING"


# ---------------------------------------------------------------------------
# Per-strategy regime filtering
# ---------------------------------------------------------------------------


class TestRegimeFiltering:
    @pytest.mark.asyncio
    async def test_routes_to_strategy_whose_regime_matches(self):
        accounts = [_account("supertrend"), _account("rsi_mean_reversion")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_trend_up_features())}
        router, _writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={
                "supertrend": frozenset(
                    {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
                ),
                "rsi_mean_reversion": frozenset({RegimeState.RANGING}),
            },
        )
        bar = _bar(M5_BAR_TYPE)
        await router.route_bar_async(bar)
        assert [d[0].strategy for d in inner.dispatches] == ["supertrend"]
        assert all(d[1] is bar for d in inner.dispatches)

    @pytest.mark.asyncio
    async def test_strategy_with_none_regimes_is_always_allow_outside_high_vol(
        self,
    ):
        accounts = [_account("ma_crossover")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_ranging_features())}
        router, _writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={"ma_crossover": None},
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert len(inner.dispatches) == 1

    @pytest.mark.asyncio
    async def test_strategy_with_empty_regimes_never_routes(self):
        # ORB Phase 1: regimes=[] is the explicit opt-out (distinguished
        # from None which means always-allow). ORB must never see a bar.
        accounts = [_account("orb")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_trend_up_features())}
        router, _writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={"orb": frozenset()},
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert inner.dispatches == []

    @pytest.mark.asyncio
    async def test_strategy_unknown_to_regime_map_is_always_allow(self):
        # Backwards compat: if a strategy was registered before story 11.6
        # added the regimes kwarg, its name will be missing from the
        # regime map; treat as None (always-allow) rather than crash.
        accounts = [_account("legacy_strategy")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_ranging_features())}
        router, _writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={},  # legacy not in the map
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert len(inner.dispatches) == 1


# ---------------------------------------------------------------------------
# Audit ordering
# ---------------------------------------------------------------------------


class TestAuditOrdering:
    @pytest.mark.asyncio
    async def test_audit_runs_before_per_account_dispatch(self):
        # Order must be: audit.log → dispatch. Capture the call ordering
        # via a writer that records timestamps relative to inner.
        order: list[str] = []

        class _OrderingWriter:
            async def log_async(self, entry: AuditEntry) -> None:
                order.append("audit")

        class _OrderingInner(_RecordingInner):
            def _route_bar_to_account(self, account: Any, bar: Any) -> None:
                order.append("dispatch")
                super()._route_bar_to_account(account, bar)

        accounts = [_account("ma_crossover")]
        inner = _OrderingInner(accounts)
        thresholds = _thresholds()
        classifier = RuleBasedRegimeClassifier(thresholds)
        hysteresis = {
            M5_BAR_TYPE: HysteresisFilter(
                bar_type=M5_BAR_TYPE,
                confirmation_bars=1,
                thresholds=thresholds,
            )
        }
        audit = RegimeAuditAdapter(_OrderingWriter())  # type: ignore[arg-type]
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_trend_up_features())}
        router = RegimeAwareRouter(
            inner=inner,
            classifier=classifier,
            feature_extractors=extractors,  # type: ignore[arg-type]
            hysteresis=hysteresis,
            audit=audit,
            strategy_regime_map={"ma_crossover": None},
        )
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert order == ["audit", "dispatch"]


# ---------------------------------------------------------------------------
# Tick pass-through (regime gates bars only)
# ---------------------------------------------------------------------------


class TestTickPassthrough:
    @pytest.mark.asyncio
    async def test_route_tick_async_delegates_to_inner(self):
        # Ticks are not regime-gated; the wrapper must forward unchanged
        # so a ``zmq_adapter.set_tick_callback(wrapper.route_tick)`` wiring
        # does not surface as AttributeError.
        inner = _RecordingInner([_account("x")])
        router, _writer = _build_router(
            extractors={M5_BAR_TYPE: _StubExtractor(emits=None)},
            inner=inner,
            strategy_regime_map={"x": None},
        )
        tick = Mock()
        await router.route_tick_async(tick)
        assert inner.tick_dispatches == [tick]

    def test_route_tick_delegates_to_inner(self):
        inner = _RecordingInner([_account("x")])
        router, _writer = _build_router(
            extractors={M5_BAR_TYPE: _StubExtractor(emits=None)},
            inner=inner,
            strategy_regime_map={"x": None},
        )
        tick = Mock()
        router.route_tick(tick)
        assert inner.tick_dispatches == [tick]


# ---------------------------------------------------------------------------
# Defensive copy of strategy_regime_map
# ---------------------------------------------------------------------------


class TestRegimeMapImmutability:
    @pytest.mark.asyncio
    async def test_caller_mutation_does_not_affect_routing(self):
        # If the wrapper held a live reference, swapping a strategy from
        # always-allow to never-route post-construction would silently
        # change live routing without re-issuing the audit row.
        inner = _RecordingInner([_account("legacy")])
        live_map: dict[str, frozenset[RegimeState] | None] = {"legacy": None}
        router, _writer = _build_router(
            extractors={M5_BAR_TYPE: _StubExtractor(emits=_trend_up_features())},
            inner=inner,
            strategy_regime_map=live_map,
        )
        live_map["legacy"] = frozenset()  # would be "never route" if held live
        await router.route_bar_async(_bar(M5_BAR_TYPE))
        assert len(inner.dispatches) == 1


# ---------------------------------------------------------------------------
# Multi-BarType isolation
# ---------------------------------------------------------------------------


class TestMultiBarTypeIsolation:
    @pytest.mark.asyncio
    async def test_m5_and_m15_bars_use_distinct_extractors(self):
        accounts = [_account("supertrend")]
        inner = _RecordingInner(accounts)
        m5_ext = _StubExtractor(emits=_trend_up_features())
        m15_ext = _StubExtractor(emits=_ranging_features())
        extractors = {M5_BAR_TYPE: m5_ext, M15_BAR_TYPE: m15_ext}
        router, _writer = _build_router(
            extractors=extractors,
            inner=inner,
            strategy_regime_map={
                "supertrend": frozenset(
                    {RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN}
                )
            },
        )
        m5_bar = _bar(M5_BAR_TYPE)
        m15_bar = _bar(M15_BAR_TYPE)
        await router.route_bar_async(m5_bar)
        await router.route_bar_async(m15_bar)
        assert m5_ext.calls == [m5_bar]
        assert m15_ext.calls == [m15_bar]
        # m5 routes (TRENDING_UP matches), m15 does not (RANGING).
        assert [d[1] for d in inner.dispatches] == [m5_bar]


# ---------------------------------------------------------------------------
# Sync-path behaviour
# ---------------------------------------------------------------------------


class TestSyncPath:
    def test_sync_route_bar_schedules_audit_and_dispatches(self):
        # Sync path is invoked from a callback that itself runs inside the
        # event loop; asyncio.create_task schedules the audit and dispatch
        # continues immediately. Driving this in a test means running the
        # call inside a loop and yielding to drain the task.
        accounts = [_account("ma_crossover")]
        inner = _RecordingInner(accounts)
        extractors = {M5_BAR_TYPE: _StubExtractor(emits=_trend_up_features())}

        async def driver() -> tuple[
            _RecordingInner, _RecordingAuditWriter
        ]:
            router, writer = _build_router(
                extractors=extractors,
                inner=inner,
                strategy_regime_map={"ma_crossover": None},
            )
            router.route_bar(_bar(M5_BAR_TYPE))
            # Yield once so the scheduled audit task can run.
            await asyncio.sleep(0)
            return inner, writer

        inner_done, writer = asyncio.run(driver())
        assert len(inner_done.dispatches) == 1
        assert len(writer.entries) == 1


# ---------------------------------------------------------------------------
# Factory — build_regime_aware_router
# ---------------------------------------------------------------------------


def _instrument_cfg() -> Any:
    from src.config.firm_profile import (
        InstrumentRegimeConfig,
        RegimeThresholds,
    )

    return InstrumentRegimeConfig(
        timeframe="M5",
        thresholds=RegimeThresholds(
            adx_trend_min=25.0,
            adx_strong_trend=40.0,
            bb_width_low_pct=0.30,
            bb_width_high_pct=0.80,
            realized_vol_high=0.025,
            ema_slope_trend_threshold=0.0005,
        ),
        adx_period=14,
        bb_period=20,
        bb_stddev=2.0,
        bb_baseline_window=100,
        realized_vol_window=20,
        ema_slope_period=20,
        ema_slope_lookback=5,
    )


def _regime_config(*, enabled: bool = True) -> Any:
    from src.config.firm_profile import RegimeConfig

    return RegimeConfig(
        enabled=enabled,
        confirmation_bars=2,
        warmup_bars=50,
        feature_window=200,
        instruments={"XAUUSD": _instrument_cfg()},
    )


def _bound_account_with_bar_type(bar_type: str, strategy_name: str) -> Mock:
    """Bound-account stand-in: ``.strategy_instance.config.bar_type``."""
    a = Mock()
    a.strategy = strategy_name
    a.strategy_instance.config.bar_type = bar_type
    return a


class TestFactoryDisabled:
    def test_returns_inner_unchanged_when_disabled(self):
        # Story 11.7 AC3: default-shipped enabled=False must be byte-
        # identical with the legacy pipeline — the wrapper is not built
        # and no extractors are allocated.
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner(
            [_bound_account_with_bar_type(M5_BAR_TYPE, "supertrend")]
        )
        out = build_regime_aware_router(
            inner=inner,  # type: ignore[arg-type]
            regime_config=_regime_config(enabled=False),
            audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
        )
        assert out is inner

    def test_enabled_with_no_bound_accounts_returns_inner(self):
        # Operators flipping the flag on an empty engine must not see it
        # crash — the empty case is logically equivalent to disabled.
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner([])
        out = build_regime_aware_router(
            inner=inner,  # type: ignore[arg-type]
            regime_config=_regime_config(enabled=True),
            audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
        )
        assert out is inner


class TestFactoryEnabled:
    def test_returns_wrapped_router(self):
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner(
            [_bound_account_with_bar_type(M5_BAR_TYPE, "supertrend")]
        )
        out = build_regime_aware_router(
            inner=inner,  # type: ignore[arg-type]
            regime_config=_regime_config(enabled=True),
            audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
            strategy_regime_map={
                "supertrend": frozenset({RegimeState.TRENDING_UP})
            },
        )
        assert isinstance(out, RegimeAwareRouter)

    def test_builds_one_extractor_per_unique_bar_type(self):
        # Two accounts on M5 + one on M15 → 2 extractors.
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner(
            [
                _bound_account_with_bar_type(M5_BAR_TYPE, "supertrend"),
                _bound_account_with_bar_type(M5_BAR_TYPE, "rsi_mean_reversion"),
                _bound_account_with_bar_type(M15_BAR_TYPE, "donchian_breakout"),
            ]
        )
        router = build_regime_aware_router(
            inner=inner,  # type: ignore[arg-type]
            regime_config=_regime_config(enabled=True),
            audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
            strategy_regime_map={
                "supertrend": frozenset({RegimeState.TRENDING_UP}),
                "rsi_mean_reversion": frozenset({RegimeState.RANGING}),
                "donchian_breakout": frozenset({RegimeState.TRENDING_UP}),
            },
        )
        assert isinstance(router, RegimeAwareRouter)
        # Inspect via private attrs — wiring shape is the contract this
        # test pins.
        assert set(router._extractors) == {M5_BAR_TYPE, M15_BAR_TYPE}
        assert set(router._hysteresis) == {M5_BAR_TYPE, M15_BAR_TYPE}

    def test_multi_symbol_raises_not_implemented(self):
        # Phase 1 ships a single classifier; multi-symbol deployments
        # must fail loudly rather than silently classify EURUSD against
        # XAUUSD's calibration.
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner(
            [
                _bound_account_with_bar_type(
                    "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL", "supertrend"
                ),
                _bound_account_with_bar_type(
                    "EURUSD.BROKER-5-MINUTE-LAST-EXTERNAL", "supertrend"
                ),
            ]
        )
        with pytest.raises(NotImplementedError, match="single instrument"):
            build_regime_aware_router(
                inner=inner,  # type: ignore[arg-type]
                regime_config=_regime_config(enabled=True),
                audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
                strategy_regime_map={
                    "supertrend": frozenset({RegimeState.TRENDING_UP})
                },
            )

    def test_unknown_symbol_in_bar_type_raises(self):
        # bar_type with no matching instrument config must surface
        # loudly rather than silently dropping the stream from
        # classification.
        from src.regime.factory import build_regime_aware_router

        inner = _RecordingInner(
            [_bound_account_with_bar_type(
                "EURUSD.BROKER-5-MINUTE-LAST-EXTERNAL", "supertrend"
            )]
        )
        with pytest.raises(KeyError, match="EURUSD"):
            build_regime_aware_router(
                inner=inner,  # type: ignore[arg-type]
                regime_config=_regime_config(enabled=True),
                audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
                strategy_regime_map={
                    "supertrend": frozenset({RegimeState.TRENDING_UP})
                },
            )

    def test_factory_pulls_strategy_map_from_registry_when_omitted(self):
        # Backwards compat: if caller does not pass strategy_regime_map,
        # the factory reads the live snapshot from StrategyRegistry.
        from src.regime.factory import build_regime_aware_router
        from src.strategies.registry import StrategyRegistry

        StrategyRegistry.clear()
        try:
            from src.strategies.base_strategy import BaseStrategy
            from src.orders.signal import SignalType

            class _T(BaseStrategy):
                def generate_signal(self, bar) -> SignalType:
                    return SignalType.NONE

            StrategyRegistry.register(
                "trender",
                _T,
                regimes=[RegimeState.TRENDING_UP],
            )
            inner = _RecordingInner(
                [_bound_account_with_bar_type(M5_BAR_TYPE, "trender")]
            )
            router = build_regime_aware_router(
                inner=inner,  # type: ignore[arg-type]
                regime_config=_regime_config(enabled=True),
                audit_writer=_RecordingAuditWriter(),  # type: ignore[arg-type]
            )
            assert isinstance(router, RegimeAwareRouter)
            assert router._regime_map["trender"] == frozenset(
                {RegimeState.TRENDING_UP}
            )
        finally:
            StrategyRegistry.clear()
