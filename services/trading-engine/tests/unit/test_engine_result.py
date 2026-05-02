"""Tests for RuleEngineResult dataclass (Story 4.1).

Tests cover:
- RuleEngineResult properties and summary
- is_allowed, is_blocked properties
- has_warnings, warning_messages properties
- get_summary() method
"""

from src.rules.base_rule import RuleAction, RuleResult
from src.rules.engine_result import RuleEngineResult


class MockRule:
    """Minimal mock rule for testing."""

    def __init__(self, rule_type: str = "mock"):
        self.rule_type = rule_type
        self.name = f"Mock {rule_type}"


class TestRuleEngineResultProperties:
    """Tests for RuleEngineResult properties."""

    def test_is_allowed_for_allow_action(self):
        """Test is_allowed returns True for ALLOW action."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.is_allowed is True
        assert result.is_blocked is False

    def test_is_allowed_for_warn_action(self):
        """Test is_allowed returns True for WARN action (trade proceeds)."""
        result = RuleEngineResult(action=RuleAction.WARN)
        assert result.is_allowed is True
        assert result.is_blocked is False

    def test_is_blocked_for_block_action(self):
        """Test is_blocked returns True for BLOCK action."""
        result = RuleEngineResult(action=RuleAction.BLOCK)
        assert result.is_blocked is True
        assert result.is_allowed is False

    def test_has_warnings_false_when_empty(self):
        """Test has_warnings returns False when no warnings."""
        result = RuleEngineResult(action=RuleAction.ALLOW, warnings=[])
        assert result.has_warnings is False

    def test_has_warnings_true_when_present(self):
        """Test has_warnings returns True when warnings exist."""
        warnings = [RuleResult(action=RuleAction.WARN, message="Warning")]
        result = RuleEngineResult(action=RuleAction.WARN, warnings=warnings)
        assert result.has_warnings is True


class TestRuleEngineResultWarnings:
    """Tests for warning handling."""

    def test_warning_messages_returns_list(self):
        """Test warning_messages returns list of message strings."""
        warnings = [
            RuleResult(action=RuleAction.WARN, message="Warning 1"),
            RuleResult(action=RuleAction.WARN, message="Warning 2"),
        ]
        result = RuleEngineResult(action=RuleAction.WARN, warnings=warnings)

        assert result.warning_messages == ["Warning 1", "Warning 2"]

    def test_warning_messages_excludes_none(self):
        """Test warning_messages excludes None messages."""
        warnings = [
            RuleResult(action=RuleAction.WARN, message="Warning 1"),
            RuleResult(action=RuleAction.WARN, message=None),
        ]
        result = RuleEngineResult(action=RuleAction.WARN, warnings=warnings)

        assert result.warning_messages == ["Warning 1"]

    def test_warning_messages_empty_when_no_warnings(self):
        """Test warning_messages returns empty list when no warnings."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.warning_messages == []


class TestRuleEngineResultSummary:
    """Tests for get_summary() method."""

    def test_summary_includes_action(self):
        """Test summary includes action."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        summary = result.get_summary()
        assert "Action: allow" in summary

    def test_summary_includes_blocked_by(self):
        """Test summary includes blocked_by rule when blocked."""
        blocker = MockRule(rule_type="daily_limit")
        result = RuleEngineResult(
            action=RuleAction.BLOCK,
            blocked_by=blocker,
        )
        summary = result.get_summary()
        assert "Blocked by: daily_limit" in summary

    def test_summary_includes_warning_count(self):
        """Test summary includes warning count."""
        warnings = [
            RuleResult(action=RuleAction.WARN),
            RuleResult(action=RuleAction.WARN),
        ]
        result = RuleEngineResult(action=RuleAction.WARN, warnings=warnings)
        summary = result.get_summary()
        assert "Warnings: 2" in summary

    def test_summary_includes_rules_evaluated(self):
        """Test summary includes number of rules evaluated."""
        blocker = MockRule()
        all_results = [
            (blocker, RuleResult(action=RuleAction.ALLOW)),
            (blocker, RuleResult(action=RuleAction.ALLOW)),
            (blocker, RuleResult(action=RuleAction.BLOCK)),
        ]
        result = RuleEngineResult(
            action=RuleAction.BLOCK,
            all_results=all_results,
        )
        summary = result.get_summary()
        assert "Rules evaluated: 3" in summary

    def test_summary_includes_time(self):
        """Test summary includes evaluation time."""
        result = RuleEngineResult(
            action=RuleAction.ALLOW,
            evaluation_time_ms=12.345,
        )
        summary = result.get_summary()
        assert "Time: 12.35ms" in summary


class TestRuleEngineResultDefaults:
    """Tests for default values."""

    def test_blocked_by_defaults_to_none(self):
        """Test blocked_by defaults to None."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.blocked_by is None

    def test_blocking_reason_defaults_to_none(self):
        """Test blocking_reason defaults to None."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.blocking_reason is None

    def test_warnings_defaults_to_empty_list(self):
        """Test warnings defaults to empty list."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.warnings == []

    def test_all_results_defaults_to_empty_list(self):
        """Test all_results defaults to empty list."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.all_results == []

    def test_evaluation_time_defaults_to_zero(self):
        """Test evaluation_time_ms defaults to 0.0."""
        result = RuleEngineResult(action=RuleAction.ALLOW)
        assert result.evaluation_time_ms == 0.0
