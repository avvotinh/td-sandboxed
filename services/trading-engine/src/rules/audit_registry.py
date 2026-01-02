"""Audit Logger Registry - Per-account audit logger management.

This module provides the AuditLoggerRegistry class that manages
AuditLogger instances on a per-account basis, following the same
pattern as PnLTrackerRegistry from Story 4.7.

Key design decisions:
- Lazy initialization: Loggers created on first use
- Thread-safe access: Single registry per engine instance
- Convenience methods: log_all() for easy integration
"""

import asyncio
import logging
from typing import Any

from redis.asyncio import Redis

from .audit_logger import AuditLogger, audit_task_done_callback
from .base_rule import BaseRule, RuleResult

logger = logging.getLogger(__name__)


class AuditLoggerRegistry:
    """Registry for per-account AuditLogger instances.

    The registry manages AuditLogger instances, creating them lazily
    on first access for each account. This follows the same pattern
    as PnLTrackerRegistry from Story 4.7.

    Attributes:
        redis_client: Shared Redis client for all loggers.

    Example:
        registry = AuditLoggerRegistry(redis_client)
        audit_logger = registry.get_or_create("ftmo-gold-001")
        await registry.log_all("ftmo-gold-001", rule, result, order_id, context)
    """

    def __init__(self, redis_client: Redis) -> None:
        """Initialize AuditLoggerRegistry.

        Args:
            redis_client: Async Redis client shared by all loggers.
        """
        self._redis = redis_client
        self._loggers: dict[str, AuditLogger] = {}

    def get_or_create(self, account_id: str) -> AuditLogger:
        """Get or create an AuditLogger for an account.

        Args:
            account_id: Account identifier.

        Returns:
            AuditLogger instance for the account.
        """
        if account_id not in self._loggers:
            self._loggers[account_id] = AuditLogger(self._redis, account_id)
            logger.debug("Created AuditLogger for account: %s", account_id)

        return self._loggers[account_id]

    async def log_all(
        self,
        account_id: str,
        rule: BaseRule,
        result: RuleResult,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Convenience method to log a rule check for an account.

        This method gets or creates the logger for the account and
        logs the rule check result. The actual Redis write is non-blocking.

        Args:
            account_id: Account identifier.
            rule: The rule that was evaluated.
            result: The result of the rule evaluation.
            order_id: ID of the order being validated (if any).
            context: Additional context (signal, symbol, size, etc.).
        """
        audit_logger = self.get_or_create(account_id)
        await audit_logger.log_rule_check(rule, result, order_id, context)

    def log_all_fire_and_forget(
        self,
        account_id: str,
        rule: BaseRule,
        result: RuleResult,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> asyncio.Task:
        """Log a rule check using fire-and-forget pattern.

        This method creates an asyncio task for the logging operation
        and attaches a done callback for error handling. The task is
        returned so the caller can track it if needed.

        Args:
            account_id: Account identifier.
            rule: The rule that was evaluated.
            result: The result of the rule evaluation.
            order_id: ID of the order being validated (if any).
            context: Additional context (signal, symbol, size, etc.).

        Returns:
            The asyncio Task for the logging operation.
        """
        task = asyncio.create_task(
            self.log_all(account_id, rule, result, order_id, context),
            name=f"audit_{account_id}_{rule.rule_type}",
        )
        task.add_done_callback(audit_task_done_callback)
        return task

    def get_logger(self, account_id: str) -> AuditLogger | None:
        """Get an existing AuditLogger for an account (without creating).

        Args:
            account_id: Account identifier.

        Returns:
            AuditLogger instance if it exists, None otherwise.
        """
        return self._loggers.get(account_id)

    def remove_logger(self, account_id: str) -> None:
        """Remove an AuditLogger for an account.

        This is useful for cleanup when an account is stopped.

        Args:
            account_id: Account identifier.
        """
        if account_id in self._loggers:
            del self._loggers[account_id]
            logger.debug("Removed AuditLogger for account: %s", account_id)

    @property
    def account_count(self) -> int:
        """Number of accounts with active loggers."""
        return len(self._loggers)

    @property
    def account_ids(self) -> list[str]:
        """List of account IDs with active loggers."""
        return list(self._loggers.keys())
