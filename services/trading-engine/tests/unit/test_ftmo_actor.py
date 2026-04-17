"""Unit tests for FtmoComplianceActor.

We test the actor's pure logic (rule-engine invocation, breach dedup,
equity curve accumulation) without instantiating a full BacktestEngine.
The Nautilus ``Actor`` base is Cython and exposes ``portfolio`` / ``cache``
as read-only attrs, so the actor is designed with a thin seam
(``_build_account_state``) that tests patch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from src.backtesting.ftmo_actor import (
    FtmoComplianceActor,
    FtmoComplianceActorConfig,
)
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine_result import RuleEngineResult


pytestmark = pytest.mark.unit


def _make_actor(rule_engine) -> FtmoComplianceActor:
    config = FtmoComplianceActorConfig(
        account_id="ftmo-test",
        initial_balance=Decimal("100000"),
    )
    actor = FtmoComplianceActor(config=config, rule_engine=rule_engine)
    return actor


class TestActorSubclass:
    def test_is_nautilus_actor(self) -> None:
        rule_engine = Mock()
        actor = _make_actor(rule_engine)
        assert isinstance(actor, Actor)

    def test_config_is_actor_config(self) -> None:
        assert issubclass(FtmoComplianceActorConfig, ActorConfig)


class TestEvaluateCompliance:
    def test_allow_records_no_breach(self) -> None:
        rule_engine = Mock()
        rule_engine.validate = Mock(
            return_value=RuleEngineResult(
                action=RuleAction.ALLOW,
                blocked_by=None,
                blocking_reason=None,
                warnings=[],
                all_results=[],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        state = {"balance": Decimal("100000"), "equity": Decimal("100000")}
        new_breaches = actor.evaluate_compliance(state, ts=datetime(2026, 1, 1, tzinfo=UTC))
        assert new_breaches == []
        rule_engine.validate.assert_called_once()

    def test_block_records_breach(self) -> None:
        mock_rule = Mock()
        mock_rule.name = "daily_loss_limit"
        rule_engine = Mock()
        rule_engine.validate = Mock(
            return_value=RuleEngineResult(
                action=RuleAction.BLOCK,
                blocked_by=mock_rule,
                blocking_reason="Daily loss 5.2% exceeds 5%",
                warnings=[],
                all_results=[
                    (
                        mock_rule,
                        RuleResult(
                            action=RuleAction.BLOCK,
                            message="Daily loss 5.2% exceeds 5%",
                            current_value=5.2,
                            threshold_value=5.0,
                        ),
                    )
                ],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        state = {"balance": Decimal("94800"), "equity": Decimal("94800")}
        new_breaches = actor.evaluate_compliance(state, ts=datetime(2026, 1, 1, tzinfo=UTC))
        assert len(new_breaches) == 1
        assert new_breaches[0].rule_name == "daily_loss_limit"
        assert new_breaches[0].current_value == 5.2
        assert new_breaches[0].threshold_value == 5.0


class TestBreachDeduplication:
    def test_same_day_same_rule_recorded_once(self) -> None:
        """A losing day must register one daily-loss breach, not one per bar."""
        mock_rule = Mock()
        mock_rule.name = "daily_loss_limit"
        rule_engine = Mock()
        rule_engine.validate = Mock(
            return_value=RuleEngineResult(
                action=RuleAction.BLOCK,
                blocked_by=mock_rule,
                blocking_reason="Daily loss breach",
                warnings=[],
                all_results=[
                    (
                        mock_rule,
                        RuleResult(
                            action=RuleAction.BLOCK,
                            message="Daily loss breach",
                            current_value=5.2,
                            threshold_value=5.0,
                        ),
                    )
                ],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        state = {"balance": Decimal("94800"), "equity": Decimal("94800")}

        base_ts = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        actor.record_compliance_check(state, ts=base_ts)
        actor.record_compliance_check(state, ts=base_ts + timedelta(hours=1))
        actor.record_compliance_check(state, ts=base_ts + timedelta(hours=5))

        assert len(actor.breaches) == 1  # deduped on (date, rule_name)

    def test_different_days_recorded_separately(self) -> None:
        mock_rule = Mock()
        mock_rule.name = "daily_loss_limit"
        rule_engine = Mock()
        rule_engine.validate = Mock(
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
                            current_value=6.0,
                            threshold_value=5.0,
                        ),
                    )
                ],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        state = {"balance": Decimal("94000"), "equity": Decimal("94000")}

        actor.record_compliance_check(
            state, ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        )
        actor.record_compliance_check(
            state, ts=datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
        )
        assert len(actor.breaches) == 2

    def test_different_rules_same_day_recorded_separately(self) -> None:
        mock_rule_a = Mock()
        mock_rule_a.name = "daily_loss_limit"
        mock_rule_b = Mock()
        mock_rule_b.name = "max_drawdown"
        rule_engine = Mock()
        rule_engine.validate = Mock(
            return_value=RuleEngineResult(
                action=RuleAction.BLOCK,
                blocked_by=mock_rule_a,
                blocking_reason="breach",
                warnings=[],
                all_results=[
                    (
                        mock_rule_a,
                        RuleResult(
                            action=RuleAction.BLOCK,
                            message="daily loss",
                            current_value=5.5,
                            threshold_value=5.0,
                        ),
                    ),
                    (
                        mock_rule_b,
                        RuleResult(
                            action=RuleAction.BLOCK,
                            message="max dd",
                            current_value=11,
                            threshold_value=10,
                        ),
                    ),
                ],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        state = {"balance": Decimal("89000"), "equity": Decimal("89000")}
        actor.record_compliance_check(
            state, ts=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        )
        assert len(actor.breaches) == 2


class TestEquityTracking:
    def test_equity_curve_accumulates(self) -> None:
        rule_engine = Mock()
        rule_engine.validate = Mock(
            return_value=RuleEngineResult(
                action=RuleAction.ALLOW,
                blocked_by=None,
                blocking_reason=None,
                warnings=[],
                all_results=[],
                evaluation_time_ms=0.1,
            )
        )
        actor = _make_actor(rule_engine)
        ts0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        actor.record_equity(ts=ts0, equity=Decimal("100000"))
        actor.record_equity(ts=ts0 + timedelta(hours=1), equity=Decimal("100500"))
        assert len(actor.equity_curve) == 2
        assert actor.equity_curve[-1][1] == Decimal("100500")

    def test_peak_balance_updated(self) -> None:
        rule_engine = Mock()
        actor = _make_actor(rule_engine)
        ts0 = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        actor.record_equity(ts=ts0, equity=Decimal("100000"))
        actor.record_equity(ts=ts0 + timedelta(hours=1), equity=Decimal("102000"))
        actor.record_equity(ts=ts0 + timedelta(hours=2), equity=Decimal("101000"))
        assert actor.peak_balance == Decimal("102000")
