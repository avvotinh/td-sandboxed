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

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..accounts.models import AccountConfig
    from .base_rule import BaseRule

AssignmentType = Literal["firm", "preset", "personal", "none"]


@dataclass
class RuleAssignment:
    """Rule assignment configuration for an account.

    Determines which rules apply to an account based on its type.
    This is an intermediate representation between account configuration
    and loaded rules.

    Attributes:
        assignment_type: How rules are assigned
            ("firm", "preset", "personal", "none").
        preset_name: Name of preset (assignment_type == "preset").
        rules_file: Path to custom rules file (assignment_type == "personal").
        firm_id: Firm registry id (assignment_type == "firm").
        product_id: Firm product id (assignment_type == "firm").
        phase: Firm phase id (assignment_type == "firm").
        rule_overrides: Per-account overrides (assignment_type == "firm").
            Merged against product + phase baseline by
            :func:`rules.override_merger.merge_rule_overrides`; account
            overrides may only tighten guarded block thresholds.
        rules: List of instantiated rule objects (populated after loading).
    """

    assignment_type: AssignmentType
    preset_name: str | None = None
    rules_file: str | None = None
    firm_id: str | None = None
    product_id: str | None = None
    phase: str | None = None
    rule_overrides: dict[str, Any] = field(default_factory=dict)
    rules: list["BaseRule"] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate assignment configuration."""
        if self.assignment_type == "preset" and not self.preset_name:
            raise ValueError(
                "preset_name is required when assignment_type is 'preset'"
            )

        if self.assignment_type == "personal" and not self.rules_file:
            raise ValueError(
                "rules_file is required when assignment_type is 'personal'"
            )

        if self.assignment_type == "firm":
            missing = [
                f for f, v in
                [("firm_id", self.firm_id), ("product_id", self.product_id), ("phase", self.phase)]
                if not v
            ]
            if missing:
                raise ValueError(
                    f"assignment_type 'firm' requires all of firm_id, product_id, phase; "
                    f"missing {missing}"
                )

    @classmethod
    def from_account_config(cls, account: "AccountConfig") -> "RuleAssignment":
        """Create RuleAssignment from account configuration.

        Resolution order (matches ``AccountConfig.validate_rules_source``):
          1. ``firm_id`` set → firm assignment (Epic 9+ path).
          2. ``rules_file`` set → personal assignment.
          3. Otherwise (demo or no source) → none.

        Story 10.12 dropped the legacy ``prop_firm`` preset branch
        once ops sign-off confirmed no production accounts remain on
        the legacy path. ``RuleAssignment(assignment_type="preset")``
        is still constructable for historical-data inspection but
        :class:`AccountConfig` no longer produces it.
        """
        from ..accounts.models import AccountType

        if account.firm_id and account.product_id and account.phase:
            return cls(
                assignment_type="firm",
                firm_id=account.firm_id,
                product_id=account.product_id,
                phase=account.phase,
                rule_overrides=deepcopy(account.rule_overrides),
            )
        if account.type == AccountType.PERSONAL and account.rules_file:
            return cls(
                assignment_type="personal",
                rules_file=account.rules_file,
            )
        return cls(assignment_type="none")

    @property
    def source_description(self) -> str:
        """Human-readable description of rule source.

        Returns:
            Source description (e.g., "firm:ftmo/challenge/evaluation",
            "preset:ftmo", "personal:my_rules.yaml", "none").
        """
        if self.assignment_type == "firm":
            return f"firm:{self.firm_id}/{self.product_id}/{self.phase}"
        if self.assignment_type == "preset":
            return f"preset:{self.preset_name}"
        if self.assignment_type == "personal":
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
        if self.assignment_type == "firm":
            return (
                f"RuleAssignment(type='firm', firm='{self.firm_id}', "
                f"product='{self.product_id}', phase='{self.phase}', "
                f"overrides={len(self.rule_overrides)}, rules={self.rule_count})"
            )
        if self.assignment_type == "preset":
            return f"RuleAssignment(type='preset', preset='{self.preset_name}', rules={self.rule_count})"
        if self.assignment_type == "personal":
            return f"RuleAssignment(type='personal', file='{self.rules_file}', rules={self.rule_count})"
        return "RuleAssignment(type='none')"
