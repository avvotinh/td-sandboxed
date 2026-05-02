"""Rule Engine - Evaluates multiple rules against a trading context.

This module provides the RuleEngine class that:
1. Maintains a sorted list of rules (by priority)
2. Evaluates all rules against a trading context
3. Aggregates results and determines final action
4. Implements fail-safe behavior (errors = BLOCK in strict mode)
"""

import logging
import time
from typing import Any

from .base_rule import BaseRule, RuleAction, RuleResult
from .engine_result import RuleEngineResult

logger = logging.getLogger(__name__)

# Type alias to reduce repetition
RuleList = list[BaseRule]


class RuleValidationError(Exception):
    """Raised when rule validation fails unexpectedly."""

    pass


class RuleEngine:
    """Engine that evaluates multiple rules against a trading context.

    The RuleEngine is the core component that:
    1. Maintains a sorted list of rules (by priority)
    2. Evaluates all rules against a trading context
    3. Aggregates results and determines final action
    4. Implements fail-safe behavior (errors = BLOCK)

    Attributes:
        account_id: The account this engine validates for.
        rules: Sorted list of rules (critical first).
        strict_mode: If True, any error = BLOCK (default: True).
    """

    def __init__(
        self,
        account_id: str,
        rules: RuleList,
        strict_mode: bool = True,
    ):
        """Initialize RuleEngine for an account.

        Args:
            account_id: Account identifier this engine belongs to.
            rules: List of rules to evaluate.
            strict_mode: If True, rule errors cause BLOCK.
        """
        self.account_id = account_id
        self.strict_mode = strict_mode

        # Sort rules by priority (lower = higher priority, evaluated first)
        # Python's sorted() is stable - equal priorities maintain insertion order
        self._rules = sorted(rules, key=lambda r: getattr(r, "priority", 50))

        logger.info(
            f"RuleEngine initialized for account '{account_id}' "
            f"with {len(self._rules)} rules"
        )

    def validate(
        self,
        context: dict[str, Any],
        continue_after_block: bool = False,
    ) -> RuleEngineResult:
        """Validate a trading context against all rules.

        NOTE: This method is intentionally SYNCHRONOUS for performance.
        Async operations should happen before (build context) or after (log results).

        Args:
            context: Trading context with account state and signal info.
            continue_after_block: If True, evaluate all rules even after BLOCK.

        Returns:
            RuleEngineResult with combined action and details.
        """
        start_time = time.perf_counter()
        all_results: list[tuple[BaseRule, RuleResult]] = []
        warnings: list[RuleResult] = []
        blocked_by: BaseRule | None = None
        blocking_reason: str | None = None

        for rule in self._rules:
            try:
                result = rule.validate(context)
                all_results.append((rule, result))

                # Log the validation result
                self._log_validation(rule, result)

                if result.action == RuleAction.WARN:
                    warnings.append(result)

                if result.action == RuleAction.BLOCK:
                    blocked_by = rule
                    blocking_reason = result.message or f"Blocked by {rule.rule_type}"

                    if not continue_after_block:
                        # Short-circuit: stop evaluating
                        logger.warning(
                            f"Rule evaluation stopped: {rule.name} blocked trade"
                        )
                        break

            except Exception as e:
                error_msg = f"Error in {rule.rule_type}: {e}"
                logger.exception(error_msg)

                if self.strict_mode:
                    # Fail-safe: error = BLOCK
                    error_result = RuleResult(
                        action=RuleAction.BLOCK,
                        message=error_msg,
                        metadata={"error": str(e), "rule_type": rule.rule_type},
                    )
                    all_results.append((rule, error_result))
                    blocked_by = rule
                    blocking_reason = error_msg
                    break

        evaluation_time_ms = (time.perf_counter() - start_time) * 1000

        # Determine final action
        if blocked_by is not None:
            final_action = RuleAction.BLOCK
        elif warnings:
            final_action = RuleAction.WARN
        else:
            final_action = RuleAction.ALLOW

        return RuleEngineResult(
            action=final_action,
            blocked_by=blocked_by,
            blocking_reason=blocking_reason,
            warnings=warnings,
            all_results=all_results,
            evaluation_time_ms=evaluation_time_ms,
        )

    def _log_validation(self, rule: BaseRule, result: RuleResult) -> None:
        """Log a rule validation result with appropriate level.

        Logging levels:
        - ALLOW results: debug (high volume, only for debugging)
        - WARN results: warning (important, but trade proceeds)
        - BLOCK results: warning (critical, trade stopped)

        Args:
            rule: The rule that was evaluated.
            result: The result of the evaluation.
        """
        rule_name = getattr(rule, "name", rule.rule_type)

        if result.action == RuleAction.ALLOW:
            logger.debug(f"Rule '{rule_name}' ALLOWED")
        elif result.action == RuleAction.WARN:
            logger.warning(f"Rule warning: {rule_name} - {result.message}")
        elif result.action == RuleAction.BLOCK:
            logger.warning(f"Rule BLOCKED trade: {rule_name} - {result.message}")

    def get_rules(self) -> RuleList:
        """Get the sorted list of rules.

        Returns:
            List of rules in priority order.
        """
        return self._rules.copy()

    @property
    def rule_count(self) -> int:
        """Number of rules in this engine."""
        return len(self._rules)
