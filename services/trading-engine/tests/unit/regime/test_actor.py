"""Unit tests for ``RegimeActor`` (Epic 15 story 15.5).

The actor's pure orchestration is tested without a ``BacktestEngine``: the four
pipeline components are injected as lightweight fakes so each test controls the
classifier/hysteresis output exactly, and ``on_bar`` is driven directly. The
real pipeline (real ``FeatureExtractor`` + indicators) is exercised end-to-end
by the ablation test in story 15.9.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from src.regime.actor import RegimeActor, RegimeActorConfig
from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.state_store import RegimeStateStore
from src.regime.states import RegimeState
from src.rules.audit_logger import AuditEntry

pytestmark = pytest.mark.unit

BAR_TYPE = "XAUUSD.SIM-5-MINUTE-LAST-EXTERNAL"
# 2024-01-02 00:00:00 UTC in integer nanoseconds.
TS_NS = int(datetime(2024, 1, 2, tzinfo=UTC).timestamp()) * 1_000_000_000


def _features() -> RegimeFeatures:
    return RegimeFeatures(
        adx=30.0,
        plus_di=25.0,
        minus_di=10.0,
        bb_width_pct=0.5,
        realized_vol=0.01,
        ema_slope=0.002,
        is_warmed_up=True,
    )


def _decision(
    *,
    state: RegimeState = RegimeState.TRENDING_UP,
    ts: datetime | None = None,
    features: RegimeFeatures | None = None,
) -> RegimeDecision:
    feats = features if features is not None else _features()
    return RegimeDecision(
        timestamp=ts if ts is not None else datetime(2024, 1, 2, tzinfo=UTC),
        bar_type=BAR_TYPE,
        current_state=state,
        raw_state=state,
        pending_state=None,
        bars_in_pending=0,
        features=feats,
        confidence=0.8,
    )


class _FakeExtractor:
    """Returns each queued value in turn; ``None`` models warmup."""

    def __init__(self, returns: list[RegimeFeatures | None]) -> None:
        self._returns = list(returns)
        self.bars_seen: list[Any] = []

    def update(self, bar: Any) -> RegimeFeatures | None:
        self.bars_seen.append(bar)
        return self._returns.pop(0)


class _FakeClassifier:
    def __init__(self, state: RegimeState = RegimeState.TRENDING_UP) -> None:
        self._state = state
        self.calls: list[RegimeFeatures] = []

    def decide(self, features: RegimeFeatures) -> RegimeState:
        self.calls.append(features)
        return self._state


class _FakeHysteresis:
    """Records the ``(raw, ts, features)`` it was applied with; returns a decision."""

    def __init__(self, decision: RegimeDecision) -> None:
        self._decision = decision
        self.calls: list[tuple[RegimeState, datetime, RegimeFeatures]] = []

    def apply(
        self, raw: RegimeState, ts: datetime, features: RegimeFeatures
    ) -> RegimeDecision:
        self.calls.append((raw, ts, features))
        return self._decision


def _bar(ts_ns: int = TS_NS) -> SimpleNamespace:
    """Minimal stand-in for a Nautilus ``Bar`` — the actor only reads ts_event."""
    return SimpleNamespace(ts_event=ts_ns)


def _make_actor(
    *,
    extractor: _FakeExtractor,
    classifier: _FakeClassifier,
    hysteresis: _FakeHysteresis,
    store: RegimeStateStore,
    audit_to_db: bool = False,
    audit_hook: Any = None,
) -> RegimeActor:
    config = RegimeActorConfig(primary_symbol="XAUUSD", audit_to_db=audit_to_db)
    return RegimeActor(
        config=config,
        classifier=classifier,  # type: ignore[arg-type]
        feature_extractor=extractor,  # type: ignore[arg-type]
        hysteresis=hysteresis,  # type: ignore[arg-type]
        regime_state=store,
        audit_hook=audit_hook,
    )


class TestActorSubclass:
    def test_is_nautilus_actor(self) -> None:
        actor = _make_actor(
            extractor=_FakeExtractor([None]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=RegimeStateStore(),
        )
        assert isinstance(actor, Actor)

    def test_config_is_actor_config(self) -> None:
        assert issubclass(RegimeActorConfig, ActorConfig)

    def test_config_defaults(self) -> None:
        cfg = RegimeActorConfig(primary_symbol="XAUUSD")
        assert cfg.audit_to_db is False
        assert cfg.bar_type is None


class TestLifecycle:
    def test_on_start_warns_when_audit_enabled_but_no_hook(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # bar_type defaults to None, so on_start does not subscribe (safe to call
        # without an engine) but still runs the misconfiguration check.
        actor = _make_actor(
            extractor=_FakeExtractor([]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=RegimeStateStore(),
            audit_to_db=True,
            audit_hook=None,
        )

        with caplog.at_level("WARNING"):
            actor.on_start()

        assert any(
            "audit_to_db=True but no audit hook" in r.message for r in caplog.records
        )

    def test_on_start_no_warning_when_hook_present(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        actor = _make_actor(
            extractor=_FakeExtractor([]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=RegimeStateStore(),
            audit_to_db=True,
            audit_hook=lambda _e: None,
        )

        with caplog.at_level("WARNING"):
            actor.on_start()

        assert not any("audit hook" in r.message for r in caplog.records)

    def test_on_stop_no_bar_type_is_noop(self) -> None:
        # bar_type=None → on_stop must not call unsubscribe (and not raise).
        actor = _make_actor(
            extractor=_FakeExtractor([]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=RegimeStateStore(),
        )
        actor.on_stop()  # no exception


class TestWarmup:
    def test_none_features_does_not_publish_or_audit(self) -> None:
        store = RegimeStateStore()
        hook_calls: list[AuditEntry] = []
        classifier = _FakeClassifier()
        hysteresis = _FakeHysteresis(_decision())
        extractor = _FakeExtractor([None])
        actor = _make_actor(
            extractor=extractor,
            classifier=classifier,
            hysteresis=hysteresis,
            store=store,
            audit_to_db=True,
            audit_hook=hook_calls.append,
        )

        bar = _bar()
        actor.on_bar(bar)

        assert extractor.bars_seen == [bar]  # bar was fed to the extractor
        assert store.current(BAR_TYPE) is None  # nothing published
        assert classifier.calls == []  # classifier never reached
        assert hysteresis.calls == []
        assert hook_calls == []  # no audit during warmup


class TestPublish:
    def test_confirmed_decision_published_to_store(self) -> None:
        store = RegimeStateStore()
        decision = _decision(state=RegimeState.TRENDING_UP)
        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(RegimeState.TRENDING_UP),
            hysteresis=_FakeHysteresis(decision),
            store=store,
        )

        actor.on_bar(_bar())

        snap = store.current(BAR_TYPE)
        assert snap is not None
        assert snap.current_state == RegimeState.TRENDING_UP
        assert snap.confidence == 0.8
        assert snap.features == decision.features

    def test_high_volatility_is_published_actor_does_not_gate(self) -> None:
        # The actor publishes every confirmed state; suppression is the
        # strategy's job (15.7). HIGH_VOLATILITY must reach the store so the
        # strategy can act on the kill-switch.
        store = RegimeStateStore()
        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(RegimeState.HIGH_VOLATILITY),
            hysteresis=_FakeHysteresis(_decision(state=RegimeState.HIGH_VOLATILITY)),
            store=store,
        )

        actor.on_bar(_bar())

        snap = store.current(BAR_TYPE)
        assert snap is not None
        assert snap.current_state == RegimeState.HIGH_VOLATILITY

    def test_ts_event_converted_to_tz_aware_utc(self) -> None:
        store = RegimeStateStore()
        hysteresis = _FakeHysteresis(_decision())
        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(),
            hysteresis=hysteresis,
            store=store,
        )

        actor.on_bar(_bar(TS_NS))

        assert len(hysteresis.calls) == 1
        _, ts, _ = hysteresis.calls[0]
        assert ts == datetime(2024, 1, 2, tzinfo=UTC)
        assert ts.tzinfo is not None


class TestAudit:
    def test_audit_hook_called_with_entry_when_enabled(self) -> None:
        store = RegimeStateStore()
        hook_calls: list[AuditEntry] = []
        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=store,
            audit_to_db=True,
            audit_hook=hook_calls.append,
        )

        actor.on_bar(_bar())

        assert len(hook_calls) == 1
        entry = hook_calls[0]
        assert isinstance(entry, AuditEntry)
        assert entry.event_type == "regime_decision"
        assert entry.account_id is None
        assert entry.rule_result == RegimeState.TRENDING_UP.value

    def test_audit_skipped_when_audit_to_db_false(self) -> None:
        # Defense in depth for R-E: even if a hook is wired, audit_to_db=False
        # (the backtest default) writes zero rows.
        store = RegimeStateStore()
        hook_calls: list[AuditEntry] = []
        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=store,
            audit_to_db=False,
            audit_hook=hook_calls.append,
        )

        actor.on_bar(_bar())

        assert hook_calls == []
        assert store.current(BAR_TYPE) is not None  # still published

    def test_audit_happens_before_publish(self) -> None:
        # The hook observes the store as still-empty for this bar_type, proving
        # the audit call precedes publish.
        store = RegimeStateStore()
        observed_during_hook: list[Any] = []

        def hook(_entry: AuditEntry) -> None:
            observed_during_hook.append(store.current(BAR_TYPE))

        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=store,
            audit_to_db=True,
            audit_hook=hook,
        )

        actor.on_bar(_bar())

        assert observed_during_hook == [None]  # store empty when audit ran
        assert store.current(BAR_TYPE) is not None  # published afterwards

    def test_audit_hook_failure_is_swallowed_and_publish_still_happens(self) -> None:
        store = RegimeStateStore()

        def boom(_entry: AuditEntry) -> None:
            raise RuntimeError("queue exploded")

        actor = _make_actor(
            extractor=_FakeExtractor([_features()]),
            classifier=_FakeClassifier(),
            hysteresis=_FakeHysteresis(_decision()),
            store=store,
            audit_to_db=True,
            audit_hook=boom,
        )

        # Must not raise — telemetry failure cannot break regime publishing.
        actor.on_bar(_bar())

        assert store.current(BAR_TYPE) is not None
