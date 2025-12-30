"""Rule assignment model for accounts.

Determines which rules apply to an account based on its type and configuration.
This module bridges account configuration (Epic 2/3) with rule loading (Epic 4).

Example:
    >>> from src.accounts.models import AccountConfig, AccountType
    >>> config = AccountConfig(
    ...     id="ftmo-001", name="FTMO Gold", type=AccountType.PROP_FIRM,
    ...     prop_firm="ftmo", mt5=..., strategy="ma_crossover"
    ... )
    >>> assignment = RuleAssignment.from_account_config(config)
    >>> assignment.assignment_type
    'preset'
    >>> assignment.preset_name
    'ftmo'
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..accounts.models import AccountConfig
    from .base_rule import BaseRule


@dataclass
class RuleAssignment:
    """Rule assignment configuration for an account.

    Determines which rules apply to an account based on its type.
    This is an intermediate representation between account configuration
    and loaded rules.

    Attributes:
        assignment_type: How rules are assigned ("preset", "personal", "none").
        preset_name: Name of preset if using prop firm preset.
        rules_file: Path to custom rules file if using personal/custom rules.
        rules: List of instantiated rule objects (populated after loading).
    """

    assignment_type: Literal["preset", "personal", "none"]
    preset_name: str | None = None
    rules_file: str | None = None
    rules: list["BaseRule"] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate assignment configuration."""
        # Validate preset_name is set for preset type
        if self.assignment_type == "preset" and not self.preset_name:
            raise ValueError(
                "preset_name is required when assignment_type is 'preset'"
            )

        # Validate rules_file is set for personal type
        if self.assignment_type == "personal" and not self.rules_file:
            raise ValueError(
                "rules_file is required when assignment_type is 'personal'"
            )

    @classmethod
    def from_account_config(cls, account: "AccountConfig") -> "RuleAssignment":
        """Create RuleAssignment from account configuration.

        Determines the assignment type based on account type and
        available configuration fields.

        Args:
            account: Account configuration object.

        Returns:
            RuleAssignment with appropriate type and settings.

        Note:
            Uses AccountType enum for comparison (not string literals).
            - PROP_FIRM with prop_firm → preset assignment
            - PERSONAL with rules_file → personal assignment
            - DEMO or no rules → no assignment
        """
        # Import here to avoid circular import
        from ..accounts.models import AccountType

        if account.type == AccountType.PROP_FIRM and account.prop_firm:
            return cls(
                assignment_type="preset",
                preset_name=account.prop_firm,
            )
        elif account.type == AccountType.PERSONAL and account.rules_file:
            return cls(
                assignment_type="personal",
                rules_file=account.rules_file,
            )
        else:
            # Demo, test, or no rules specified
            return cls(assignment_type="none")

    @property
    def source_description(self) -> str:
        """Human-readable description of rule source.

        Returns:
            Source description (e.g., "preset:ftmo", "personal:my_rules.yaml", "none").
        """
        if self.assignment_type == "preset":
            return f"preset:{self.preset_name}"
        elif self.assignment_type == "personal":
            return f"personal:{self.rules_file}"
        return "none"

    @property
    def has_rules(self) -> bool:
        """Check if this assignment will load rules.

        Returns:
            True if assignment_type is not 'none'.
        """
        return self.assignment_type != "none"

    @property
    def rule_count(self) -> int:
        """Get the number of loaded rules.

        Returns:
            Number of rules in the rules list.
        """
        return len(self.rules)

    def __repr__(self) -> str:
        """Return string representation."""
        if self.assignment_type == "preset":
            return f"RuleAssignment(type='preset', preset='{self.preset_name}', rules={self.rule_count})"
        elif self.assignment_type == "personal":
            return f"RuleAssignment(type='personal', file='{self.rules_file}', rules={self.rule_count})"
        return "RuleAssignment(type='none')"
