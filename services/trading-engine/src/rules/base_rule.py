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
    """

    action: RuleAction = RuleAction.ALLOW
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

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
    - rule_type: A string identifier for the rule type
    - validate(): A method that checks a trading context and returns a result

    NOTE: Full rule implementations will be created in Epic 4. This protocol
    allows Story 3.7 to define the rule assignment infrastructure before
    the actual rule classes exist.

    Example:
        >>> class DailyLossLimitRule:
        ...     rule_type: str = "daily_loss_limit"
        ...     threshold_percent: float
        ...
        ...     def __init__(self, threshold_percent: float = 5.0, **kwargs):
        ...         self.threshold_percent = threshold_percent
        ...
        ...     def validate(self, context: dict[str, Any]) -> RuleResult:
        ...         # Check daily loss against threshold
        ...         daily_loss = context.get("daily_loss_percent", 0.0)
        ...         if daily_loss >= self.threshold_percent:
        ...             return RuleResult(
        ...                 action=RuleAction.BLOCK,
        ...                 message=f"Daily loss {daily_loss}% exceeds limit {self.threshold_percent}%"
        ...             )
        ...         return RuleResult(action=RuleAction.ALLOW)
    """

    rule_type: str
    """Identifier for the rule type (e.g., 'daily_loss_limit')."""

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate a trading context against this rule.

        Args:
            context: Dictionary containing trading context data such as:
                - daily_loss_percent: Current daily loss percentage
                - drawdown_percent: Current drawdown percentage
                - position_size: Requested position size
                - account_balance: Current account balance
                - etc.

        Returns:
            RuleResult indicating whether trading should proceed.
        """
        ...


# Type alias for a list of rules
RuleList = list[BaseRule]
