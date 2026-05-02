"""Rule Engine Factory - Creates RuleEngine instances for accounts.

This module provides the RuleEngineFactory class that validates rules
and creates account-specific RuleEngine instances.
"""

import logging

from .base_rule import BaseRule
from .engine import RuleEngine

logger = logging.getLogger(__name__)


class RuleEngineFactory:
    """Factory for creating RuleEngine instances.

    The factory:
    1. Validates that all rules implement the BaseRule protocol
    2. Creates account-specific RuleEngine instances
    3. Logs engine creation for auditing
    """

    @staticmethod
    def create_for_account(
        account_id: str,
        rules: list[BaseRule],
        strict_mode: bool = True,
    ) -> RuleEngine:
        """Create a RuleEngine for a specific account.

        Args:
            account_id: Account identifier.
            rules: List of rules to include in the engine.
            strict_mode: If True, rule errors cause BLOCK (default: True).

        Returns:
            RuleEngine configured for the account.

        Raises:
            TypeError: If any rule doesn't implement BaseRule protocol.
        """
        # Validate all rules implement BaseRule protocol
        for i, rule in enumerate(rules):
            if not isinstance(rule, BaseRule):
                raise TypeError(
                    f"Rule at index {i} does not implement BaseRule protocol: "
                    f"{type(rule).__name__}"
                )

            # Check for required attributes (defensive - isinstance should catch these)
            if not hasattr(rule, "rule_type"):
                raise TypeError(
                    f"Rule at index {i} missing 'rule_type' attribute: "
                    f"{type(rule).__name__}"
                )

        engine = RuleEngine(
            account_id=account_id,
            rules=rules,
            strict_mode=strict_mode,
        )

        logger.info(
            f"Created RuleEngine for account {account_id} with {len(rules)} rules"
        )

        return engine
