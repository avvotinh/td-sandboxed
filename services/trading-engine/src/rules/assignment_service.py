"""Service for assigning rules to accounts.

Determines which rules apply to each account based on its configuration
(firm-bound profile or personal rules file).

Example:
    >>> from src.rules.assignment_service import RuleAssignmentService
    >>> service = RuleAssignmentService(firm_registry=registry)
    >>> rules = service.get_rules_for_account(account_config)
    >>> print(f"Assigned {len(rules)} rules")
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .assignment import RuleAssignment
from .custom_loader import CustomRuleLoader
from .override_merger import merge_rule_overrides
from .parser import RuleParser

if TYPE_CHECKING:
    from ..accounts.models import AccountConfig
    from ..config.firm_registry import FirmRegistry
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class RuleAssignmentService:
    """Service for assigning rules to accounts.

    Determines which rules apply to each account based on its
    configuration (firm binding or personal rules file).

    Story 10.13 — the legacy ``RulePresetLoader`` was removed once
    Story 10.12 dropped the ``prop_firm`` field from ``AccountConfig``.
    Pre-existing ``RuleAssignment(assignment_type="preset", ...)``
    objects (constructed in tests for backwards compatibility) raise on
    :meth:`get_rules_for_account` rather than silently returning ``[]``.

    Attributes:
        _custom_loader: Loader for custom rule files.
        _firm_registry: Optional FirmRegistry for firm-bound accounts (Epic 9).
    """

    def __init__(
        self,
        custom_loader: CustomRuleLoader | None = None,
        firm_registry: "FirmRegistry | None" = None,
        rule_parser: RuleParser | None = None,
    ):
        """Initialize rule assignment service.

        Args:
            custom_loader: Optional custom loader (creates default if None).
            firm_registry: Optional firm registry for ``assignment_type=="firm"``
                accounts. If an account is firm-bound but this is ``None``,
                :meth:`get_rules_for_account` raises :class:`ValueError`.
            rule_parser: Optional rule parser used to re-instantiate the
                merged rule specs when phase or account overrides are
                present (creates default if None).
        """
        self._custom_loader = custom_loader or CustomRuleLoader()
        self._firm_registry = firm_registry
        self._rule_parser = rule_parser or RuleParser()

    @property
    def custom_loader(self) -> CustomRuleLoader:
        """Get the custom loader."""
        return self._custom_loader

    def get_rules_for_account(
        self,
        account: "AccountConfig",
    ) -> list["BaseRule"]:
        """Get rules for an account based on its configuration.

        This is the main entry point for rule assignment. It:
        1. Determines assignment type from account configuration
        2. Loads rules from appropriate source (preset or custom file)
        3. Returns the list of rule instances

        Args:
            account: Account configuration object.

        Returns:
            List of rule objects to apply to the account.
            Empty list if account has no rules (e.g., demo accounts).

        Raises:
            PresetNotFoundError: If preset doesn't exist.
            RulesFileNotFoundError: If custom rules file doesn't exist.
            RuleParseError: If rules cannot be parsed.
        """
        assignment = RuleAssignment.from_account_config(account)

        if assignment.assignment_type == "firm":
            if self._firm_registry is None:
                from ..config.firm_registry import FirmRegistryNotConfiguredError

                raise FirmRegistryNotConfiguredError(
                    f"Account '{account.id}' is firm-bound "
                    f"({assignment.source_description}) but no FirmRegistry "
                    "is configured on this RuleAssignmentService."
                )
            _firm, product, phase = self._firm_registry.resolve(
                assignment.firm_id, assignment.product_id, assignment.phase
            )
            # Always run the merger, even when both override layers are empty.
            # Re-parsing from rule_specs gives every account its own fresh rule
            # instances, so any future stateful field on a BaseRule subclass
            # cannot leak across accounts via the cached product.rules tuple.
            merged_specs = merge_rule_overrides(
                product.rule_specs,
                phase.rule_overrides,
                assignment.rule_overrides,
                account_id=account.id,
            )
            rules = self._rule_parser.parse_rules({"rules": merged_specs})
            if phase.rule_overrides or assignment.rule_overrides:
                logger.info(
                    "Account '%s' rule set rebuilt with overrides "
                    "(phase=%d types, account=%d types)",
                    account.id,
                    len(phase.rule_overrides),
                    len(assignment.rule_overrides),
                )
            logger.info(
                "Assigned %d rules from %s to account '%s'",
                len(rules),
                assignment.source_description,
                account.id,
            )
            return rules

        if assignment.assignment_type == "preset":
            # Story 10.12 dropped the AccountConfig field; story 10.13
            # dropped the loader. Surfaces as a clear error if any test
            # or migration tool still constructs a preset assignment.
            raise NotImplementedError(
                f"Account '{account.id}' carries a legacy 'preset' "
                "assignment, but the preset path was removed in story "
                "10.13. Migrate the account to firm_id+product_id+phase."
            )

        if assignment.assignment_type == "personal":
            rules = self._custom_loader.load_custom_rules(assignment.rules_file)
            logger.info(
                "Assigned %d personal rules from '%s' to account '%s'",
                len(rules),
                assignment.rules_file,
                account.id,
            )
            return rules

        logger.info(
            "No rules assigned to account '%s' (type: %s)",
            account.id,
            account.type.value,
        )
        return []

    def get_assignment_for_account(
        self,
        account: "AccountConfig",
    ) -> RuleAssignment:
        """Get the rule assignment configuration for an account.

        Unlike get_rules_for_account(), this returns the assignment
        metadata without loading the actual rules. Useful for
        inspecting what rules will be loaded.

        Args:
            account: Account configuration object.

        Returns:
            RuleAssignment with type and source information.
        """
        return RuleAssignment.from_account_config(account)

    def set_config_dir(self, config_dir: Path | str) -> None:
        """Set the configuration directory for custom rules.

        Args:
            config_dir: New configuration directory path.
        """
        if isinstance(config_dir, str):
            config_dir = Path(config_dir)

        self._custom_loader = CustomRuleLoader(config_dir=config_dir)
        logger.debug(f"Updated custom rules config_dir to: {config_dir}")
