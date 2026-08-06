"""Shared compliance-actor factory used by both backtest and live paths.

Story 10.5a — extract :func:`build_compliance_actor` so the backtest
runner and the live orchestrator construct the actor with the same
defaults. Spec ref: ``docs/sprint-artifacts/10-5-live-orchestrator.md``
AC2 — "shared between LiveOrchestrator and BacktestRunner". Story 10.5d
adds the ``equity_provider`` plumbing — a callable the live orchestrator
wires from :class:`PnLTrackerRegistry` so the actor's ``on_bar`` rule
check sees the engine's authoritative per-account equity instead of the
Nautilus ``Portfolio`` (which is populated by the bridge later in the
pipeline). Backtest callers leave the provider ``None`` and the actor
falls back to ``Portfolio.balance_total`` — preserving AC10 parity.

Story 15.6 adds :func:`build_regime_actor`, the regime counterpart, for the
same backtest/live parity reason — one shared constructor so the regime
pipeline cannot drift between simulation and production.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.currencies import USD

from src.lab.prop_firm_actor import (
    LiveEquityProvider,
    PropFirmComplianceActor,
    PropFirmComplianceActorConfig,
)
from src.config.firm_profile import RegimeConfig
from src.kernel.regime.actor import RegimeActor, RegimeActorConfig, RegimeAuditHook
from src.kernel.regime.builders import build_extractor
from src.kernel.regime.classifier import RuleBasedRegimeClassifier
from src.kernel.regime.hysteresis import HysteresisFilter
from src.kernel.regime.state_store import RegimeStateStore

if TYPE_CHECKING:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Currency

    from src.rules.engine import RuleEngine


def build_compliance_actor(
    *,
    account_id: str,
    initial_balance: Decimal,
    rule_engine: RuleEngine,
    daily_session_tz: str = "UTC",
    bar_type: BarType | None = None,
    venue: Venue | None = None,
    currency: Currency = USD,
    equity_provider: LiveEquityProvider | None = None,
) -> PropFirmComplianceActor:
    """Construct a :class:`PropFirmComplianceActor` with shared defaults.

    Both :class:`~src.lab.engine.BacktestRunner` and
    :class:`~src.engine.live_orchestrator.LiveOrchestrator` call this
    function so the actor's behaviour cannot drift between simulation
    and production.

    Args:
        account_id: Account scope for rule context.
        initial_balance: Starting balance — anchors drawdown / peak
            calculations and prop-firm percentage metrics.
        rule_engine: Resolved rule engine for this account (for live,
            built per ``firm_id + product_id + phase + rule_overrides``
            via :class:`~src.rules.assignment_service.RuleAssignmentService`).
        daily_session_tz: IANA timezone whose midnight marks a new
            trading day for daily-loss deduplication.
        bar_type: Optional ``BarType`` for the actor to subscribe to on
            start. Tests / unit paths leave this ``None``.
        venue: Optional venue handle so the actor can read live equity
            from the Nautilus portfolio. Live callers usually pass
            ``equity_provider`` instead and leave ``venue`` ``None``.
        currency: Account base currency.
        equity_provider: Live mode — callable returning the engine's
            authoritative per-account equity. When provided, the actor
            sources ``on_bar`` equity from this closure (typically wired
            from :class:`~src.accounts.pnl_registry.PnLTrackerRegistry`).
            ``None`` (default) preserves the backtest portfolio path.
    """
    config = PropFirmComplianceActorConfig(
        account_id=account_id,
        initial_balance=initial_balance,
        daily_session_tz=daily_session_tz,
        bar_type=bar_type,
        venue=venue,
        currency=currency,
    )
    return PropFirmComplianceActor(
        config=config,
        rule_engine=rule_engine,
        equity_provider=equity_provider,
    )


def build_regime_actor(
    *,
    regime_config: RegimeConfig,
    bar_type: BarType,
    regime_state: RegimeStateStore,
    audit_hook: RegimeAuditHook | None = None,
) -> RegimeActor | None:
    """Construct a :class:`RegimeActor` for one ``bar_type``, or ``None`` if off.

    The regime counterpart of :func:`build_compliance_actor`: both the backtest
    runner (:meth:`~src.lab.engine.BacktestRunner.attach_regime`, story
    15.8) and the live path (``node_factory`` / ``LiveOrchestrator``, stories
    15.10/15.11) call this so the classify → hysteresis → audit pipeline cannot
    drift between simulation and production.

    Single source of truth: the factory builds exactly one
    :class:`FeatureExtractor` (via :func:`~src.kernel.regime.builders.build_extractor`),
    one :class:`RuleBasedRegimeClassifier`, and one :class:`HysteresisFilter` for
    this ``bar_type``, so the regime indicators are computed exactly once. The
    instrument is looked up by the symbol leg of ``bar_type`` (one actor per
    ``bar_type``; multi-symbol live is N actors — design §4), and the
    ``HysteresisFilter`` / extractor are keyed by ``str(bar_type)`` to match the
    key strategies read from the store.

    Args:
        regime_config: Firm-level regime block. ``enabled=False`` (the shipped
            default) short-circuits to ``None`` — zero extractor, zero overhead.
        bar_type: The ``BarType`` the actor subscribes to and classifies. Its
            symbol leg selects the :class:`InstrumentRegimeConfig`.
        regime_state: The shared :class:`RegimeStateStore` the caller also
            injects into the strategy (story 15.7/15.8) so both sides reference
            the *same* object — passed in rather than created here to preserve
            that identity.
        audit_hook: Optional sync, non-blocking audit sink. ``None`` (backtest,
            the default) keeps ``audit_to_db`` off so zero rows reach the live
            ``audit_logs`` hypertable (review R-E). A hook (live, story 15.11,
            a closure over the existing ``AuditWriter`` queue) flips
            ``audit_to_db`` on, so the factory can never produce the
            ``(audit_to_db=True, hook=None)`` silent-drop misconfiguration.

    Returns:
        A wired :class:`RegimeActor`, or ``None`` when the classifier is
        disabled.

    Raises:
        KeyError: if ``bar_type``'s symbol has no
            :class:`InstrumentRegimeConfig` in ``regime_config`` — fail loudly
            rather than classify against another instrument's calibration.
            Only reachable when ``regime_config.enabled`` is ``True``.
    """
    if not regime_config.enabled:
        return None

    # Resolve the symbol via the Nautilus type system, NOT a str(bar_type)
    # split on "." (the legacy regime/factory.py:_symbol_from_bar_type does the
    # latter and would mis-parse a dotted symbol like "NQ.CME"). Do not
    # "harmonize" this toward that helper. The extractor/hysteresis below are
    # still keyed by str(bar_type) — the same key strategies read from the store.
    symbol = bar_type.instrument_id.symbol.value
    instrument_cfg = regime_config.get_instrument(symbol)
    bar_type_str = str(bar_type)

    config = RegimeActorConfig(
        primary_symbol=symbol,
        bar_type=bar_type,
        audit_to_db=audit_hook is not None,
    )
    return RegimeActor(
        config=config,
        classifier=RuleBasedRegimeClassifier(instrument_cfg.thresholds),
        feature_extractor=build_extractor(
            bar_type_str, instrument_cfg, regime_config.warmup_bars
        ),
        hysteresis=HysteresisFilter(
            bar_type=bar_type_str,
            confirmation_bars=regime_config.confirmation_bars,
            thresholds=instrument_cfg.thresholds,
        ),
        regime_state=regime_state,
        audit_hook=audit_hook,
    )
