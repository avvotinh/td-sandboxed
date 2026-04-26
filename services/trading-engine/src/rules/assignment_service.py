"""Service for assigning rules to accounts.

Determines which rules apply to each account based on its configuration
(prop firm preset, custom rules, or none).

Example:
    >>> from src.rules.assignment_service import RuleAssignmentService
    >>> service = RuleAssignmentService()
    >>> rules = service.get_rules_for_account(account_config)
    >>> print(f"Assigned {len(rules)} rules")
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .assignment import RuleAssignment
from .custom_loader import CustomRuleLoader
from .preset_loader import RulePresetLoader

if TYPE_CHECKING:
    from ..accounts.models import AccountConfig
    from ..config.firm_registry import FirmRegistry
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class RuleAssignmentService:
    """Service for assigning rules to accounts.

    Determines which rules apply to each account based on its
    configuration (firm binding, prop firm preset, custom rules, or none).

    This service acts as the main interface for rule assignment,
    delegating to specialized loaders based on account type.

    Attributes:
        _preset_loader: Loader for legacy prop firm presets (Epic 4).
        _custom_loader: Loader for custom rule files.
        _firm_registry: Optional FirmRegistry for firm-bound accounts (Epic 9).
    """

    def __init__(
        self,
        preset_loader: RulePresetLoader | None = None,
        custom_loader: CustomRuleLoader | None = None,
        firm_registry: "FirmRegistry | None" = None,
    ):
        """Initialize rule assignment service.

        Args:
            preset_loader: Optional preset loader (creates default if None).
            custom_loader: Optional custom loader (creates default if None).
            firm_registry: Optional firm registry for ``assignment_type=="firm"``
                accounts. If an account is firm-bound but this is ``None``,
                :meth:`get_rules_for_account` raises :class:`ValueError`.
        """
        self._preset_loader = preset_loader or RulePresetLoader()
        self._custom_loader = custom_loader or CustomRuleLoader()
        self._firm_registry = firm_registry

    @property
    def preset_loader(self) -> RulePresetLoader:
        """Get the preset loader."""
        return self._preset_loader

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
            _firm, product, _phase = self._firm_registry.resolve(
                assignment.firm_id, assignment.product_id, assignment.phase
            )
            # TODO(P0.16): merge product.rules with phase.rule_overrides and
            # assignment.rule_overrides (with safety guard: no loosening of
            # block thresholds). For now, return the product's baseline rules.
            rules = list(product.rules)
            logger.info(
                "Assigned %d rules from %s to account '%s'",
                len(rules),
                assignment.source_description,
                account.id,
            )
            return rules

        if assignment.assignment_type == "preset":
            rules = self._preset_loader.load_preset(assignment.preset_name)
            logger.info(
                "Assigned %d rules from preset '%s' to account '%s'",
                len(rules),
                assignment.preset_name,
                account.id,
            )
            return rules

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

    def get_available_presets(self) -> list[str]:
        """Get list of available preset names.

        Returns:
            List of preset names.
        """
        return self._preset_loader.get_available_presets()

    def set_config_dir(self, config_dir: Path | str) -> None:
        """Set the configuration directory for custom rules.

        Args:
            config_dir: New configuration directory path.
        """
        if isinstance(config_dir, str):
            config_dir = Path(config_dir)

        self._custom_loader = CustomRuleLoader(config_dir=config_dir)
        logger.debug(f"Updated custom rules config_dir to: {config_dir}")

    def clear_preset_cache(self) -> None:
        """Clear the preset cache.

        Forces presets to be reloaded from disk on next access.
        Useful for testing or when preset files are updated.
        """
        self._preset_loader.clear_cache()
