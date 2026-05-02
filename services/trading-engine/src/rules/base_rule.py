"""Base rule protocol and placeholder types for rule assignment.

This module provides the foundational protocol and types for the rule system.
The BaseRule protocol defines the interface that all rules must implement.

NOTE: This is a placeholder for Epic 4. The full rule implementation with
concrete rule classes (DailyLossLimitRule, MaxDrawdownRule, etc.) will be
implemented in Epic 4 (FTMO Compliance Rule Engine).

Example:
    >>> class MyRule:
    ...     rule_type = "my_rule"
    ...     def validate(self, context: dict) -> RuleResult:
    ...         return RuleResult(action=RuleAction.ALLOW)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class RuleAction(str, Enum):
    """Actions that a rule can return after validation.

    Attributes:
        ALLOW: Trade is allowed to proceed.
        WARN: Trade is allowed but a warning should be issued.
        BLOCK: Trade should be blocked.
    """

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class RuleResult:
    """Result of a rule validation check.

    Attributes:
        action: Action to take (allow, warn, block).
        message: Optional message explaining the result.
        metadata: Optional additional data about the validation.
        current_value: Current value of the metric being checked (Story 4.1).
        threshold_value: Threshold value that triggered the result (Story 4.1).
    """

    action: RuleAction = RuleAction.ALLOW
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # NEW optional fields (Story 4.1) - defaults maintain backward compatibility
    current_value: float | None = None
    threshold_value: float | None = None

    @property
    def is_allowed(self) -> bool:
        """Check if the action allows trading."""
        return self.action in (RuleAction.ALLOW, RuleAction.WARN)

    @property
    def is_blocked(self) -> bool:
        """Check if the action blocks trading."""
        return self.action == RuleAction.BLOCK


@runtime_checkable
class BaseRule(Protocol):
    """Protocol defining the interface for all trading rules.

    All rule implementations must satisfy this protocol by providing:
    - rule_type: String identifier for the rule type
    - name: Human-readable rule name
    - priority: Integer priority (lower = evaluated first)
    - validate(): Check context and return result
    - get_current_value(): Get current metric value
    - get_threshold(): Get configured threshold
    - get_warning_thresholds(): Get warning percentage thresholds

    Example:
        >>> class DailyLossLimitRule:
        ...     rule_type: str = "daily_loss_limit"
        ...     name: str = "Daily Loss Limit 5%"
        ...     priority: int = 1  # Critical rule, evaluated first
        ...     threshold_percent: float
        ...
        ...     def __init__(self, threshold_percent: float = 5.0, **kwargs):
        ...         self.threshold_percent = threshold_percent
        ...
        ...     def validate(self, context: dict[str, Any]) -> RuleResult:
        ...         daily_loss = context.get("daily_loss_percent", 0.0)
        ...         if daily_loss >= self.threshold_percent:
        ...             return RuleResult(
        ...                 action=RuleAction.BLOCK,
        ...                 message=f"Daily loss {daily_loss}% exceeds limit",
        ...                 current_value=daily_loss,
        ...                 threshold_value=self.threshold_percent,
        ...             )
        ...         return RuleResult(action=RuleAction.ALLOW)
        ...
        ...     def get_current_value(self, context: dict[str, Any]) -> float:
        ...         return context.get("daily_loss_percent", 0.0)
        ...
        ...     def get_threshold(self) -> float:
        ...         return self.threshold_percent
        ...
        ...     def get_warning_thresholds(self) -> list[float]:
        ...         return [70.0, 80.0, 90.0]  # Warn at 70%, 80%, 90% of limit
    """

    rule_type: str
    """Identifier for the rule type (e.g., 'daily_loss_limit')."""

    name: str
    """Human-readable name (e.g., 'Daily Loss Limit 5%').

    This is a required attribute with no default value. Each rule implementation
    should provide a descriptive name that includes configuration details
    (e.g., 'Daily Loss Limit 5%' rather than just 'Daily Loss Limit').
    """

    priority: int
    """Evaluation priority (lower = evaluated first, default: 50)."""

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate a trading context against this rule.

        Args:
            context: Dictionary containing trading context data such as:
                - account_id: Account identifier
                - current_balance: Current account balance
                - current_equity: Current account equity
                - daily_pnl_percent: Current daily P&L percentage
                - total_drawdown_percent: Current drawdown percentage
                - symbol: Trading symbol
                - side: Trade side (buy/sell)
                - quantity: Trade quantity

        Returns:
            RuleResult indicating whether trading should proceed.
        """
        ...

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get the current value of the metric this rule monitors.

        Args:
            context: Trading context with current state.

        Returns:
            Current value (e.g., current daily loss percent).
        """
        ...

    def get_threshold(self) -> float:
        """Get the threshold value for this rule.

        Returns:
            Threshold value (e.g., 5.0 for 5% daily loss limit).
        """
        ...

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [70.0, 80.0, 90.0]).
        """
        ...


# Type alias for a list of rules
RuleList = list[BaseRule]
