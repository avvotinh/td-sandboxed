"""Story 10.5d — live ``PropFirmComplianceActor`` wiring tests.

Covers the seam that lets the live orchestrator drive the actor's
``on_bar`` rule check from the engine's per-account ``PnLTrackerRegistry``
instead of the Nautilus ``Portfolio``:

- ``PropFirmComplianceActor`` consults ``equity_provider`` when set.
- ``build_compliance_actor`` forwards the provider to the actor.
- ``LiveOrchestrator._build_equity_provider`` wraps the registry into
  a per-account closure that's bound to one ``account_id`` (so cross-
  account misuse fails loudly).
- ``_build_session_components`` injects the provider so each session
  ends up with its own isolated closure.
- Backtest parity: leaving the provider ``None`` keeps the Nautilus-
  portfolio fallback intact.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backtesting.prop_firm_actor import (
    PropFirmComplianceActor,
    PropFirmComplianceActorConfig,
)
from src.engine.actors import build_compliance_actor
from src.engine.collaborators import LiveServiceBundle
from src.engine.live_orchestrator import LiveOrchestrator
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine_result import RuleEngineResult


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures (kept local — the public test surface should be visible inline)
# ---------------------------------------------------------------------------


def _allow_engine() -> MagicMock:
    """A rule engine whose ``validate`` always returns ALLOW."""
    rule_engine = MagicMock()
    rule_engine.validate = MagicMock(
        return_value=RuleEngineResult(
            action=RuleAction.ALLOW,
            blocked_by=None,
            blocking_reason=None,
            warnings=[],
            all_results=[],
            evaluation_time_ms=0.1,
        )
    )
    return rule_engine


def _block_engine(rule_name: str = "daily_loss_limit") -> MagicMock:
    """A rule engine whose ``validate`` always BLOCKs (one rule)."""
    mock_rule = MagicMock()
    mock_rule.name = rule_name
    rule_engine = MagicMock()
    rule_engine.validate = MagicMock(
        return_value=RuleEngineResult(
            action=RuleAction.BLOCK,
            blocked_by=mock_rule,
            blocking_reason="breach",
            warnings=[],
            all_results=[
                (
                    mock_rule,
                    RuleResult(
                        action=RuleAction.BLOCK,
                        message="breach",
                        current_value=5.5,
                        threshold_value=5.0,
                    ),
                )
            ],
            evaluation_time_ms=0.1,
        )
    )
    return rule_engine


def _account(
    account_id: str = "acct-1",
    symbols: list[str] | None = None,
) -> MagicMock:
    sig_filter = MagicMock()
    sig_filter.symbols = symbols if symbols is not None else ["XAUUSD"]
    cfg = MagicMock()
    cfg.id = account_id
    cfg.signal_filter = sig_filter
    return cfg


def _account_manager(active: list[MagicMock]) -> MagicMock:
    am = MagicMock()
    am.get_active_account_ids = MagicMock(return_value=[a.id for a in active])
    am.get_account = MagicMock(side_effect=lambda aid: next(
        (a for a in active if a.id == aid), None
    ))
    am.pause_account = AsyncMock()
    return am


def _rule_assignment_service() -> MagicMock:
    svc = MagicMock()
    svc.get_rules_for_account = MagicMock(return_value=[])
    return svc


def _risk_registry(starting_balance: Decimal = Decimal("100000")) -> MagicMock:
    state = MagicMock()
    state.daily_starting_balance = starting_balance
    registry = MagicMock()
    registry.get_risk_state = MagicMock(return_value=state)
    return registry


def _pnl_registry(equity_by_account: dict[str, Decimal]) -> MagicMock:
    """Build a ``PnLTrackerRegistry`` mock whose ``get`` returns a
    tracker with ``.equity`` for each known account, ``None`` otherwise."""
    registry = MagicMock()

    def _get(account_id: str):
        equity = equity_by_account.get(account_id)
        if equity is None:
            return None
        tracker = MagicMock()
        tracker.equity = equity
        return tracker

    registry.get = MagicMock(side_effect=_get)
    return registry


# ---------------------------------------------------------------------------
# Actor — ``equity_provider`` resolution
# ---------------------------------------------------------------------------


class TestActorEquityProvider:
    """``_read_equity`` order: provider → portfolio → fallback."""

    def test_uses_provider_when_set(self) -> None:
        config = PropFirmComplianceActorConfig(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
        )
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=_allow_engine(),
            equity_provider=lambda aid: Decimal("99750"),
        )
        assert actor._read_equity() == Decimal("99750")

    def test_provider_takes_precedence_over_venue(self) -> None:
        """When both wired, the live provider wins — backtest semantics
        only kick in when the provider is ``None``."""
        from nautilus_trader.model.identifiers import Venue

        config = PropFirmComplianceActorConfig(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
            venue=Venue("MT5"),
        )
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=_allow_engine(),
            equity_provider=lambda aid: Decimal("123"),
        )
        # Even though venue is set, ``portfolio`` is never consulted —
        # touching it would raise on this Cython base outside an engine.
        assert actor._read_equity() == Decimal("123")

    def test_provider_returning_none_propagates(self) -> None:
        """Warm-up — no tracker yet — returns ``None`` to skip the tick."""
        config = PropFirmComplianceActorConfig(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
        )
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=_allow_engine(),
            equity_provider=lambda aid: None,
        )
        assert actor._read_equity() is None

    def test_provider_called_with_actor_account_id(self) -> None:
        seen: list[str] = []
        config = PropFirmComplianceActorConfig(
            account_id="ftmo-002",
            initial_balance=Decimal("100000"),
        )

        def _provider(aid: str) -> Decimal | None:
            seen.append(aid)
            return Decimal("100000")

        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=_allow_engine(),
            equity_provider=_provider,
        )
        actor._read_equity()
        assert seen == ["ftmo-002"]

    def test_no_provider_no_venue_returns_none(self) -> None:
        """Backtest unit-test path — preserved verbatim from before 10.5d."""
        config = PropFirmComplianceActorConfig(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
        )
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=_allow_engine(),
        )
        assert actor._read_equity() is None


# ---------------------------------------------------------------------------
# Factory — ``equity_provider`` passthrough
# ---------------------------------------------------------------------------


class TestFactoryPassthrough:
    def test_factory_default_no_provider(self) -> None:
        actor = build_compliance_actor(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
            rule_engine=_allow_engine(),
        )
        assert actor._equity_provider is None

    def test_factory_forwards_provider_identity(self) -> None:
        provider = lambda aid: Decimal("0")  # noqa: E731 — identity check
        actor = build_compliance_actor(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
            rule_engine=_allow_engine(),
            equity_provider=provider,
        )
        assert actor._equity_provider is provider


# ---------------------------------------------------------------------------
# End-to-end — provider drives ``record_compliance_check``
# ---------------------------------------------------------------------------


class TestRuleCheckUsesProviderEquity:
    """``on_bar`` reads equity through provider → builds context → BLOCKs."""

    def test_block_breach_recorded_using_provider_equity(self) -> None:
        provider_equity = Decimal("94800")  # -5.2% from 100k starting
        config = PropFirmComplianceActorConfig(
            account_id="acct-1",
            initial_balance=Decimal("100000"),
        )
        engine = _block_engine("daily_loss_limit")
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=engine,
            equity_provider=lambda aid: provider_equity,
        )

        # ``record_compliance_check`` is the public seam used by ``on_bar``.
        # We feed it a fully formed account_state so the rule engine sees
        # the exact equity the provider would surface.
        state = {
            "balance": provider_equity,
            "equity": provider_equity,
            "open_positions": 0,
            "total_exposure": Decimal("0"),
        }
        actor.record_compliance_check(state, ts=datetime(2026, 1, 1, tzinfo=UTC))

        assert len(actor.breaches) == 1
        engine.validate.assert_called_once()
        ctx = engine.validate.call_args[0][0]
        assert ctx["equity"] == provider_equity
        assert ctx["balance"] == provider_equity

    def test_on_bar_threads_provider_equity_into_rule_context(self) -> None:
        """End-to-end: ``on_bar`` → ``_read_equity`` → ``account_state["equity"]``.

        The previous test patches ``record_compliance_check`` directly,
        which bypasses ``_read_equity``. This one drives the actor's
        ``on_bar`` with a real ``Bar`` and asserts the equity surfaced
        in the rule context comes from the provider — closing the gap
        flagged by review.
        """
        from nautilus_trader.model.data import Bar, BarSpecification, BarType
        from nautilus_trader.model.enums import (
            AggregationSource,
            BarAggregation,
            PriceType,
        )
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
        from nautilus_trader.model.objects import Price, Quantity

        provider_calls: list[str] = []

        def _provider(aid: str) -> Decimal | None:
            provider_calls.append(aid)
            return Decimal("100123.45")

        config = PropFirmComplianceActorConfig(
            account_id="ftmo-007",
            initial_balance=Decimal("100000"),
        )
        engine = _allow_engine()
        actor = PropFirmComplianceActor(
            config=config,
            rule_engine=engine,
            equity_provider=_provider,
        )

        bar_type = BarType(
            instrument_id=InstrumentId(Symbol("EURUSD"), Venue("MT5")),
            bar_spec=BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
            aggregation_source=AggregationSource.EXTERNAL,
        )
        ts_ns = int(
            datetime(2026, 1, 1, 9, 0, tzinfo=UTC).timestamp() * 1_000_000_000
        )
        bar = Bar(
            bar_type=bar_type,
            open=Price.from_str("1.10000"),
            high=Price.from_str("1.10010"),
            low=Price.from_str("1.09990"),
            close=Price.from_str("1.10005"),
            volume=Quantity.from_str("1000"),
            ts_event=ts_ns,
            ts_init=ts_ns,
        )

        actor.on_bar(bar)

        assert provider_calls == ["ftmo-007"]
        engine.validate.assert_called_once()
        ctx = engine.validate.call_args[0][0]
        assert ctx["equity"] == Decimal("100123.45")
        assert ctx["balance"] == Decimal("100123.45")


# ---------------------------------------------------------------------------
# LiveOrchestrator — ``_build_equity_provider``
# ---------------------------------------------------------------------------


class TestBuildEquityProvider:
    def test_returns_none_without_pnl_registry(self) -> None:
        live = LiveOrchestrator(services=LiveServiceBundle())
        assert live._build_equity_provider("acct-1") is None

    def test_provider_reads_tracker_equity(self) -> None:
        registry = _pnl_registry({"acct-1": Decimal("99500")})
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            pnl_registry=registry,
        )
        provider = live._build_equity_provider("acct-1")
        assert provider is not None
        assert provider("acct-1") == Decimal("99500")

    def test_provider_returns_none_when_tracker_missing(self) -> None:
        """Warm-up path — the tracker is created lazily on first fill."""
        registry = _pnl_registry({})
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            pnl_registry=registry,
        )
        provider = live._build_equity_provider("acct-1")
        assert provider is not None
        assert provider("acct-1") is None

    def test_provider_late_binds_tracker(self) -> None:
        """``reload_account`` may swap the tracker — provider must
        re-resolve every call rather than capture at construction."""
        equities: dict[str, Decimal] = {"acct-1": Decimal("100000")}
        registry = _pnl_registry(equities)
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            pnl_registry=registry,
        )
        provider = live._build_equity_provider("acct-1")
        assert provider is not None
        assert provider("acct-1") == Decimal("100000")

        # Mutate the underlying state — the next call must see it.
        equities["acct-1"] = Decimal("105500")
        assert provider("acct-1") == Decimal("105500")

    def test_provider_rejects_wrong_account_id(self) -> None:
        """Cross-account misuse must fail loudly so a buggy caller can't
        silently feed account A's equity into account B's rule check."""
        registry = _pnl_registry({"acct-1": Decimal("100000")})
        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            pnl_registry=registry,
        )
        provider = live._build_equity_provider("acct-1")
        assert provider is not None
        with pytest.raises(ValueError, match="bound to 'acct-1'"):
            provider("acct-2")


# ---------------------------------------------------------------------------
# LiveOrchestrator — session wiring
# ---------------------------------------------------------------------------


class TestSessionEquityProviderWiring:
    """``_build_session_components`` attaches a per-account provider."""

    @pytest.mark.asyncio
    async def test_session_attaches_equity_provider_when_pnl_wired(
        self,
    ) -> None:
        account = _account("acct-1")
        am = _account_manager([account])
        ras = _rule_assignment_service()
        risk = _risk_registry()
        pnl = _pnl_registry({"acct-1": Decimal("100250")})

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
            pnl_registry=pnl,
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.is_running

        provider = session.components["equity_provider"]
        assert callable(provider)
        assert provider("acct-1") == Decimal("100250")

        # Same provider is reachable from the actor itself.
        actor = session.components["compliance_actor"]
        assert actor._equity_provider is provider

        await live.stop()

    @pytest.mark.asyncio
    async def test_session_omits_equity_provider_when_pnl_absent(self) -> None:
        """Backward compat — 10.5e1-shaped wiring (no pnl_registry)
        leaves the actor on the backtest path."""
        account = _account("acct-1")
        am = _account_manager([account])
        ras = _rule_assignment_service()
        risk = _risk_registry()

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
            # pnl_registry intentionally absent
        )
        await live.start()

        session = live.sessions["acct-1"]
        assert session.components["equity_provider"] is None
        actor = session.components["compliance_actor"]
        assert actor._equity_provider is None

        await live.stop()

    @pytest.mark.asyncio
    async def test_per_account_provider_isolation(self) -> None:
        """Two accounts → two distinct closures; each refuses the other's id."""
        a1 = _account("acct-1")
        a2 = _account("acct-2")
        am = _account_manager([a1, a2])
        ras = _rule_assignment_service()
        risk = _risk_registry()
        pnl = _pnl_registry(
            {"acct-1": Decimal("100000"), "acct-2": Decimal("250000")}
        )

        live = LiveOrchestrator(
            services=LiveServiceBundle(),
            account_manager=am,
            rule_assignment_service=ras,
            risk_registry=risk,
            pnl_registry=pnl,
        )
        await live.start()

        provider_a = live.sessions["acct-1"].components["equity_provider"]
        provider_b = live.sessions["acct-2"].components["equity_provider"]

        assert provider_a is not provider_b
        assert provider_a("acct-1") == Decimal("100000")
        assert provider_b("acct-2") == Decimal("250000")

        # Per-account guard rails
        with pytest.raises(ValueError):
            provider_a("acct-2")
        with pytest.raises(ValueError):
            provider_b("acct-1")

        await live.stop()
