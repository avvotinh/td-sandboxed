"""Rules module - Pluggable rule engine.

This module handles:
- Rule assignment to accounts (Story 3.7)
- Prop firm preset loading (FTMO, The5ers, WMT)
- Custom rule file parsing
- FTMO compliance rules (daily loss limit, max drawdown, etc.) - Epic 4
- Rule validation before trade execution - Epic 4
- Rule check audit logging - Epic 4

Story 3.7 Exports:
- BaseRule: Protocol for rule implementations
- RuleAction, RuleResult: Rule validation results
- RuleAssignment: Assignment configuration for accounts
- RuleAssignmentService: Main service for assigning rules to accounts
- RulePresetLoader: Load rules from prop firm presets
- CustomRuleLoader: Load rules from custom YAML files
- RuleParser: Parse YAML rule definitions
- Exceptions: PresetNotFoundError, RulesFileNotFoundError, RuleParseError

Full rule implementations in Epic 4+.
"""

from .assignment import RuleAssignment
from .assignment_service import RuleAssignmentService
from .base_rule import BaseRule, RuleAction, RuleList, RuleResult
from .custom_loader import CustomRuleLoader, RulesFileInvalidError, RulesFileNotFoundError
from .parser import RuleParseError, RuleParser
from .preset_loader import PresetNotFoundError, RulePresetLoader

__all__ = [
    # Base types
    "BaseRule",
    "RuleAction",
    "RuleResult",
    "RuleList",
    # Assignment
    "RuleAssignment",
    "RuleAssignmentService",
    # Loaders
    "RulePresetLoader",
    "CustomRuleLoader",
    "RuleParser",
    # Exceptions
    "PresetNotFoundError",
    "RulesFileNotFoundError",
    "RulesFileInvalidError",
    "RuleParseError",
]
