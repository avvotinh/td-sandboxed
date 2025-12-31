"""Order Validator - Pre-trade validation against compliance rules.

This module provides the OrderValidator class that validates orders
against configured rules BEFORE they are sent to MT5 for execution.

Key design decisions:
- RuleEngine.validate() is SYNCHRONOUS for performance
- OrderValidator.validate_order() is ASYNC only for notification publishing
- Fail-safe behavior: any error = BLOCK trade
- Performance target: < 50ms total validation time
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from ..adapters.zmq_models import Order
from ..rules.context_builder import RuleContextBuilder
from ..rules.engine import RuleEngine, RuleValidationError

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of pre-trade validation.

    Attributes:
        allowed: Whether the trade is allowed to proceed.
        reason: Explanation for why the trade was blocked (if blocked).
        warnings: List of warning messages (if any).
        evaluation_time_ms: Time taken for validation in milliseconds.
        blocked_by_rule: Name of the rule that blocked the trade (if any).
        current_value: Current metric value that triggered block/warn.
        threshold_value: Threshold value that was exceeded.
    """

    allowed: bool
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    evaluation_time_ms: float = 0.0
    blocked_by_rule: str | None = None
    current_value: float | None = None
    threshold_value: float | None = None

    @property
    def is_blocked(self) -> bool:
        """Check if the trade is blocked."""
        return not self.allowed

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging.

        Returns:
            Dictionary representation for logging.
        """
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "warnings": self.warnings,
            "evaluation_time_ms": round(self.evaluation_time_ms, 3),
            "blocked_by_rule": self.blocked_by_rule,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
        }


class OrderValidator:
    """Validates orders against compliance rules before execution.

    The OrderValidator is the integration point between the rule engine
    and the execution flow. It:
    1. Builds validation context from order and account state
    2. Calls RuleEngine.validate() (synchronous for performance)
    3. Maps RuleEngineResult to ValidationResult
    4. Publishes notifications to Redis for blocked/warning trades
    5. Implements fail-safe behavior (errors = BLOCK)

    Attributes:
        rule_engine: The RuleEngine instance to validate against.
        redis_client: Redis client for notification publishing.

    Example:
        validator = OrderValidator(rule_engine, redis_client)
        result = await validator.validate_order(order, account_state)
        if result.is_blocked:
            print(f"Trade blocked: {result.reason}")
    """

    # Performance thresholds
    WARN_THRESHOLD_MS = 25.0
    ERROR_THRESHOLD_MS = 50.0

    def __init__(
        self,
        rule_engine: RuleEngine,
        redis_client: Redis,
    ) -> None:
        """Initialize OrderValidator.

        Args:
            rule_engine: RuleEngine instance for rule validation.
            redis_client: Redis client for notification publishing.
        """
        self._rule_engine = rule_engine
        self._redis = redis_client
        self._context_builder = RuleContextBuilder()

    async def validate_order(
        self,
        order: Order,
        account_state: dict[str, Any],
    ) -> ValidationResult:
        """Validate an order against all configured rules.

        This method:
        1. Builds validation context from order and account state
        2. Calls RuleEngine.validate() (synchronous)
        3. Maps result to ValidationResult
        4. Publishes notifications for blocked/warning trades
        5. Handles errors with fail-safe (error = BLOCK)

        Args:
            order: The order to validate.
            account_state: Current account state (balance, equity, etc.).

        Returns:
            ValidationResult indicating whether the trade is allowed.

        Note:
            This method NEVER raises exceptions - all errors are caught
            and converted to BLOCK results (fail-safe behavior).
        """
        start_time = time.perf_counter()

        try:
            # Build validation context using RuleContextBuilder
            # Order duck-types as signal (has symbol, action, volume)
            context = self._context_builder.build_validation_context(
                account_id=order.account_id,
                signal=order,
                account_state=account_state,
            )

            # Validate against rules (synchronous for performance)
            engine_result = self._rule_engine.validate(context)

            evaluation_time_ms = (time.perf_counter() - start_time) * 1000

            # Log performance warnings
            self._log_performance(evaluation_time_ms)

            # Map RuleEngineResult to ValidationResult
            if engine_result.is_blocked:
                # Extract current/threshold values from blocking rule result
                blocking_result = next(
                    (
                        result
                        for rule, result in engine_result.all_results
                        if rule == engine_result.blocked_by
                    ),
                    None,
                )

                result = ValidationResult(
                    allowed=False,
                    reason=engine_result.blocking_reason,
                    blocked_by_rule=(
                        engine_result.blocked_by.name
                        if engine_result.blocked_by
                        else "unknown"
                    ),
                    evaluation_time_ms=evaluation_time_ms,
                    current_value=(
                        blocking_result.current_value if blocking_result else None
                    ),
                    threshold_value=(
                        blocking_result.threshold_value if blocking_result else None
                    ),
                )

                # Publish BLOCK notification (fire-and-forget)
                task = asyncio.create_task(
                    self._publish_block_notification(order, result),
                    name=f"notify_block_{order.order_id}",
                )
                task.add_done_callback(self._notification_task_done)

                logger.warning(
                    "Order blocked: %s - Rule: %s - Reason: %s",
                    order.order_id,
                    result.blocked_by_rule,
                    result.reason,
                )

            elif engine_result.has_warnings:
                result = ValidationResult(
                    allowed=True,
                    warnings=engine_result.warning_messages,
                    evaluation_time_ms=evaluation_time_ms,
                )

                # Publish WARN notification (fire-and-forget)
                task = asyncio.create_task(
                    self._publish_warn_notification(order, result),
                    name=f"notify_warn_{order.order_id}",
                )
                task.add_done_callback(self._notification_task_done)

                logger.info(
                    "Order allowed with warnings: %s - Warnings: %s",
                    order.order_id,
                    result.warnings,
                )

            else:
                result = ValidationResult(
                    allowed=True,
                    evaluation_time_ms=evaluation_time_ms,
                )

                logger.debug(
                    "Order validated successfully: %s in %.2fms",
                    order.order_id,
                    evaluation_time_ms,
                )

            return result

        except KeyError as e:
            # Missing context field - fail-safe BLOCK
            evaluation_time_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"Missing context field: {e}"
            logger.exception("Validation failed - missing field: %s", e)

            return ValidationResult(
                allowed=False,
                reason=error_msg,
                blocked_by_rule="error",
                evaluation_time_ms=evaluation_time_ms,
            )

        except TypeError as e:
            # Invalid context value - fail-safe BLOCK
            evaluation_time_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"Invalid context value: {e}"
            logger.exception("Validation failed - type error: %s", e)

            return ValidationResult(
                allowed=False,
                reason=error_msg,
                blocked_by_rule="error",
                evaluation_time_ms=evaluation_time_ms,
            )

        except RuleValidationError as e:
            # Rule validation error - fail-safe BLOCK
            evaluation_time_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"Rule validation error: {e}"
            logger.exception("Validation failed - rule error: %s", e)

            return ValidationResult(
                allowed=False,
                reason=error_msg,
                blocked_by_rule="error",
                evaluation_time_ms=evaluation_time_ms,
            )

        except Exception as e:
            # Any other error - fail-safe BLOCK
            evaluation_time_ms = (time.perf_counter() - start_time) * 1000
            error_msg = f"Validation error: {e}"
            logger.exception("Validation failed unexpectedly: %s", e)

            return ValidationResult(
                allowed=False,
                reason=error_msg,
                blocked_by_rule="error",
                evaluation_time_ms=evaluation_time_ms,
            )

    def _log_performance(self, evaluation_time_ms: float) -> None:
        """Log performance warnings if thresholds exceeded.

        Args:
            evaluation_time_ms: Time taken for validation.
        """
        if evaluation_time_ms >= self.ERROR_THRESHOLD_MS:
            logger.error(
                "Validation exceeded error threshold: %.2fms (limit: %.2fms)",
                evaluation_time_ms,
                self.ERROR_THRESHOLD_MS,
            )
        elif evaluation_time_ms >= self.WARN_THRESHOLD_MS:
            logger.warning(
                "Validation exceeded warning threshold: %.2fms (warn: %.2fms)",
                evaluation_time_ms,
                self.WARN_THRESHOLD_MS,
            )

    def _notification_task_done(self, task: asyncio.Task) -> None:
        """Callback for notification tasks to log any unhandled exceptions.

        This is called when a fire-and-forget notification task completes.
        It logs any exceptions that occurred without affecting validation.

        Args:
            task: The completed task.
        """
        if task.cancelled():
            logger.debug("Notification task %s was cancelled", task.get_name())
            return

        exception = task.exception()
        if exception is not None:
            logger.warning(
                "Notification task %s failed: %s",
                task.get_name(),
                exception,
            )

    async def _publish_block_notification(
        self,
        order: Order,
        result: ValidationResult,
    ) -> None:
        """Publish BLOCK notification to Redis for Go notification service.

        This is fire-and-forget - notification failures don't affect validation.

        Args:
            order: The blocked order.
            result: The validation result with block details.
        """
        try:
            channel = f"alerts:risk:{order.account_id}"
            message = {
                "type": "rule_block",
                "account_id": order.account_id,
                "rule_name": result.blocked_by_rule,
                "reason": result.reason,
                "current_value": result.current_value,
                "threshold_value": result.threshold_value,
                "order": {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "action": order.action.value,
                    "volume": order.volume,
                    "price": order.price,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self._redis.publish(channel, json.dumps(message))
            logger.debug("Published BLOCK notification to %s", channel)

        except Exception as e:
            # Log but don't fail - notification is fire-and-forget
            logger.warning(
                "Failed to publish BLOCK notification for %s: %s",
                order.order_id,
                e,
            )

    async def _publish_warn_notification(
        self,
        order: Order,
        result: ValidationResult,
    ) -> None:
        """Publish WARN notification to Redis for Go notification service.

        This is fire-and-forget - notification failures don't affect validation.

        Args:
            order: The order with warnings.
            result: The validation result with warning details.
        """
        try:
            channel = f"alerts:risk:{order.account_id}"
            message = {
                "type": "rule_warning",
                "account_id": order.account_id,
                "warnings": result.warnings,
                "order": {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "action": order.action.value,
                    "volume": order.volume,
                    "price": order.price,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            await self._redis.publish(channel, json.dumps(message))
            logger.debug("Published WARN notification to %s", channel)

        except Exception as e:
            # Log but don't fail - notification is fire-and-forget
            logger.warning(
                "Failed to publish WARN notification for %s: %s",
                order.order_id,
                e,
            )
