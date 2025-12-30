"""Rule parser for YAML rule configurations.

This module parses YAML rule definitions into instantiated rule objects.
It supports all rule types defined in the rule engine with lazy imports
to defer Epic 4 dependencies until actually needed.

Example YAML structure:
    name: "My Rules"
    version: "1.0"
    rules:
      - type: daily_loss_limit
        threshold_percent: 5.0
        action: block_trading
      - type: max_drawdown
        threshold_percent: 10.0

Example usage:
    >>> parser = RuleParser()
    >>> rules = parser.parse_rules(yaml_content)
    >>> len(rules)
    2
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class RuleParseError(Exception):
    """Raised when rule parsing fails.

    This exception provides detailed information about what went wrong
    during parsing, including the index and field that caused the error.

    Attributes:
        message: Error description.
        index: Index of the rule that failed (if applicable).
        field: Field that caused the error (if applicable).
    """

    def __init__(
        self,
        message: str,
        index: int | None = None,
        field: str | None = None,
    ):
        """Initialize RuleParseError.

        Args:
            message: Error description.
            index: Index of the rule that failed.
            field: Field that caused the error.
        """
        self.message = message
        self.index = index
        self.field = field

        # Build full message
        parts = []
        if index is not None:
            parts.append(f"rule[{index}]")
        if field is not None:
            parts.append(f"field '{field}'")
        if parts:
            full_message = f"{' '.join(parts)}: {message}"
        else:
            full_message = message

        super().__init__(full_message)


class RuleParser:
    """Parser for rule YAML configurations.

    Converts YAML rule definitions to instantiated rule objects.
    Supports all rule types defined in the rule engine.

    NOTE: Rule type classes are imported lazily from Epic 4.
    Until Epic 4 is implemented, this parser will use placeholder
    rule classes that satisfy the BaseRule protocol.

    Attributes:
        RULE_TYPES: Registry mapping YAML type to rule class (lazy-loaded).
    """

    _rule_types: dict[str, type] | None = None
    _placeholders_created: bool = False

    @property
    def RULE_TYPES(self) -> dict[str, type]:
        """Registry mapping YAML type to rule class.

        Lazy-loaded to defer Epic 4 imports until actually needed.
        Returns placeholder classes if Epic 4 rule classes don't exist yet.

        Returns:
            Dictionary mapping rule type strings to rule classes.
        """
        if self._rule_types is not None:
            return self._rule_types

        try:
            # These imports will work once Epic 4 is implemented
            from .types.drawdown import DailyLossLimitRule, MaxDrawdownRule
            from .types.position import MaxPositionSizeRule
            from .types.targets import MinTradingDaysRule, ProfitTargetRule

            self._rule_types = {
                "daily_loss_limit": DailyLossLimitRule,
                "max_drawdown": MaxDrawdownRule,
                "max_position_size": MaxPositionSizeRule,
                "profit_target": ProfitTargetRule,
                "min_trading_days": MinTradingDaysRule,
            }
            logger.debug("Loaded Epic 4 rule types")
        except ImportError:
            # Epic 4 not implemented yet - create placeholder classes
            if not self._placeholders_created:
                logger.info(
                    "Epic 4 rule types not found - using placeholder classes. "
                    "Full rule implementations will be available in Epic 4."
                )
                self._placeholders_created = True

            self._rule_types = self._create_placeholder_types()

        return self._rule_types

    def _create_placeholder_types(self) -> dict[str, type]:
        """Create placeholder rule classes for pre-Epic 4 operation.

        Returns:
            Dictionary of placeholder rule classes.
        """
        from .base_rule import RuleAction, RuleResult

        def make_placeholder(rule_type_name: str) -> type:
            """Create a placeholder rule class."""

            class PlaceholderRule:
                """Placeholder rule - full implementation in Epic 4."""

                rule_type: str = rule_type_name

                def __init__(self, **kwargs: Any):
                    """Store all kwargs as attributes."""
                    for key, value in kwargs.items():
                        setattr(self, key, value)

                def validate(self, context: dict[str, Any]) -> RuleResult:
                    """Placeholder validation - always allows."""
                    return RuleResult(
                        action=RuleAction.ALLOW,
                        message=f"Placeholder rule {rule_type_name} - Epic 4 not implemented",
                    )

                def __repr__(self) -> str:
                    attrs = ", ".join(f"{k}={v}" for k, v in self.__dict__.items())
                    return f"<PlaceholderRule({rule_type_name}) {attrs}>"

            PlaceholderRule.__name__ = f"Placeholder{rule_type_name.title().replace('_', '')}Rule"
            return PlaceholderRule

        return {
            "daily_loss_limit": make_placeholder("daily_loss_limit"),
            "max_drawdown": make_placeholder("max_drawdown"),
            "max_position_size": make_placeholder("max_position_size"),
            "profit_target": make_placeholder("profit_target"),
            "min_trading_days": make_placeholder("min_trading_days"),
        }

    def parse_rules(self, yaml_content: dict[str, Any]) -> list["BaseRule"]:
        """Parse rules from YAML content.

        Args:
            yaml_content: Parsed YAML dictionary with 'rules' key.
                Expected structure:
                {
                    "name": "Rule Set Name",
                    "version": "1.0",
                    "rules": [
                        {"type": "daily_loss_limit", "threshold_percent": 5.0},
                        {"type": "max_drawdown", "threshold_percent": 10.0},
                    ]
                }

        Returns:
            List of instantiated rule objects.

        Raises:
            RuleParseError: If parsing fails due to missing keys or invalid types.
        """
        if "rules" not in yaml_content:
            raise RuleParseError("YAML must contain 'rules' key")

        rules_list = yaml_content["rules"]

        if not isinstance(rules_list, list):
            raise RuleParseError("'rules' must be a list")

        rules: list["BaseRule"] = []
        for idx, rule_def in enumerate(rules_list):
            try:
                rule = self._parse_single_rule(rule_def, idx)
                rules.append(rule)
            except RuleParseError:
                # Re-raise as-is (already has index info)
                raise
            except Exception as e:
                raise RuleParseError(str(e), index=idx) from e

        return rules

    def _parse_single_rule(
        self,
        rule_def: dict[str, Any],
        index: int,
    ) -> "BaseRule":
        """Parse a single rule definition.

        Args:
            rule_def: Dictionary with rule definition.
            index: Index of the rule in the list (for error messages).

        Returns:
            Instantiated rule object.

        Raises:
            RuleParseError: If rule definition is invalid.
        """
        if not isinstance(rule_def, dict):
            raise RuleParseError(
                "Rule definition must be a dictionary",
                index=index,
            )

        if "type" not in rule_def:
            raise RuleParseError(
                "Rule must have 'type' field",
                index=index,
                field="type",
            )

        rule_type = rule_def["type"]

        if not isinstance(rule_type, str):
            raise RuleParseError(
                f"'type' must be a string, got {type(rule_type).__name__}",
                index=index,
                field="type",
            )

        if rule_type not in self.RULE_TYPES:
            available = ", ".join(sorted(self.RULE_TYPES.keys()))
            raise RuleParseError(
                f"Unknown rule type '{rule_type}'. Available types: {available}",
                index=index,
                field="type",
            )

        # Get rule class and remaining kwargs
        rule_class = self.RULE_TYPES[rule_type]
        kwargs = {k: v for k, v in rule_def.items() if k != "type"}

        # Instantiate rule
        try:
            return rule_class(**kwargs)
        except TypeError as e:
            raise RuleParseError(
                f"Invalid parameters for {rule_type}: {e}",
                index=index,
            ) from e

    def get_available_types(self) -> list[str]:
        """Get list of available rule types.

        Returns:
            List of rule type names.
        """
        return list(self.RULE_TYPES.keys())
