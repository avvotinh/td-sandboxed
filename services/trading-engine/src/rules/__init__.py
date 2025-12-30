"""Rules module - Pluggable rule engine.

This module handles:
- Rule assignment to accounts (Story 3.7)
- Prop firm preset loading (FTMO, The5ers, WMT)
- Custom rule file parsing
- Rule engine framework (Story 4.1)
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

Story 4.1 Exports:
- RuleEngine: Core engine that evaluates multiple rules
- RuleEngineResult: Result of evaluating all rules
- RuleEngineFactory: Factory for creating account-specific engines
- RuleContextBuilder: Builder for creating validation contexts
- RuleValidationError: Exception for rule validation failures

Story 4.2 Exports:
- DailyLossLimitRule: Blocks trades when daily loss exceeds threshold

Full rule implementations in Epic 4+.
"""

from .assignment import RuleAssignment
from .assignment_service import RuleAssignmentService
from .base_rule import BaseRule, RuleAction, RuleList, RuleResult
from .context_builder import RuleContextBuilder
from .custom_loader import CustomRuleLoader, RulesFileInvalidError, RulesFileNotFoundError
from .engine import RuleEngine, RuleValidationError
from .engine_factory import RuleEngineFactory
from .engine_result import RuleEngineResult
from .parser import RuleParseError, RuleParser
from .preset_loader import PresetNotFoundError, RulePresetLoader
from .types.drawdown import DailyLossLimitRule

__all__ = [
    # Base types
    "BaseRule",
    "RuleAction",
    "RuleResult",
    "RuleList",
    # Rule types (Story 4.2+)
    "DailyLossLimitRule",
    # Assignment
    "RuleAssignment",
    "RuleAssignmentService",
    # Loaders
    "RulePresetLoader",
    "CustomRuleLoader",
    "RuleParser",
    # Engine (Story 4.1)
    "RuleEngine",
    "RuleEngineResult",
    "RuleEngineFactory",
    "RuleContextBuilder",
    "RuleValidationError",
    # Exceptions
    "PresetNotFoundError",
    "RulesFileNotFoundError",
    "RulesFileInvalidError",
    "RuleParseError",
]
