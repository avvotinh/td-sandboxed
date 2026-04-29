"""End-to-end integration test for per-account rule_overrides (Epic 9 P0.16).

Exercises the full firm-binding path: shipped ``configs/firms/*.yaml`` →
:class:`FirmRegistry` → :class:`RuleAssignmentService` → instantiated rules.
The unit tests in ``test_override_merger.py`` cover the merge contract in
isolation; this file verifies that the wired path produces a rule list with
the **effective** thresholds, both for the no-overrides fast path and for
the merged-and-reparsed path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.accounts.models import AccountConfig, AccountType, MT5Config
from src.config.firm_registry import FirmRegistry
from src.rules.assignment_service import RuleAssignmentService
from src.rules.override_merger import RuleOverrideError


# ---------------------------------------------------------------------------
# Fixtures — load real YAMLs once per module, mirror test_firm_yaml_configs.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def firms_dir(pytestconfig: pytest.Config) -> Path:
    d = pytestconfig.rootpath.parents[1] / "configs" / "firms"
    assert d.is_dir(), f"firms dir missing: {d}"
    return d


@pytest.fixture(scope="module")
def registry(firms_dir: Path) -> FirmRegistry:
    r = FirmRegistry(firms_dir)
    r.load()
    return r


@pytest.fixture
def service(registry: FirmRegistry) -> RuleAssignmentService:
    # Fresh service per test so cache state never crosses cases.
    return RuleAssignmentService(firm_registry=registry)


def _mt5() -> MT5Config:
    return MT5Config(server="Test-Server", login=12345, password_env="TEST_PASS")


def _ftmo_account(
    account_id: str = "ftmo-001",
    phase: str = "evaluation",
    rule_overrides: dict | None = None,
) -> AccountConfig:
    return AccountConfig(
        id=account_id,
        name=f"FTMO {account_id}",
        type=AccountType.PROP_FIRM,
        firm_id="ftmo",
        product_id="challenge",
        phase=phase,
        rule_overrides=rule_overrides or {},
        mt5=_mt5(),
        strategy="ma_crossover",
    )


def _find(rules: list, rule_type: str):
    for r in rules:
        if getattr(r, "rule_type", None) == rule_type:
            return r
    raise AssertionError(f"rule_type {rule_type!r} not in instantiated rules")


# ---------------------------------------------------------------------------
# No-overrides — fresh rules per account (no cached aliasing).
# ---------------------------------------------------------------------------


class TestNoOverrides:
    def test_returns_semantically_equivalent_rule_set(
        self, registry: FirmRegistry, service: RuleAssignmentService
    ) -> None:
        # FTMO challenge `funded` phase has no rule_overrides; account has none.
        # The service must still produce a rule set whose types and primary
        # thresholds match the product baseline, but with FRESH instances so
        # any future stateful field on a BaseRule subclass cannot leak across
        # accounts via a shared cached tuple.
        account = _ftmo_account(phase="funded")
        rules = service.get_rules_for_account(account)

        product = registry.get("ftmo").get_product("challenge")
        assert [r.rule_type for r in rules] == [r.rule_type for r in product.rules]
        # Per-account isolation: identity check confirms re-instantiation.
        assert all(r is not br for r, br in zip(rules, product.rules)), (
            "rule instances must be fresh per account; cached aliasing risks "
            "stateful-rule cross-talk between accounts"
        )
        # Spot-check a primary threshold to confirm the merge passthrough is
        # value-correct.
        assert _find(rules, "daily_loss_limit").threshold_percent == pytest.approx(5.0)
        assert _find(rules, "max_drawdown").threshold_percent == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Phase-only overrides — applied without guard (firm-controlled).
# ---------------------------------------------------------------------------


class TestPhaseOverridesAppliedThroughService:
    def test_evaluation_phase_keeps_profit_target_at_10(
        self, service: RuleAssignmentService
    ) -> None:
        # `evaluation` phase rule_overrides set profit_target.threshold_percent
        # to 10.0, matching the product baseline (10.0). The service still
        # walks the override path because phase_overrides is non-empty.
        account = _ftmo_account(phase="evaluation")
        rules = service.get_rules_for_account(account)
        profit_target = _find(rules, "profit_target")
        assert profit_target.threshold_percent == pytest.approx(10.0)

    def test_verification_phase_lowers_profit_target_to_5(
        self, service: RuleAssignmentService
    ) -> None:
        # FTMO Step 2 verification overrides profit_target down to 5%; this
        # is a legitimate firm-level loosening of an INFORMATIONAL rule, so
        # the merger must not raise.
        account = _ftmo_account(phase="verification")
        rules = service.get_rules_for_account(account)
        profit_target = _find(rules, "profit_target")
        assert profit_target.threshold_percent == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Account overrides — guarded.
# ---------------------------------------------------------------------------


class TestAccountOverridesAppliedThroughService:
    def test_tighter_daily_loss_propagates_to_instantiated_rule(
        self, service: RuleAssignmentService
    ) -> None:
        account = _ftmo_account(
            account_id="ftmo-prudent",
            phase="funded",
            rule_overrides={"daily_loss_limit": {"threshold_percent": 3.0}},
        )
        rules = service.get_rules_for_account(account)

        daily = _find(rules, "daily_loss_limit")
        assert daily.threshold_percent == pytest.approx(3.0)
        # Other rules untouched — only daily_loss should differ from baseline.
        max_dd = _find(rules, "max_drawdown")
        assert max_dd.threshold_percent == pytest.approx(10.0)

    def test_tighter_consistency_block_at_propagates(
        self, service: RuleAssignmentService
    ) -> None:
        # The baseline warn ladder (40/45/48) overlaps any block tightened
        # below 48, so the operator must tighten the warn ladder alongside
        # the block. The merger applies both as a coordinated override; the
        # rule's own __init__ enforces warn < block.
        account = _ftmo_account(
            account_id="ftmo-strict-consistency",
            phase="funded",
            rule_overrides={
                "consistency": {"block_at": 45.0, "warn_at": [35, 40]},
            },
        )
        rules = service.get_rules_for_account(account)
        cons = _find(rules, "consistency")
        assert cons.block_at == pytest.approx(45.0)
        assert cons.warn_at == [35.0, 40.0]

    def test_tightening_block_only_without_warn_update_surfaces_rule_error(
        self, service: RuleAssignmentService
    ) -> None:
        # Documents the contract: the merger does NOT inspect cross-field
        # semantic constraints (warn < block). When the override leaves the
        # warn ladder behind, the rule's own validator surfaces the conflict
        # at parse time so the misconfiguration is caught loudly.
        from src.rules.parser import RuleParseError

        account = _ftmo_account(
            account_id="ftmo-half-strict",
            phase="funded",
            rule_overrides={"consistency": {"block_at": 45.0}},
        )
        with pytest.raises(RuleParseError, match="warn_at"):
            service.get_rules_for_account(account)

    def test_loosen_attempt_raises_at_assignment_time(
        self, service: RuleAssignmentService
    ) -> None:
        # An ops-side mistake (or a malicious config) tries to raise the
        # daily loss limit. The service must reject during rule resolution
        # so the account never starts with a relaxed guard.
        account = _ftmo_account(
            account_id="ftmo-bad",
            phase="funded",
            rule_overrides={"daily_loss_limit": {"threshold_percent": 8.0}},
        )
        with pytest.raises(RuleOverrideError, match="would loosen"):
            service.get_rules_for_account(account)

    def test_unknown_rule_type_in_account_override_raises(
        self, service: RuleAssignmentService
    ) -> None:
        account = _ftmo_account(
            account_id="ftmo-typo",
            phase="funded",
            rule_overrides={"daily_lossss_limit": {"threshold_percent": 4.0}},
        )
        with pytest.raises(RuleOverrideError, match="unknown rule_type"):
            service.get_rules_for_account(account)


# ---------------------------------------------------------------------------
# Phase + account stacked.
# ---------------------------------------------------------------------------


class TestPhaseAndAccountStacked:
    def test_phase_lowers_profit_target_account_tightens_consistency(
        self, service: RuleAssignmentService
    ) -> None:
        # Verification phase brings profit_target to 5%; account independently
        # tightens consistency (both block and warn ladder together). Both
        # effects must land in the rule list.
        account = _ftmo_account(
            account_id="ftmo-step2-strict",
            phase="verification",
            rule_overrides={
                "consistency": {"block_at": 45.0, "warn_at": [35, 40]},
            },
        )
        rules = service.get_rules_for_account(account)

        assert _find(rules, "profit_target").threshold_percent == pytest.approx(5.0)
        assert _find(rules, "consistency").block_at == pytest.approx(45.0)
        # Untouched rules still hold the product baseline.
        assert _find(rules, "daily_loss_limit").threshold_percent == pytest.approx(5.0)
