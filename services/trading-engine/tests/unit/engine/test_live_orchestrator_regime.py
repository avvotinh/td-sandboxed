"""Story 15.11 — per-account RegimeActor + store wiring in LiveOrchestrator.

The live counterpart of the backtest wiring (``run_backtest``, story 15.8):
``_build_session_components`` builds a per-account :class:`RegimeActor` +
shared :class:`RegimeStateStore` from the account's firm ``regime_classifier``
block, threads both into the :class:`AccountNodeSpec` (so
``node_factory.build_account_trading_node`` attaches the actor and injects the
store into the strategy — story 15.10), and stashes them on the session.

Audit goes through the existing :class:`AuditWriter` queue via a sync,
non-blocking hook (review R-D — no extra drainer task); ``None`` when no audit
service is wired, leaving ``audit_to_db`` off (R-E).

Default-OFF (no firm regime block, or ``enabled=false`` — the shipped default)
returns ``(None, None)`` so a session is byte-identical to pre-epic behaviour.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.firm_profile import (
    InstrumentRegimeConfig,
    RegimeConfig,
    RegimeThresholds,
)
from src.config.firm_registry import FirmNotFoundError
from src.engine.account_session import LiveAccountSession
from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator
from src.regime.state_store import RegimeStateStore

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _regime_config(*, enabled: bool = True) -> RegimeConfig:
    instrument = InstrumentRegimeConfig(
        # Calibration-timeframe label (M5/M15 only); independent of the live
        # bar subscription, which drives the actual BarType the actor uses.
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
        bb_baseline_window=200,
        realized_vol_window=20,
        ema_slope_period=20,
        ema_slope_lookback=5,
    )
    return RegimeConfig(
        enabled=enabled,
        confirmation_bars=2,
        warmup_bars=50,
        feature_window=200,
        instruments={"XAUUSD": instrument},
    )


def _firm_registry(regime_config: RegimeConfig | None) -> MagicMock:
    """Registry whose ``get`` returns a profile carrying ``regime_classifier``."""
    profile = SimpleNamespace(regime_classifier=regime_config)
    registry = MagicMock()
    registry.get = MagicMock(return_value=profile)
    return registry


def _account(
    account_id: str = "acct-1",
    *,
    firm_id: str | None = "ftmo",
    symbols: list[str] | None = None,
    strategy: str = "ma_crossover",
) -> MagicMock:
    sig_filter = MagicMock()
    sig_filter.symbols = symbols if symbols is not None else ["XAUUSD"]
    cfg = MagicMock()
    cfg.id = account_id
    cfg.firm_id = firm_id
    cfg.signal_filter = sig_filter
    cfg.strategy = strategy
    cfg.strategy_params = {}
    return cfg


def _orchestrator(
    *,
    firm_registry: Any = None,
    audit_service: Any = None,
) -> LiveOrchestrator:
    return LiveOrchestrator(
        services=LiveServiceBundle(),
        firm_registry=firm_registry,
        audit_service=audit_service,
    )


# 5m matches the M5 calibration in ``_regime_config`` (the timeframe guard
# only builds an actor when live tf == firm calibration tf).
XAUUSD_SUB = [("XAUUSD", "5m")]


# ---------------------------------------------------------------------------
# _build_regime_components — default-OFF branches
# ---------------------------------------------------------------------------


class TestBuildRegimeComponentsOff:
    def test_no_firm_registry_returns_none_pair(self) -> None:
        live = _orchestrator(firm_registry=None)
        assert live._build_regime_components(_account(), XAUUSD_SUB) == (None, None)

    def test_account_without_firm_id_returns_none_pair(self) -> None:
        live = _orchestrator(firm_registry=_firm_registry(_regime_config()))
        assert live._build_regime_components(
            _account(firm_id=None), XAUUSD_SUB
        ) == (None, None)

    def test_empty_bar_subscriptions_returns_none_pair(self) -> None:
        live = _orchestrator(firm_registry=_firm_registry(_regime_config()))
        assert live._build_regime_components(_account(), []) == (None, None)

    def test_firm_not_in_registry_degrades_to_off(self) -> None:
        registry = _firm_registry(_regime_config())
        registry.get = MagicMock(side_effect=FirmNotFoundError("nope"))
        live = _orchestrator(firm_registry=registry)
        # A regime-config resolution failure must never block trading.
        assert live._build_regime_components(_account(), XAUUSD_SUB) == (None, None)

    def test_no_regime_block_returns_none_pair(self) -> None:
        live = _orchestrator(firm_registry=_firm_registry(None))
        assert live._build_regime_components(_account(), XAUUSD_SUB) == (None, None)

    def test_disabled_regime_block_returns_none_pair(self) -> None:
        live = _orchestrator(
            firm_registry=_firm_registry(_regime_config(enabled=False))
        )
        assert live._build_regime_components(_account(), XAUUSD_SUB) == (None, None)


# ---------------------------------------------------------------------------
# _build_regime_components — enabled
# ---------------------------------------------------------------------------


class TestBuildRegimeComponentsOn:
    def test_enabled_builds_actor_and_store(self) -> None:
        live = _orchestrator(firm_registry=_firm_registry(_regime_config()))
        actor, store = live._build_regime_components(_account(), XAUUSD_SUB)

        assert actor is not None
        assert isinstance(store, RegimeStateStore)
        # The actor subscribes/classifies the primary subscription's bar type.
        assert actor.config.bar_type.instrument_id.symbol.value == "XAUUSD"
        # Same store object the strategy will read (passed to build_regime_actor).
        assert actor._regime_state is store

    def test_timeframe_mismatch_degrades_to_off(self) -> None:
        """Live tf (1m) != firm calibration tf (M5) ⇒ regime OFF, no actor."""
        live = _orchestrator(firm_registry=_firm_registry(_regime_config()))
        # _regime_config calibrates for M5; a 1m subscription must not build a
        # miscalibrated actor (HIGH guard).
        assert live._build_regime_components(
            _account(), [("XAUUSD", "1m")]
        ) == (None, None)

    def test_audit_off_when_no_audit_service(self) -> None:
        live = _orchestrator(
            firm_registry=_firm_registry(_regime_config()), audit_service=None
        )
        actor, _ = live._build_regime_components(_account(), XAUUSD_SUB)
        # The orchestrator wires no hook ⇒ build_regime_actor derives
        # audit_to_db=False ⇒ zero rows to audit_logs (R-E).
        assert actor._audit_hook is None
        assert actor.config.audit_to_db is False

    def test_audit_on_when_audit_service_present(self) -> None:
        audit_service = MagicMock()
        audit_service.writer = MagicMock()
        live = _orchestrator(
            firm_registry=_firm_registry(_regime_config()),
            audit_service=audit_service,
        )
        actor, _ = live._build_regime_components(_account(), XAUUSD_SUB)
        assert actor.config.audit_to_db is True


# ---------------------------------------------------------------------------
# _build_regime_audit_hook
# ---------------------------------------------------------------------------


class TestRegimeAuditHook:
    def test_none_when_no_audit_service(self) -> None:
        assert _orchestrator(audit_service=None)._build_regime_audit_hook() is None

    def test_hook_enqueues_nowait_onto_writer(self) -> None:
        writer = MagicMock()
        audit_service = MagicMock()
        audit_service.writer = writer
        hook = _orchestrator(audit_service=audit_service)._build_regime_audit_hook()
        assert hook is not None

        entry = object()
        hook(entry)  # type: ignore[arg-type]
        # R-D — sync, non-blocking enqueue onto the existing writer queue.
        writer.enqueue_nowait.assert_called_once_with(entry)


# ---------------------------------------------------------------------------
# _build_trading_node_if_ready — regime pair flows into the spec
# ---------------------------------------------------------------------------


class TestRegimePairThreadedIntoSpec:
    def _ready_orchestrator(self, captured: list[Any]):
        def _factory(*, account, spec):
            captured.append(spec)
            return MagicMock()

        return LiveOrchestrator(
            services=LiveServiceBundle(),
            redis_manager=MagicMock(client=MagicMock()),
            validated_adapter=MagicMock(),
            node_factory=_factory,
        )

    def test_regime_pair_passed_to_node_factory(self) -> None:
        captured: list[Any] = []
        live = self._ready_orchestrator(captured)
        actor, store = MagicMock(name="RegimeActor"), RegimeStateStore()

        live._build_trading_node_if_ready(
            account=_account(),
            bar_subscriptions=XAUUSD_SUB,
            compliance_actor=None,
            regime_actor=actor,
            regime_state=store,
        )

        assert captured[0].regime_actor is actor
        assert captured[0].regime_state is store

    def test_default_off_leaves_spec_regime_none(self) -> None:
        captured: list[Any] = []
        live = self._ready_orchestrator(captured)

        live._build_trading_node_if_ready(
            account=_account(),
            bar_subscriptions=XAUUSD_SUB,
            compliance_actor=None,
        )

        assert captured[0].regime_actor is None
        assert captured[0].regime_state is None


# ---------------------------------------------------------------------------
# End-to-end through _build_session_components
# ---------------------------------------------------------------------------


class TestSessionComponentsWiring:
    """``_build_session_components`` builds the regime pair, threads it into the
    spec, and stashes it on the session.
    """

    def _full_orchestrator(self, *, account, regime_config, captured):
        from src.rules.engine import RuleEngine  # noqa: F401 — ensure importable

        account_manager = MagicMock()
        account_manager.get_account = MagicMock(return_value=account)
        rule_assignment = MagicMock()
        rule_assignment.get_rules_for_account = MagicMock(return_value=[])
        risk_state = MagicMock()
        risk_state.daily_starting_balance = Decimal("100000")
        risk_registry = MagicMock()
        risk_registry.get_risk_state = MagicMock(return_value=risk_state)

        def _factory(*, account, spec):
            captured.append(spec)
            node = MagicMock()
            node.run_async = AsyncMock()
            node.stop_async = AsyncMock()
            return node

        return LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=account_manager,
            rule_assignment_service=rule_assignment,
            firm_registry=_firm_registry(regime_config),
            risk_registry=risk_registry,
            redis_manager=MagicMock(client=MagicMock()),
            validated_adapter=MagicMock(),
            node_factory=_factory,
            # Subscribe at 5m so the computed subscription matches the M5
            # calibration timeframe and the regime guard builds the actor.
            bar_timeframes=("5m",),
        )

    @pytest.mark.asyncio
    async def test_enabled_regime_threaded_through_and_stashed(self) -> None:
        account = _account("acct-1", firm_id="ftmo")
        captured: list[Any] = []
        live = self._full_orchestrator(
            account=account, regime_config=_regime_config(), captured=captured
        )
        session = LiveAccountSession(account_id="acct-1")

        await live._build_session_components(session)

        # Built + stashed on the session.
        actor = session.components["regime_actor"]
        store = session.components["regime_state"]
        assert actor is not None
        assert isinstance(store, RegimeStateStore)
        # Threaded into the spec the node factory received.
        assert captured[0].regime_actor is actor
        assert captured[0].regime_state is store

    @pytest.mark.asyncio
    async def test_default_off_session_has_none_regime(self) -> None:
        account = _account("acct-1", firm_id="ftmo")
        captured: list[Any] = []
        live = self._full_orchestrator(
            account=account,
            regime_config=_regime_config(enabled=False),
            captured=captured,
        )
        session = LiveAccountSession(account_id="acct-1")

        await live._build_session_components(session)

        assert session.components["regime_actor"] is None
        assert session.components["regime_state"] is None
        assert captured[0].regime_actor is None
