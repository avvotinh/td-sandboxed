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
        Returns placeholder classes for rule types that don't exist yet.

        Returns:
            Dictionary mapping rule type strings to rule classes.
        """
        if self._rule_types is not None:
            return self._rule_types

        # Start with placeholder types for all rules
        self._rule_types = self._create_placeholder_types()

        # Try to import each implemented rule type individually
        # This allows partial Epic 4 implementation (e.g., Story 4.2 adds DailyLossLimitRule)
        try:
            from .types.drawdown import DailyLossLimitRule

            self._rule_types["daily_loss_limit"] = DailyLossLimitRule
            logger.debug("Loaded DailyLossLimitRule")
        except ImportError:
            pass

        try:
            from .types.drawdown import MaxDrawdownRule

            self._rule_types["max_drawdown"] = MaxDrawdownRule
            logger.debug("Loaded MaxDrawdownRule")
        except ImportError:
            pass

        try:
            from .types.position import MaxPositionSizeRule

            self._rule_types["max_position_size"] = MaxPositionSizeRule
            logger.debug("Loaded MaxPositionSizeRule")
        except ImportError:
            pass

        try:
            from .types.targets import ProfitTargetRule

            self._rule_types["profit_target"] = ProfitTargetRule
            logger.debug("Loaded ProfitTargetRule")
        except ImportError:
            pass

        try:
            from .types.targets import MinTradingDaysRule

            self._rule_types["min_trading_days"] = MinTradingDaysRule
            logger.debug("Loaded MinTradingDaysRule")
        except ImportError:
            pass

        try:
            from .types.consistency import ConsistencyRule

            self._rule_types["consistency"] = ConsistencyRule
            logger.debug("Loaded ConsistencyRule")
        except ImportError:
            pass

        try:
            from .types.targets import WeeklyTargetRule

            self._rule_types["weekly_target"] = WeeklyTargetRule
            logger.debug("Loaded WeeklyTargetRule")
        except ImportError:
            pass

        try:
            from .types.news_blackout import NewsBlackoutRule

            self._rule_types["news_blackout"] = NewsBlackoutRule
            logger.debug("Loaded NewsBlackoutRule")
        except ImportError:
            pass

        # Log which rules are using placeholders
        placeholder_types = [
            k
            for k, v in self._rule_types.items()
            if "Placeholder" in v.__name__
        ]
        if placeholder_types and not self._placeholders_created:
            logger.info(
                "Using placeholder classes for: %s. "
                "Full implementations will be available as Epic 4 progresses.",
                ", ".join(placeholder_types),
            )
            self._placeholders_created = True

        return self._rule_types

    def _create_placeholder_types(self) -> dict[str, type]:
        """Create placeholder rule classes for pre-Epic 4 operation.

        Returns:
            Dictionary of placeholder rule classes.
        """
        from .base_rule import RuleAction, RuleResult

        # Priority mapping for different rule types (critical rules first)
        priority_map = {
            "daily_loss_limit": 1,
            "max_drawdown": 2,
            "consistency": 5,
            "max_position_size": 10,
            "profit_target": 100,
            "min_trading_days": 100,
            "weekly_target": 100,
        }
        # Without an entry here, a future import failure of `types/targets.py`
        # or `types/consistency.py` would silently delete these rule types
        # from RULE_TYPES — the placeholder dance keeps them resolvable.

        def make_placeholder(rule_type_name: str) -> type:
            """Create a placeholder rule class."""

            class PlaceholderRule:
                """Placeholder rule - full implementation in Epic 4.

                Implements the extended BaseRule protocol from Story 4.1.
                """

                rule_type: str = rule_type_name
                name: str = f"Placeholder {rule_type_name.replace('_', ' ').title()}"
                priority: int = priority_map.get(rule_type_name, 50)

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

                def get_current_value(self, context: dict[str, Any]) -> float:
                    """Placeholder - returns 0.0."""
                    return 0.0

                def get_threshold(self) -> float:
                    """Get threshold from config, default 100.0."""
                    return getattr(self, "threshold_percent", 100.0)

                def get_warning_thresholds(self) -> list[float]:
                    """Placeholder - returns default warning thresholds."""
                    return [70.0, 80.0, 90.0]

                def __repr__(self) -> str:
                    attrs = ", ".join(f"{k}={v}" for k, v in self.__dict__.items())
                    return f"<PlaceholderRule({rule_type_name}) {attrs}>"

            PlaceholderRule.__name__ = f"Placeholder{rule_type_name.title().replace('_', '')}Rule"
            return PlaceholderRule

        return {
            "daily_loss_limit": make_placeholder("daily_loss_limit"),
            "max_drawdown": make_placeholder("max_drawdown"),
            "consistency": make_placeholder("consistency"),
            "max_position_size": make_placeholder("max_position_size"),
            "profit_target": make_placeholder("profit_target"),
            "min_trading_days": make_placeholder("min_trading_days"),
            "weekly_target": make_placeholder("weekly_target"),
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
