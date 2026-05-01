"""Story 10.5a — shared compliance-actor factory tests."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from src.backtesting.prop_firm_actor import PropFirmComplianceActor
from src.engine.actors import build_compliance_actor


def test_returns_prop_firm_compliance_actor() -> None:
    rule_engine = MagicMock()
    actor = build_compliance_actor(
        account_id="acct-1",
        initial_balance=Decimal("100000"),
        rule_engine=rule_engine,
    )
    assert isinstance(actor, PropFirmComplianceActor)


def test_passes_account_id_into_actor_config() -> None:
    actor = build_compliance_actor(
        account_id="ftmo-gold-001",
        initial_balance=Decimal("100000"),
        rule_engine=MagicMock(),
    )
    assert actor._config.account_id == "ftmo-gold-001"


def test_initial_balance_anchors_actor_peak() -> None:
    actor = build_compliance_actor(
        account_id="acct-1",
        initial_balance=Decimal("250000"),
        rule_engine=MagicMock(),
    )
    assert actor._peak_balance == Decimal("250000")


def test_default_session_tz_is_utc() -> None:
    actor = build_compliance_actor(
        account_id="acct-1",
        initial_balance=Decimal("100000"),
        rule_engine=MagicMock(),
    )
    assert actor._config.daily_session_tz == "UTC"


def test_custom_session_tz_propagated() -> None:
    actor = build_compliance_actor(
        account_id="acct-1",
        initial_balance=Decimal("100000"),
        rule_engine=MagicMock(),
        daily_session_tz="America/New_York",
    )
    assert actor._config.daily_session_tz == "America/New_York"
