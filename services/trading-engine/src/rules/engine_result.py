"""Rule Engine Result - Result of evaluating all rules in a RuleEngine.

This module provides the RuleEngineResult dataclass that aggregates
results from multiple rule evaluations.
"""

from dataclasses import dataclass, field

from .base_rule import BaseRule, RuleAction, RuleResult

# Type alias for rule evaluation tuple
RuleEvaluation = tuple[BaseRule, RuleResult]


@dataclass
class RuleEngineResult:
    """Result of evaluating all rules in a RuleEngine.

    Attributes:
        action: Final action (ALLOW, WARN, BLOCK).
        blocked_by: The rule that caused BLOCK, if any.
        blocking_reason: Human-readable reason for block.
        warnings: All WARN results collected.
        all_results: All rule evaluations for audit.
        evaluation_time_ms: Total evaluation time in milliseconds.
    """

    action: RuleAction
    blocked_by: BaseRule | None = None
    blocking_reason: str | None = None
    warnings: list[RuleResult] = field(default_factory=list)
    all_results: list[RuleEvaluation] = field(default_factory=list)
    evaluation_time_ms: float = 0.0

    @property
    def is_allowed(self) -> bool:
        """Check if trading is allowed (ALLOW or WARN)."""
        return self.action in (RuleAction.ALLOW, RuleAction.WARN)

    @property
    def is_blocked(self) -> bool:
        """Check if trading is blocked."""
        return self.action == RuleAction.BLOCK

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def warning_messages(self) -> list[str]:
        """Get list of warning messages for notifications."""
        return [w.message for w in self.warnings if w.message]

    def get_summary(self) -> str:
        """Get human-readable summary for logging.

        Returns:
            Summary string with action, warnings, and timing.
        """
        parts = [f"Action: {self.action.value}"]

        if self.blocked_by:
            parts.append(f"Blocked by: {self.blocked_by.rule_type}")

        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")

        parts.append(f"Rules evaluated: {len(self.all_results)}")
        parts.append(f"Time: {self.evaluation_time_ms:.2f}ms")

        return " | ".join(parts)
