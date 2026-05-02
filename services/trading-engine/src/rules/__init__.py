"""Rules module - Pluggable rule engine.

This module handles:
- Rule assignment to accounts (Story 3.7)
- Firm-bound profile loading (Epic 9; legacy preset loader removed in 10.13)
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
- CustomRuleLoader: Load rules from custom YAML files
- RuleParser: Parse YAML rule definitions
- Exceptions: RulesFileNotFoundError, RuleParseError

Story 4.1 Exports:
- RuleEngine: Core engine that evaluates multiple rules
- RuleEngineResult: Result of evaluating all rules
- RuleEngineFactory: Factory for creating account-specific engines
- RuleContextBuilder: Builder for creating validation contexts
- RuleValidationError: Exception for rule validation failures

Story 4.2 Exports:
- DailyLossLimitRule: Blocks trades when daily loss exceeds threshold

Story 4.3 Exports:
- MaxDrawdownRule: Blocks trades when total drawdown exceeds threshold

Story 4.4 Exports:
- MaxPositionSizeRule: Limits position sizes with fixed or scaled limits

Story 4.8 Exports:
- AuditLogger: Logs rule checks to Redis with fire-and-forget pattern
- AuditEntry: Dataclass representing a single audit log entry
- AuditLoggerRegistry: Per-account audit logger management
- AuditDBWriter: Batch persistence to TimescaleDB
- audit_task_done_callback: Done callback for fire-and-forget audit tasks

Full rule implementations in Epic 4+.
"""

from .assignment import RuleAssignment
from .assignment_service import RuleAssignmentService
from .audit_db_writer import AuditDBWriter, AuditLogModel
from .audit_logger import (
    AUDIT_TTL_SECONDS,
    AuditEntry,
    AuditEventType,
    AuditLogger,
    audit_task_done_callback,
)
from .audit_registry import AuditLoggerRegistry
from .base_rule import BaseRule, RuleAction, RuleList, RuleResult
from .context_builder import RuleContextBuilder
from .custom_loader import CustomRuleLoader, RulesFileInvalidError, RulesFileNotFoundError
from .engine import RuleEngine, RuleValidationError
from .engine_factory import RuleEngineFactory
from .engine_result import RuleEngineResult
from .parser import RuleParseError, RuleParser
from .types.consistency import ConsistencyRule
from .types.drawdown import DailyLossLimitRule, MaxDrawdownRule
from .types.position import MaxPositionSizeRule
from .types.targets import MinTradingDaysRule, ProfitTargetRule, WeeklyTargetRule
from .violation import RuleViolation
from .violation_db_writer import RuleViolationModel, ViolationDBWriter
from .violation_service import ViolationService

__all__ = [
    # Base types
    "BaseRule",
    "RuleAction",
    "RuleResult",
    "RuleList",
    # Rule types (Story 4.2+; Epic 9 P0.7 added ConsistencyRule;
    #             P0.8 added WeeklyTargetRule)
    "ConsistencyRule",
    "DailyLossLimitRule",
    "MaxDrawdownRule",
    "MaxPositionSizeRule",
    "ProfitTargetRule",
    "MinTradingDaysRule",
    "WeeklyTargetRule",
    # Assignment
    "RuleAssignment",
    "RuleAssignmentService",
    # Loaders
    "CustomRuleLoader",
    "RuleParser",
    # Engine (Story 4.1)
    "RuleEngine",
    "RuleEngineResult",
    "RuleEngineFactory",
    "RuleContextBuilder",
    "RuleValidationError",
    # Audit logging (Story 4.8)
    "AuditLogger",
    "AuditEntry",
    "AuditEventType",
    "AuditLoggerRegistry",
    "AuditDBWriter",
    "AuditLogModel",
    "audit_task_done_callback",
    "AUDIT_TTL_SECONDS",
    # Violation tracking (Story 7.3)
    "RuleViolation",
    "RuleViolationModel",
    "ViolationDBWriter",
    "ViolationService",
    # Exceptions
    "RulesFileNotFoundError",
    "RulesFileInvalidError",
    "RuleParseError",
]
