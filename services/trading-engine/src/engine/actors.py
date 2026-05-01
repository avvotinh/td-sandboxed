"""Shared compliance-actor factory used by both backtest and live paths.

Story 10.5a — extract :func:`build_compliance_actor` so the backtest
runner and the live orchestrator construct the actor with the same
defaults. Spec ref: ``docs/sprint-artifacts/10-5-live-orchestrator.md``
AC2 — "shared between LiveOrchestrator and BacktestRunner". Live
trading paths plug in here in 10.5d once :class:`LiveOrchestrator`
mounts a Nautilus ``LiveNode`` per account; today the function exists
so both call-sites converge on the same construction signature.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.currencies import USD

from ..backtesting.prop_firm_actor import (
    PropFirmComplianceActor,
    PropFirmComplianceActorConfig,
)

if TYPE_CHECKING:
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Currency

    from ..rules.engine import RuleEngine


def build_compliance_actor(
    *,
    account_id: str,
    initial_balance: Decimal,
    rule_engine: RuleEngine,
    daily_session_tz: str = "UTC",
    bar_type: BarType | None = None,
    venue: Venue | None = None,
    currency: Currency = USD,
) -> PropFirmComplianceActor:
    """Construct a :class:`PropFirmComplianceActor` with shared defaults.

    Both :class:`~src.backtesting.engine.BacktestRunner` and
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
            from the Nautilus portfolio.
        currency: Account base currency.
    """
    config = PropFirmComplianceActorConfig(
        account_id=account_id,
        initial_balance=initial_balance,
        daily_session_tz=daily_session_tz,
        bar_type=bar_type,
        venue=venue,
        currency=currency,
    )
    return PropFirmComplianceActor(config=config, rule_engine=rule_engine)
