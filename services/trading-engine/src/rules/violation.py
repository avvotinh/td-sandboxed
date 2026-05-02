"""Rule Violation data model for tracking violations in TimescaleDB."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .base_rule import BaseRule, RuleAction, RuleResult

ACTION_MAP = {
    RuleAction.BLOCK: "blocked",
    RuleAction.WARN: "warned",
    RuleAction.ALLOW: "logged",
}


@dataclass
class RuleViolation:
    """Represents a rule violation for persistence to TimescaleDB.

    Maps to the rule_violations hypertable (17 columns in init.sql).
    """

    account_id: str
    timestamp: datetime
    rule_type: str
    rule_name: str
    severity: str  # INFO, WARNING, CRITICAL, FATAL
    action_taken: str  # blocked, warned, notified, logged
    current_value: float | None = None
    threshold_value: float | None = None
    threshold_percent: float | None = None
    trade_id: str | None = None
    order_blocked: bool = False
    message: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: datetime | None = None

    @classmethod
    def from_rule_result(
        cls,
        rule: BaseRule,
        result: RuleResult,
        account_id: str,
        trade_id: str | None = None,
        signal_context: dict[str, Any] | None = None,
    ) -> "RuleViolation":
        """Create a RuleViolation from an existing rule check result.

        Args:
            rule: The rule that triggered the violation.
            result: The rule's validation result (BLOCK or WARN).
            account_id: Account that was evaluated.
            trade_id: UUID of trade if it proceeded (WARN), None if blocked.
            signal_context: Additional context about the signal/order.
        """
        is_block = result.action == RuleAction.BLOCK

        # Calculate threshold percentage
        threshold_pct = None
        if result.current_value is not None and result.threshold_value is not None:
            if result.threshold_value != 0:
                threshold_pct = (result.current_value / result.threshold_value) * 100

        # Determine severity
        if is_block:
            severity = "FATAL"
        elif threshold_pct is not None:
            if threshold_pct >= 90:
                severity = "CRITICAL"
            elif threshold_pct >= 80:
                severity = "WARNING"
            else:
                severity = "INFO"
        else:
            severity = "WARNING"

        # Build context
        ctx: dict[str, Any] = {}
        if signal_context:
            ctx.update(signal_context)
        if result.metadata:
            ctx["rule_metadata"] = result.metadata

        return cls(
            account_id=account_id,
            timestamp=datetime.now(timezone.utc),
            rule_type=rule.rule_type,
            rule_name=rule.name,
            severity=severity,
            action_taken=ACTION_MAP.get(result.action, "logged"),
            current_value=result.current_value,
            threshold_value=result.threshold_value,
            threshold_percent=threshold_pct,
            trade_id=trade_id,
            order_blocked=is_block,
            message=result.message,
            context=ctx,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "rule_type": self.rule_type,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "action_taken": self.action_taken,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "threshold_percent": self.threshold_percent,
            "trade_id": self.trade_id,
            "order_blocked": self.order_blocked,
            "message": self.message,
            "context": self.context,
            "acknowledged": self.acknowledged,
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
        }
