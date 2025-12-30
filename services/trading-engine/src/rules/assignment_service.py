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
    from .base_rule import BaseRule

logger = logging.getLogger(__name__)


class RuleAssignmentService:
    """Service for assigning rules to accounts.

    Determines which rules apply to each account based on its
    configuration (prop firm preset, custom rules, or none).

    This service acts as the main interface for rule assignment,
    delegating to specialized loaders based on account type.

    Attributes:
        _preset_loader: Loader for prop firm presets.
        _custom_loader: Loader for custom rule files.
    """

    def __init__(
        self,
        preset_loader: RulePresetLoader | None = None,
        custom_loader: CustomRuleLoader | None = None,
    ):
        """Initialize rule assignment service.

        Args:
            preset_loader: Optional preset loader (creates default if None).
            custom_loader: Optional custom loader (creates default if None).
        """
        self._preset_loader = preset_loader or RulePresetLoader()
        self._custom_loader = custom_loader or CustomRuleLoader()

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

        if assignment.assignment_type == "preset":
            rules = self._preset_loader.load_preset(assignment.preset_name)
            logger.info(
                f"Assigned {len(rules)} rules from preset "
                f"'{assignment.preset_name}' to account '{account.id}'"
            )
            return rules

        elif assignment.assignment_type == "personal":
            rules = self._custom_loader.load_custom_rules(assignment.rules_file)
            logger.info(
                f"Assigned {len(rules)} personal rules from "
                f"'{assignment.rules_file}' to account '{account.id}'"
            )
            return rules

        else:
            logger.info(
                f"No rules assigned to account '{account.id}' "
                f"(type: {account.type.value})"
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
