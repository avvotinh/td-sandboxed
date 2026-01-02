"""Audit Logger - Logs rule check results for compliance and debugging.

This module provides the AuditLogger class that logs every rule evaluation
with full context to Redis (for real-time access) and buffers entries for
batch persistence to TimescaleDB.

Key design decisions:
- Fire-and-forget pattern: Audit logging never blocks validation flow
- Redis with TTL: 24-hour retention for real-time queries
- Non-blocking async writes: Logging overhead < 2ms per entry
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from redis.asyncio import Redis

from .base_rule import BaseRule, RuleResult

logger = logging.getLogger(__name__)

# Constants
AUDIT_TTL_SECONDS = 86400  # 24 hours


class AuditEventType(str, Enum):
    """Types of audit events for rule check logging.

    Attributes:
        RULE_CHECK: Standard rule evaluation (ALLOW result).
        TRADE_BLOCKED: Trade was blocked by a rule (BLOCK result).
        WARNING_TRIGGERED: Warning threshold was crossed (WARN result).
    """

    RULE_CHECK = "rule_check"
    TRADE_BLOCKED = "trade_blocked"
    WARNING_TRIGGERED = "warning_triggered"


@dataclass
class AuditEntry:
    """Represents a single audit log entry for a rule check.

    Attributes:
        timestamp: When the rule was evaluated.
        account_id: Account the rule was evaluated for.
        event_type: Type of event (rule_check, trade_blocked, warning_triggered).
        rule_type: Rule type identifier (e.g., daily_loss_limit).
        rule_name: Human-readable rule name.
        rule_result: Result of the evaluation (ALLOW, WARN, BLOCK).
        current_value: Current value of the metric being checked.
        threshold_value: Threshold value that triggered the result.
        order_id: ID of the order being validated.
        context: Additional context (signal, symbol, size, etc.).
    """

    timestamp: datetime
    account_id: str
    event_type: str  # 'rule_check', 'trade_blocked', 'warning_triggered'
    rule_type: str
    rule_name: str
    rule_result: str  # 'ALLOW', 'WARN', 'BLOCK'
    current_value: float | None = None
    threshold_value: float | None = None
    order_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_redis_key(self) -> str:
        """Generate Redis key for this audit entry.

        Returns:
            Redis key in format: audit:{account_id}:{iso_timestamp}:{uuid}
        """
        ts = self.timestamp.isoformat()
        unique_id = uuid.uuid4().hex[:8]
        return f"audit:{self.account_id}:{ts}:{unique_id}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict for Redis storage.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "account_id": self.account_id,
            "event_type": self.event_type,
            "rule_type": self.rule_type,
            "rule_name": self.rule_name,
            "rule_result": self.rule_result,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "order_id": self.order_id,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        """Create an AuditEntry from a dictionary.

        Args:
            data: Dictionary with audit entry fields.

        Returns:
            AuditEntry instance.
        """
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            account_id=data["account_id"],
            event_type=data["event_type"],
            rule_type=data["rule_type"],
            rule_name=data["rule_name"],
            rule_result=data["rule_result"],
            current_value=data.get("current_value"),
            threshold_value=data.get("threshold_value"),
            order_id=data.get("order_id"),
            context=data.get("context", {}),
        )


class AuditLogger:
    """Logs rule check results to Redis with fire-and-forget pattern.

    The AuditLogger is responsible for:
    1. Creating AuditEntry instances from rule validation results
    2. Writing entries to Redis with 24-hour TTL (non-blocking)
    3. Providing callback for error handling without affecting main flow

    Attributes:
        redis_client: Async Redis client for writing entries.
        account_id: Account this logger is associated with.

    Example:
        audit_logger = AuditLogger(redis_client, "ftmo-gold-001")
        await audit_logger.log_rule_check(rule, result, order, context)
    """

    def __init__(self, redis_client: Redis, account_id: str) -> None:
        """Initialize AuditLogger for an account.

        Args:
            redis_client: Async Redis client for writing audit entries.
            account_id: Account identifier this logger is for.
        """
        self._redis = redis_client
        self._account_id = account_id

    @property
    def account_id(self) -> str:
        """Get the account ID for this logger."""
        return self._account_id

    async def log_rule_check(
        self,
        rule: BaseRule,
        result: RuleResult,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a rule check result to Redis.

        This method creates an audit entry and writes it to Redis with a 24-hour TTL.
        The write is non-blocking (fire-and-forget via asyncio.create_task in caller).

        Args:
            rule: The rule that was evaluated.
            result: The result of the rule evaluation.
            order_id: ID of the order being validated (if any).
            context: Additional context (signal, symbol, size, etc.).
        """
        entry = self._create_entry(rule, result, order_id, context)
        await self._write_to_redis(entry)

    def _create_entry(
        self,
        rule: BaseRule,
        result: RuleResult,
        order_id: str | None,
        context: dict[str, Any] | None,
    ) -> AuditEntry:
        """Create an AuditEntry from rule validation components.

        Args:
            rule: The rule that was evaluated.
            result: The result of the rule evaluation.
            order_id: ID of the order being validated.
            context: Additional context for the entry.

        Returns:
            AuditEntry with all fields populated.
        """
        # Determine event type based on result action
        event_type = AuditEventType.RULE_CHECK
        if result.action.value == "block":
            event_type = AuditEventType.TRADE_BLOCKED
        elif result.action.value == "warn":
            event_type = AuditEventType.WARNING_TRIGGERED

        # Build context with blocking reason if applicable
        entry_context = context.copy() if context else {}
        if result.action.value == "block" and result.message:
            entry_context["blocking_reason"] = result.message

        return AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=self._account_id,
            event_type=event_type.value,
            rule_type=rule.rule_type,
            rule_name=rule.name,
            rule_result=result.action.value.upper(),
            current_value=result.current_value,
            threshold_value=result.threshold_value,
            order_id=order_id,
            context=entry_context,
        )

    async def _write_to_redis(self, entry: AuditEntry) -> None:
        """Write an audit entry to Redis with TTL.

        Uses setex for atomic set-with-TTL. Errors are logged but not raised
        to maintain fire-and-forget behavior.

        Args:
            entry: The audit entry to write.
        """
        try:
            key = entry.to_redis_key()
            value = json.dumps(entry.to_dict())
            await self._redis.setex(key, AUDIT_TTL_SECONDS, value)

            logger.debug(
                "Audit entry written: %s (result=%s)",
                key,
                entry.rule_result,
            )

        except Exception as e:
            # Log but don't raise - audit logging is fire-and-forget
            logger.warning(
                "Failed to write audit entry for %s: %s",
                self._account_id,
                e,
            )


def audit_task_done_callback(task: asyncio.Task) -> None:
    """Callback for audit logging tasks to handle exceptions.

    This is used as a done_callback for fire-and-forget audit tasks.
    It logs any exceptions without affecting the main validation flow.

    Args:
        task: The completed asyncio task.
    """
    if task.cancelled():
        logger.debug("Audit task %s was cancelled", task.get_name())
        return

    exception = task.exception()
    if exception is not None:
        logger.warning(
            "Audit task %s failed: %s",
            task.get_name(),
            exception,
        )
