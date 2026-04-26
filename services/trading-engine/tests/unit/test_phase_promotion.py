"""Unit tests for phase_promotion service (Epic 9 Phase 0, task P0.10).

Pure-logic helper invoked by the ``trading-engine accounts promote`` CLI.
The helper validates that a target phase transition is allowed by the
firm's product profile and produces an :class:`AuditEntry` describing
the intent. Persisting the audit entry and updating the account's YAML
phase remain operational concerns outside this helper.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.accounts.phase_promotion import (
    PhasePromotionError,
    build_phase_transition_audit_entry,
    validate_phase_transition,
)
from src.config.firm_profile import (
    AccountPhase,
    AccountProduct,
    FirmProfile,
    SessionConfig,
)
from src.config.firm_registry import (
    FirmNotFoundError,
    PhaseNotFoundError,
    ProductNotFoundError,
)
from src.rules.audit_logger import AuditEventType


# ---------------------------------------------------------------------------
# Test fixtures — minimal real domain objects (P0.1 dataclasses are frozen)
# ---------------------------------------------------------------------------


def _stub_rule(rule_type: str = "max_drawdown") -> object:
    """Return a tiny BaseRule-protocol-compatible stub."""
    rule = MagicMock()
    rule.rule_type = rule_type
    return rule


def _make_product() -> AccountProduct:
    evaluation = AccountPhase(
        phase_id="evaluation",
        name="Evaluation",
        allowed_transitions=("verification", "stopped"),
    )
    verification = AccountPhase(
        phase_id="verification",
        name="Verification",
        allowed_transitions=("funded", "stopped"),
    )
    funded = AccountPhase(
        phase_id="funded",
        name="Funded",
        allowed_transitions=("stopped",),
    )
    stopped = AccountPhase(phase_id="stopped", name="Stopped")
    return AccountProduct(
        product_id="challenge",
        name="FTMO Challenge",
        rules=[_stub_rule()],
        phases=(evaluation, verification, funded, stopped),
    )


def _make_firm() -> FirmProfile:
    product = _make_product()
    return FirmProfile(
        firm_id="ftmo",
        name="FTMO",
        version="2026.1",
        session=SessionConfig(timezone="Europe/Berlin", reset_time="00:00"),
        products={"challenge": product},
    )


def _make_account(
    *,
    account_id: str = "ftmo-001",
    firm_id: str | None = "ftmo",
    product_id: str | None = "challenge",
    phase: str | None = "evaluation",
) -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.firm_id = firm_id
    account.product_id = product_id
    account.phase = phase
    return account


def _make_registry(firm: FirmProfile = None):
    """Mock FirmRegistry whose ``resolve`` matches the real signature."""
    firm = firm or _make_firm()
    registry = MagicMock()

    def resolve(firm_id: str, product_id: str, phase_id: str):
        if firm_id != firm.firm_id:
            raise FirmNotFoundError(f"firm_id {firm_id!r} not in registry")
        if product_id not in firm.products:
            raise ProductNotFoundError(f"product_id {product_id!r} not found")
        product = firm.products[product_id]
        try:
            phase = product.get_phase(phase_id)
        except KeyError as exc:
            raise PhaseNotFoundError(str(exc)) from exc
        return firm, product, phase

    registry.resolve.side_effect = resolve
    return registry


# ---------------------------------------------------------------------------
# validate_phase_transition
# ---------------------------------------------------------------------------


class TestValidatePhaseTransition:
    def test_allowed_transition_returns_target_phase(self):
        account = _make_account(phase="evaluation")
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        assert from_phase.phase_id == "evaluation"
        assert to_phase.phase_id == "verification"

    def test_account_without_firm_binding_rejected(self):
        account = _make_account(firm_id=None)
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="not firm-bound"):
            validate_phase_transition(account, registry, target_phase_id="verification")

    def test_account_without_product_id_rejected(self):
        account = _make_account(product_id=None)
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="not firm-bound"):
            validate_phase_transition(account, registry, target_phase_id="verification")

    def test_account_without_current_phase_rejected(self):
        account = _make_account(phase=None)
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="not firm-bound"):
            validate_phase_transition(account, registry, target_phase_id="verification")

    def test_unknown_firm_propagates_as_promotion_error(self):
        account = _make_account(firm_id="bogus")
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="firm_id"):
            validate_phase_transition(account, registry, target_phase_id="verification")

    def test_unknown_target_phase_rejected(self):
        account = _make_account(phase="evaluation")
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="atlantis"):
            validate_phase_transition(account, registry, target_phase_id="atlantis")

    def test_disallowed_transition_rejected(self):
        # evaluation → funded is NOT in allowed_transitions
        account = _make_account(phase="evaluation")
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="not allowed"):
            validate_phase_transition(account, registry, target_phase_id="funded")

    def test_same_phase_rejected(self):
        account = _make_account(phase="evaluation")
        registry = _make_registry()
        with pytest.raises(PhasePromotionError, match="already"):
            validate_phase_transition(account, registry, target_phase_id="evaluation")


# ---------------------------------------------------------------------------
# build_phase_transition_audit_entry
# ---------------------------------------------------------------------------


class TestBuildAuditEntry:
    def test_entry_uses_system_event_type_and_phase_subtype(self):
        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="Passed Challenge: 10% target hit on 2026-04-15",
            actor="ops",
        )
        assert entry.event_type == AuditEventType.SYSTEM_EVENT.value
        assert entry.event_subtype == "phase_transition"

    def test_entry_records_account_id_and_message(self):
        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="ops decision",
            actor="ops",
        )
        assert entry.account_id == "ftmo-001"
        assert "evaluation" in entry.message
        assert "verification" in entry.message

    def test_entry_context_captures_full_transition(self):
        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="ops decision",
            actor="ops-ngoc",
        )
        ctx = entry.context
        assert ctx["firm_id"] == "ftmo"
        assert ctx["product_id"] == "challenge"
        assert ctx["from_phase"] == "evaluation"
        assert ctx["to_phase"] == "verification"
        assert ctx["reason"] == "ops decision"
        assert ctx["actor"] == "ops-ngoc"

    def test_entry_level_is_info(self):
        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="ops",
            actor="ops",
        )
        assert entry.level == "INFO"

    def test_explicit_correlation_id_propagated(self):
        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="ops",
            actor="ops",
            correlation_id="cid-test-123",
        )
        assert entry.context["correlation_id"] == "cid-test-123"
        assert "cid-test-123" in entry.message

    def test_auto_correlation_id_is_uuid_when_not_provided(self):
        import uuid as _uuid

        account = _make_account()
        registry = _make_registry()
        from_phase, to_phase = validate_phase_transition(
            account, registry, target_phase_id="verification",
        )
        entry = build_phase_transition_audit_entry(
            account=account,
            from_phase=from_phase,
            to_phase=to_phase,
            reason="ops",
            actor="ops",
        )
        cid = entry.context["correlation_id"]
        # Should parse as a valid UUID
        _uuid.UUID(cid)
        assert cid in entry.message
