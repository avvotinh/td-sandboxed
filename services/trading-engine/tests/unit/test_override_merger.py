"""Unit tests for the rule override merger (Epic 9 P0.16).

Covers the three-layer merge contract (product → phase → account), the
typo guards, and the no-loosening safety guard for guarded rule types.
"""

from __future__ import annotations

import pytest

from src.rules.override_merger import (
    RuleOverrideError,
    merge_rule_overrides,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _baseline_specs() -> list[dict]:
    """Realistic FTMO-shaped product baseline used by most tests."""
    return [
        {
            "type": "daily_loss_limit",
            "threshold_percent": 5.0,
            "reset_time": "00:00",
            "timezone": "CET",
            "warning_at": [70, 80, 90],
        },
        {
            "type": "max_drawdown",
            "threshold_percent": 10.0,
            "reference": "initial_balance",
            "method": "balance_based",
            "warning_at": [50, 70, 85],
        },
        {
            "type": "max_position_size",
            "max_lots": 100.0,
            "scaling": "per_10k_balance",
        },
        {
            "type": "consistency",
            "block_at": 50.0,
            "warn_at": [40, 45, 48],
        },
        {
            "type": "profit_target",
            "threshold_percent": 10.0,
            "action": "notify",
        },
    ]


# ---------------------------------------------------------------------------
# No-overrides passthrough
# ---------------------------------------------------------------------------


class TestNoOverrides:
    def test_returns_baseline_when_both_layers_empty(self):
        baseline = _baseline_specs()
        result = merge_rule_overrides(baseline, {}, {})
        assert result == baseline

    def test_returns_deep_copy_not_aliased(self):
        baseline = _baseline_specs()
        result = merge_rule_overrides(baseline, {}, {})
        # Mutating the result must not change the baseline.
        result[0]["threshold_percent"] = 999.0
        assert baseline[0]["threshold_percent"] == 5.0

    def test_preserves_order(self):
        baseline = _baseline_specs()
        result = merge_rule_overrides(baseline, {}, {})
        assert [r["type"] for r in result] == [r["type"] for r in baseline]

# ---------------------------------------------------------------------------
# Phase layer — firm-controlled, no guard
# ---------------------------------------------------------------------------


class TestPhaseLayer:
    def test_phase_can_lower_informational_threshold(self):
        # FTMO funded vs evaluation legitimately drops profit_target from 10 → 5.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={"profit_target": {"threshold_percent": 5.0}},
            account_overrides={},
        )
        profit_target = next(r for r in result if r["type"] == "profit_target")
        assert profit_target["threshold_percent"] == 5.0

    def test_phase_can_loosen_guarded_threshold_without_complaint(self):
        # Phase overrides are firm-controlled; the guard does not apply.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={"daily_loss_limit": {"threshold_percent": 8.0}},
            account_overrides={},
        )
        daily = next(r for r in result if r["type"] == "daily_loss_limit")
        assert daily["threshold_percent"] == 8.0

    def test_phase_unknown_rule_type_rejected(self):
        with pytest.raises(RuleOverrideError, match="phase override targets unknown rule_type"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={"never_existed_rule": {"threshold_percent": 1.0}},
                account_overrides={},
            )

    def test_phase_unknown_field_rejected(self):
        with pytest.raises(RuleOverrideError, match="unknown field 'thresholdd_percent'"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={"daily_loss_limit": {"thresholdd_percent": 4.0}},
                account_overrides={},
            )


# ---------------------------------------------------------------------------
# Account layer — ops-controlled, guarded
# ---------------------------------------------------------------------------


class TestAccountLayerGuards:
    def test_tighten_daily_loss_allowed(self):
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"daily_loss_limit": {"threshold_percent": 3.0}},
        )
        daily = next(r for r in result if r["type"] == "daily_loss_limit")
        assert daily["threshold_percent"] == 3.0

    def test_loosen_daily_loss_rejected(self):
        with pytest.raises(RuleOverrideError, match="would loosen"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"daily_loss_limit": {"threshold_percent": 7.0}},
            )

    def test_tighten_max_drawdown_allowed(self):
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"max_drawdown": {"threshold_percent": 6.0}},
        )
        dd = next(r for r in result if r["type"] == "max_drawdown")
        assert dd["threshold_percent"] == 6.0

    def test_loosen_max_drawdown_rejected(self):
        with pytest.raises(RuleOverrideError, match="would loosen"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"max_drawdown": {"threshold_percent": 12.0}},
            )

    def test_tighten_consistency_block_at_allowed(self):
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"consistency": {"block_at": 45.0}},
        )
        cons = next(r for r in result if r["type"] == "consistency")
        assert cons["block_at"] == 45.0

    def test_loosen_consistency_block_at_rejected(self):
        with pytest.raises(RuleOverrideError, match="consistency.block_at"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"consistency": {"block_at": 55.0}},
            )

    def test_tighten_max_position_size_allowed(self):
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"max_position_size": {"max_lots": 50.0}},
        )
        pos = next(r for r in result if r["type"] == "max_position_size")
        assert pos["max_lots"] == 50.0

    def test_loosen_max_position_size_rejected(self):
        with pytest.raises(RuleOverrideError, match="would loosen"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"max_position_size": {"max_lots": 200.0}},
            )

    def test_account_id_appears_in_error_message(self):
        with pytest.raises(RuleOverrideError, match="account 'ftmo-001'"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"daily_loss_limit": {"threshold_percent": 99.0}},
                account_id="ftmo-001",
            )

    def test_nan_value_rejected_not_silently_passed(self):
        # NaN compares False against everything, so a sneaky NaN would
        # bypass both > and < tightness checks. The guard must reject it
        # before reaching the comparison.
        with pytest.raises(RuleOverrideError, match="NaN"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"daily_loss_limit": {"threshold_percent": float("nan")}},
            )

    def test_inf_loosening_still_caught(self):
        # +inf > any finite baseline → must be flagged as loosening, not as
        # NaN. Locks in that the comparison still works for infinity.
        with pytest.raises(RuleOverrideError, match="would loosen"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"daily_loss_limit": {"threshold_percent": float("inf")}},
            )


# ---------------------------------------------------------------------------
# Account layer — ungaurded fields & rule types
# ---------------------------------------------------------------------------


class TestAccountLayerUngaurded:
    def test_warn_at_can_be_freely_overridden_on_consistency(self):
        # warn_at is the warn ladder, not the block threshold — no guard.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"consistency": {"warn_at": [30, 35]}},
        )
        cons = next(r for r in result if r["type"] == "consistency")
        assert cons["warn_at"] == [30, 35]
        # The block threshold is untouched.
        assert cons["block_at"] == 50.0

    def test_warning_at_on_daily_loss_unguarded(self):
        # warning_at is the percent-of-limit warn ladder, not the block.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"daily_loss_limit": {"warning_at": [50, 60, 70]}},
        )
        daily = next(r for r in result if r["type"] == "daily_loss_limit")
        assert daily["warning_at"] == [50, 60, 70]

    def test_informational_rule_threshold_freely_overridable(self):
        # profit_target is informational; raising the bar is fine.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={},
            account_overrides={"profit_target": {"threshold_percent": 12.0}},
        )
        pt = next(r for r in result if r["type"] == "profit_target")
        assert pt["threshold_percent"] == 12.0


# ---------------------------------------------------------------------------
# Account layer — typo and structural guards
# ---------------------------------------------------------------------------


class TestAccountLayerTypoGuards:
    def test_unknown_rule_type_rejected(self):
        with pytest.raises(RuleOverrideError, match="unknown rule_type 'concsistency'"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"concsistency": {"block_at": 45.0}},
            )

    def test_unknown_field_rejected(self):
        with pytest.raises(RuleOverrideError, match="unknown field 'block_att'"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"consistency": {"block_att": 45.0}},
            )

    def test_type_field_change_rejected(self):
        with pytest.raises(RuleOverrideError, match="may not change the 'type' field"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"consistency": {"type": "weekly_target"}},
            )

    def test_non_mapping_override_rejected(self):
        with pytest.raises(RuleOverrideError, match="must be a mapping"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={},
                account_overrides={"consistency": "block_at=45"},  # type: ignore[dict-item]
            )


# ---------------------------------------------------------------------------
# Layer composition
# ---------------------------------------------------------------------------


class TestLayerComposition:
    def test_account_tightens_value_set_by_phase(self):
        # Phase loosens daily_loss to 8 (firm legitimately allows). Account
        # then tightens it to 4 — allowed because 4 < 8.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={"daily_loss_limit": {"threshold_percent": 8.0}},
            account_overrides={"daily_loss_limit": {"threshold_percent": 4.0}},
        )
        daily = next(r for r in result if r["type"] == "daily_loss_limit")
        assert daily["threshold_percent"] == 4.0

    def test_account_cannot_loosen_phase_resolved_baseline(self):
        # Phase tightens daily_loss to 3. Account asks for 4 → that loosens
        # the *phase-resolved* baseline of 3, so it must be rejected.
        with pytest.raises(RuleOverrideError, match="would loosen"):
            merge_rule_overrides(
                _baseline_specs(),
                phase_overrides={"daily_loss_limit": {"threshold_percent": 3.0}},
                account_overrides={"daily_loss_limit": {"threshold_percent": 4.0}},
            )

    def test_account_can_match_phase_baseline(self):
        # Equal is not "loosening" — must not raise.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={"daily_loss_limit": {"threshold_percent": 4.0}},
            account_overrides={"daily_loss_limit": {"threshold_percent": 4.0}},
        )
        daily = next(r for r in result if r["type"] == "daily_loss_limit")
        assert daily["threshold_percent"] == 4.0

    def test_phase_and_account_target_different_rules(self):
        # Independent layers — both fields end up applied.
        result = merge_rule_overrides(
            _baseline_specs(),
            phase_overrides={"profit_target": {"threshold_percent": 5.0}},
            account_overrides={"consistency": {"block_at": 45.0}},
        )
        pt = next(r for r in result if r["type"] == "profit_target")
        cons = next(r for r in result if r["type"] == "consistency")
        assert pt["threshold_percent"] == 5.0
        assert cons["block_at"] == 45.0


# ---------------------------------------------------------------------------
# Malformed baseline
# ---------------------------------------------------------------------------


class TestMalformedBaseline:
    def test_baseline_missing_type_rejected(self):
        with pytest.raises(RuleOverrideError, match="missing string 'type' field"):
            merge_rule_overrides(
                [{"threshold_percent": 5.0}],
                phase_overrides={},
                account_overrides={},
            )

    def test_baseline_duplicate_type_rejected(self):
        with pytest.raises(RuleOverrideError, match="more than once"):
            merge_rule_overrides(
                [
                    {"type": "daily_loss_limit", "threshold_percent": 5.0},
                    {"type": "daily_loss_limit", "threshold_percent": 4.0},
                ],
                phase_overrides={},
                account_overrides={},
            )
