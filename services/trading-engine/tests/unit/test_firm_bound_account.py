"""Unit tests for Epic 9 P0.3 — firm-bound account binding.

Covers:
- ``AccountConfig`` new fields (firm_id / product_id / phase / rule_overrides)
  and the ``validate_rules_source`` / ``validate_prop_firm_preset`` logic
  that prevents conflicting or incomplete rule sources.
- ``RuleAssignment.from_account_config`` routing to ``"firm"`` assignment.
- ``RuleAssignmentService`` firm-bound path using ``FirmRegistry``.

Backward compatibility for existing ``prop_firm``-based accounts is
guarded by the pre-existing test files (``test_account_models.py``,
``test_rule_assignment.py``); this file only asserts the *new* behaviour.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
from pydantic import ValidationError

from src.accounts.models import AccountConfig, AccountType, MT5Config
from src.config.firm_registry import FirmRegistry
from src.rules.assignment import RuleAssignment
from src.rules.assignment_service import RuleAssignmentService


FIRM_YAML = dedent(
    """
    firm_id: ftmo
    name: "FTMO"
    version: "2025.1"
    session:
      timezone: "CET"
      reset_time: "00:00"
    products:
      challenge:
        product_id: challenge
        name: "FTMO Challenge"
        rules:
          - type: daily_loss_limit
            threshold_percent: 5.0
            timezone: "CET"
          - type: max_drawdown
            threshold_percent: 10.0
        phases:
          - phase_id: evaluation
            name: Evaluation
            allowed_transitions: [verification]
          - phase_id: verification
            name: Verification
            allowed_transitions: [funded]
          - phase_id: funded
            name: Funded
    """
).strip()


def _mt5() -> MT5Config:
    return MT5Config(server="Srv", login=12345, password_env="TEST_PASS")


def _firm_bound_kwargs(**over: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(
        id="ftmo-001",
        name="FTMO Gold",
        type=AccountType.PROP_FIRM,
        firm_id="ftmo",
        product_id="challenge",
        phase="evaluation",
        mt5=_mt5(),
        strategy="ma_crossover",
    )
    defaults.update(over)
    return defaults


@pytest.fixture
def firm_registry(tmp_path: Path) -> FirmRegistry:
    d = tmp_path / "firms"
    d.mkdir()
    (d / "ftmo.yaml").write_text(FIRM_YAML)
    registry = FirmRegistry(d)
    registry.load()
    return registry


# ---------------------------------------------------------------------------
# AccountConfig validators
# ---------------------------------------------------------------------------


class TestAccountConfigFirmBinding:
    def test_accepts_full_firm_binding(self):
        acc = AccountConfig(**_firm_bound_kwargs())
        assert acc.firm_id == "ftmo"
        assert acc.product_id == "challenge"
        assert acc.phase == "evaluation"
        assert acc.rule_overrides == {}
        assert acc.rules_file is None

    def test_normalizes_firm_id_to_lowercase(self):
        acc = AccountConfig(**_firm_bound_kwargs(firm_id="FTMO"))
        assert acc.firm_id == "ftmo"

    def test_accepts_rule_overrides(self):
        acc = AccountConfig(
            **_firm_bound_kwargs(
                rule_overrides={"consistency": {"block_at": 45}},
            )
        )
        assert acc.rule_overrides["consistency"]["block_at"] == 45

    def test_rejects_incomplete_firm_binding_missing_product(self):
        with pytest.raises(ValidationError, match="firm binding is incomplete"):
            AccountConfig(**_firm_bound_kwargs(product_id=None))

    def test_rejects_incomplete_firm_binding_missing_phase(self):
        with pytest.raises(ValidationError, match="firm binding is incomplete"):
            AccountConfig(**_firm_bound_kwargs(phase=None))

    def test_rejects_firm_binding_mixed_with_rules_file(self):
        with pytest.raises(ValidationError, match="exactly one rule source"):
            AccountConfig(**_firm_bound_kwargs(rules_file="configs/custom.yaml"))

    def test_rejects_rule_overrides_without_firm_binding(self):
        """Story 10.12 — rule_overrides require a firm binding; a
        personal account must not declare them."""
        with pytest.raises(ValidationError, match="rule_overrides only apply"):
            AccountConfig(
                id="personal-001",
                name="Personal",
                type=AccountType.PERSONAL,
                rules_file="configs/custom.yaml",
                rule_overrides={"consistency": {"block_at": 45}},
                mt5=_mt5(),
                strategy="ma_crossover",
            )

    def test_demo_still_requires_no_rule_source(self):
        acc = AccountConfig(
            id="demo-001",
            name="Demo",
            type=AccountType.DEMO,
            mt5=_mt5(),
            strategy="ma_crossover",
        )
        assert acc.firm_id is None
        assert acc.rules_file is None

    def test_demo_rejects_firm_binding(self):
        with pytest.raises(ValidationError, match="demo.*must have no rule source"):
            AccountConfig(**_firm_bound_kwargs(type=AccountType.DEMO))


# ---------------------------------------------------------------------------
# RuleAssignment.from_account_config
# ---------------------------------------------------------------------------


class TestRuleAssignmentFromFirmConfig:
    def test_firm_bound_account_produces_firm_assignment(self):
        acc = AccountConfig(
            **_firm_bound_kwargs(
                rule_overrides={"consistency": {"block_at": 45}},
            )
        )
        assignment = RuleAssignment.from_account_config(acc)
        assert assignment.assignment_type == "firm"
        assert assignment.firm_id == "ftmo"
        assert assignment.product_id == "challenge"
        assert assignment.phase == "evaluation"
        assert assignment.rule_overrides == {"consistency": {"block_at": 45}}
        assert assignment.preset_name is None

    def test_source_description_for_firm_assignment(self):
        acc = AccountConfig(**_firm_bound_kwargs())
        assignment = RuleAssignment.from_account_config(acc)
        assert assignment.source_description == "firm:ftmo/challenge/evaluation"

    def test_repr_for_firm_assignment(self):
        assignment = RuleAssignment(
            assignment_type="firm",
            firm_id="ftmo",
            product_id="challenge",
            phase="evaluation",
            rule_overrides={"x": 1},
        )
        rendered = repr(assignment)
        assert "firm='ftmo'" in rendered
        assert "product='challenge'" in rendered
        assert "phase='evaluation'" in rendered
        assert "overrides=1" in rendered

    def test_rule_overrides_isolated_from_account_mutation(self):
        overrides = {"x": 1}
        acc = AccountConfig(**_firm_bound_kwargs(rule_overrides=overrides))
        assignment = RuleAssignment.from_account_config(acc)
        acc.rule_overrides["x"] = 999
        assert assignment.rule_overrides["x"] == 1

    def test_rule_overrides_isolated_from_nested_mutation(self):
        acc = AccountConfig(
            **_firm_bound_kwargs(
                rule_overrides={"consistency": {"block_at": 45}},
            )
        )
        assignment = RuleAssignment.from_account_config(acc)
        acc.rule_overrides["consistency"]["block_at"] = 999
        assert assignment.rule_overrides["consistency"]["block_at"] == 45

    def test_direct_construct_requires_all_firm_fields(self):
        with pytest.raises(ValueError, match="missing"):
            RuleAssignment(assignment_type="firm", firm_id="ftmo")


# ---------------------------------------------------------------------------
# RuleAssignmentService firm-bound path
# ---------------------------------------------------------------------------


class TestRuleAssignmentServiceFirmBound:
    def test_firm_bound_account_loads_product_rules(
        self, firm_registry: FirmRegistry
    ):
        service = RuleAssignmentService(firm_registry=firm_registry)
        acc = AccountConfig(**_firm_bound_kwargs())
        rules = service.get_rules_for_account(acc)
        assert len(rules) == 2
        assert [r.rule_type for r in rules] == [
            "daily_loss_limit",
            "max_drawdown",
        ]

    def test_firm_bound_without_registry_raises_typed_error(self):
        from src.config.firm_registry import (
            FirmRegistryError,
            FirmRegistryNotConfiguredError,
        )

        service = RuleAssignmentService()
        acc = AccountConfig(**_firm_bound_kwargs())
        with pytest.raises(FirmRegistryNotConfiguredError, match="firm-bound"):
            service.get_rules_for_account(acc)
        # Catch-all via the base also works — keeps caller boilerplate low.
        with pytest.raises(FirmRegistryError):
            service.get_rules_for_account(acc)

    def test_unknown_firm_id_raises_firm_not_found(
        self, firm_registry: FirmRegistry
    ):
        from src.config.firm_registry import FirmNotFoundError

        service = RuleAssignmentService(firm_registry=firm_registry)
        acc = AccountConfig(**_firm_bound_kwargs(firm_id="apex"))
        with pytest.raises(FirmNotFoundError):
            service.get_rules_for_account(acc)

    def test_unknown_product_raises_product_not_found(
        self, firm_registry: FirmRegistry
    ):
        from src.config.firm_registry import ProductNotFoundError

        service = RuleAssignmentService(firm_registry=firm_registry)
        acc = AccountConfig(**_firm_bound_kwargs(product_id="bogus"))
        with pytest.raises(ProductNotFoundError):
            service.get_rules_for_account(acc)

    def test_unknown_phase_raises_phase_not_found(
        self, firm_registry: FirmRegistry
    ):
        from src.config.firm_registry import PhaseNotFoundError

        service = RuleAssignmentService(firm_registry=firm_registry)
        acc = AccountConfig(**_firm_bound_kwargs(phase="mars"))
        with pytest.raises(PhaseNotFoundError):
            service.get_rules_for_account(acc)

    # Story 10.12 removed the legacy ``prop_firm`` preset path; the
    # corresponding test (``test_legacy_preset_path_still_works``) is
    # gone — coverage of personal/firm paths is provided by the
    # ``TestRuleAssignmentServiceFirmBound`` and rule-assignment unit
    # tests above.
