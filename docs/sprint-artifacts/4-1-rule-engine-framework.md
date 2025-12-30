# Story 4.1: Rule Engine Framework

Status: Done

## Story

As a **developer**,
I want **a pluggable rule engine framework**,
So that **I can implement different rule types and presets**.

## Acceptance Criteria

1. **AC1**: Given I create a new rule type, when I inherit from `BaseRule`, then I implement:
   - `validate(account, signal) -> RuleResult` - Check if action is allowed
   - `get_current_value(account) -> float` - Get current metric value
   - `get_threshold() -> float` - Get configured threshold
   - `get_warning_thresholds() -> List[float]` - Get warning percentages

2. **AC2**: Given a rule engine is initialized for an account, when a signal is generated, then all applicable rules are evaluated before execution

3. **AC3**: Given any rule returns `BLOCK`, when the engine processes the result, then the trade is not executed and the blocking reason is logged

4. **AC4**: Given a rule returns `WARN`, when the engine processes the result, then a warning notification is generated and the trade proceeds (unless another rule blocks)

5. **AC5**: Given multiple rules are configured, when the engine validates a signal, then rules are evaluated in priority order with critical rules first

6. **AC6**: Given the engine encounters an error during validation, when the error is caught, then the trade is BLOCKED (fail-safe) and the error is logged

## Tasks / Subtasks

### Task 1: Extend BaseRule Protocol with Full Interface (AC: 1)

- [x] 1.1: Update `src/rules/base_rule.py` to add `get_current_value(context: dict) -> float` method to BaseRule protocol
- [x] 1.2: Add `get_threshold() -> float` method to BaseRule protocol
- [x] 1.3: Add `get_warning_thresholds() -> list[float]` method to BaseRule protocol
- [x] 1.4: Add `priority: int` attribute to BaseRule protocol (lower = higher priority)
- [x] 1.5: Add `name: str` attribute to BaseRule protocol for human-readable rule name
- [x] 1.6: **EXTEND** RuleResult (don't replace) to include `current_value: float | None = None` and `threshold_value: float | None = None` as optional fields with defaults

### Task 2: Create RuleEngine Core Class (AC: 2, 5)

- [x] 2.1: Create `src/rules/engine.py` with `RuleEngine` class (see RuleEngine Class Design)
- [x] 2.2: Define constructor: `__init__(self, rules: list[BaseRule], account_id: str)`
- [x] 2.3: Implement rule priority sorting in `__init__` (sort by priority attribute, critical rules first; rules with equal priority maintain insertion order via stable sort)
- [x] 2.4: Implement `validate(self, context: dict[str, Any]) -> RuleEngineResult` (see code design)
- [x] 2.5: Add `_log_validation(rule: BaseRule, result: RuleResult)` helper for structured logging
- [x] 2.6: Add `get_rules() -> list[BaseRule]` method for inspection

### Task 3: Create RuleEngineResult Dataclass (AC: 2, 3, 4)

- [x] 3.1: Create `src/rules/engine_result.py` with `RuleEngineResult` dataclass (see RuleEngineResult Design)
- [x] 3.2-3.5: Implement all fields and properties as shown in code design section

### Task 4: Implement Short-Circuit Evaluation (AC: 3, 5)

- [x] 4.1: Update `RuleEngine.validate()` to short-circuit on first BLOCK result
- [x] 4.2: Add `continue_after_block: bool = False` parameter to control short-circuit behavior
- [x] 4.3: When short-circuiting, still return partial results for audit purposes
- [x] 4.4: Log when short-circuit occurs: "Rule evaluation stopped: {rule_name} blocked trade"

### Task 5: Implement Warning Aggregation (AC: 4)

- [x] 5.1: Collect all WARN results during evaluation (even if BLOCK occurs later)
- [x] 5.2: Add `has_warnings` property to RuleEngineResult
- [x] 5.3: Add `warning_messages -> list[str]` property for easy notification creation
- [x] 5.4: Ensure warnings are logged even when trade proceeds

### Task 6: Implement Fail-Safe Error Handling (AC: 6)

- [x] 6.1: Wrap each `rule.validate()` call in try/except
- [x] 6.2: On exception: log error, return BLOCK result with error message
- [x] 6.3: Add `RuleValidationError` exception class for rule-specific errors
- [x] 6.4: Include exception details in RuleResult metadata for debugging
- [x] 6.5: Add `strict_mode: bool = True` constructor parameter (if True, any error = BLOCK)

### Task 7: Create RuleEngineFactory (AC: 2)

- [x] 7.1: Create `src/rules/engine_factory.py` with `RuleEngineFactory` class
- [x] 7.2: Implement `create_for_account(account_id: str, rules: list[BaseRule]) -> RuleEngine`
- [x] 7.3: Add logging: "Created RuleEngine for account {account_id} with {n} rules"
- [x] 7.4: Validate that all rules implement BaseRule protocol before creating engine

### Task 8: Integrate with AccountManager (AC: 2)

**NOTE:** AccountManager already has `_initialize_account_rules()` from Story 3.7. This task EXTENDS that integration, not replaces it.

- [x] 8.1: Add `_rule_engines: dict[str, RuleEngine]` to AccountManager `__init__`
- [x] 8.2: **Modify** existing `_initialize_account_rules()` to ALSO create RuleEngine from assigned rules after loading them
- [x] 8.3: Add `get_rule_engine(account_id: str) -> RuleEngine | None` method
- [x] 8.4: Ensure RuleEngine is created after rules are assigned via RuleAssignmentService

### Task 9: Add Context Builder Helper (AC: 2)

- [x] 9.1: Create `src/rules/context_builder.py` with `RuleContextBuilder` class (see RuleContextBuilder Design)
- [x] 9.2: Implement `build_validation_context()` - signal can be any object with `symbol`, `side`, `quantity` attributes (duck typing)
- [x] 9.3: Add `add_custom_field(key: str, value: Any)` for extensibility
- [x] 9.4: Add `validate_context(context: dict) -> bool` to ensure required fields exist

### Task 10: Unit Tests (AC: 1-6)

- [x] 10.1: Test BaseRule protocol with mock implementations
- [x] 10.2: Test RuleEngine priority ordering (lower priority first; verify stable sort for equal priorities)
- [x] 10.3: Test RuleEngine.validate() returns ALLOW when all rules pass
- [x] 10.4: Test RuleEngine.validate() returns BLOCK when any rule blocks
- [x] 10.5: Test short-circuit behavior stops on first BLOCK
- [x] 10.6: Test warning aggregation collects all WARNs
- [x] 10.7: Test fail-safe: exception in rule = BLOCK result
- [x] 10.8: Test RuleEngineResult properties and summary
- [x] 10.9: Test RuleContextBuilder builds valid context
- [x] 10.10: Test RuleEngineFactory creates valid engines

### Task 11: Integration Tests (AC: 2, 3, 4)

- [x] 11.1: Test full flow: AccountManager -> RuleEngine -> validation
- [x] 11.2: Test multiple accounts have independent rule engines
- [x] 11.3: Test rule engine with mixed FTMO preset rules
- [x] 11.4: Test validation performance: 10 rules < 50ms (see NFR2 in docs/prd.md)

## Dev Notes

### CRITICAL DEPENDENCIES & PREREQUISITES

**Story 3.7 Foundation:**
This story builds directly on Story 3.7 (Account Rule Assignment) which created:
- `BaseRule` protocol in `src/rules/base_rule.py` (placeholder with `rule_type`, `validate()`)
- `RuleAction` enum: ALLOW, WARN, BLOCK
- `RuleResult` dataclass: action, message, metadata
- `RuleAssignmentService` for loading rules per account
- `RulePresetLoader` for FTMO/The5ers/WMT presets
- `RuleParser` for YAML rule definitions
- AccountManager integration: `_initialize_account_rules()`, `get_account_rules()`

**This story EXTENDS the BaseRule protocol and RuleResult (does NOT replace them).**

**Dependencies:**
- Story 3.7: Account Rule Assignment (COMPLETE)
- Account metrics from Story 3.6: Per-Account Equity and Balance Tracking (COMPLETE)

**Subsequent Stories Depend On:**
- Story 4.2: Daily Loss Limit Rule (uses RuleEngine framework)
- Story 4.3: Max Drawdown Rule (uses RuleEngine framework)
- Story 4.6: Rule Validation Before Trade (integrates RuleEngine with execution flow)

### Task Dependencies

```
Task 1 (Extend BaseRule)
    ↓
Task 3 (RuleEngineResult) ───┐
    ↓                        │
Task 2 (RuleEngine) ←────────┘
    ↓
Task 4 (Short-Circuit) ─┐
    ↓                   │
Task 5 (Warnings) ──────┼──→ Task 6 (Error Handling)
    ↓                   │
Task 7 (Factory) ←──────┘
    ↓
Task 8 (AccountManager Integration)
    ↓
Task 9 (Context Builder)
    ↓
Task 10-11 (Tests)
```

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Pydantic:** v2 for dataclass validation (if needed)
- **Existing Rules Module:** `src/rules/` from Story 3.7

### Key Design Decisions

**Sync vs Async:**
`RuleEngine.validate()` is intentionally **synchronous** for performance (< 50ms requirement per NFR2). Async operations (Redis queries, DB writes) should happen OUTSIDE the validation loop - either before (to build context) or after (to log results).

**Priority Tie-Breaking:**
Rules with equal priority maintain insertion order (Python's `sorted()` is stable). This ensures deterministic behavior.

**Logging Levels:**
- ALLOW results: `logger.debug()` (high volume, only for debugging)
- WARN results: `logger.warning()` (important, but trade proceeds)
- BLOCK results: `logger.warning()` (critical, trade stopped)
- Errors: `logger.exception()` (with full traceback)

### RuleResult Extension (Task 1.6)

**IMPORTANT:** The existing `RuleResult` from Story 3.7 has: `action`, `message`, `metadata`. ADD new optional fields without breaking compatibility:

```python
# In src/rules/base_rule.py - EXTEND existing RuleResult
@dataclass
class RuleResult:
    """Result of a rule validation check."""
    action: RuleAction = RuleAction.ALLOW
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # NEW optional fields (Story 4.1) - defaults maintain backward compatibility
    current_value: float | None = None
    threshold_value: float | None = None

    @property
    def is_allowed(self) -> bool:
        """Check if the action allows trading."""
        return self.action in (RuleAction.ALLOW, RuleAction.WARN)

    @property
    def is_blocked(self) -> bool:
        """Check if the action blocks trading."""
        return self.action == RuleAction.BLOCK
```

### Architecture Pattern: RuleEngine Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RULE ENGINE FLOW                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   Signal Generated                                                      │
│        │                                                                │
│        ▼                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                    RuleContextBuilder                            │  │
│   │   build_validation_context(account_id, signal, account_state)   │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│        │                                                                │
│        │ context: {account_id, symbol, side, quantity, balance,        │
│        │           equity, daily_pnl_percent, drawdown_percent, ...}   │
│        ▼                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                      RuleEngine                                  │  │
│   │                                                                  │  │
│   │   rules (sorted by priority):                                   │  │
│   │   ┌────────────────────────────────────────────────────────┐   │  │
│   │   │ [0] DailyLossLimit  (priority=1, critical)             │   │  │
│   │   │ [1] MaxDrawdown     (priority=2, critical)             │   │  │
│   │   │ [2] MaxPositionSize (priority=10)                      │   │  │
│   │   │ [3] ProfitTarget    (priority=100, notify-only)        │   │  │
│   │   └────────────────────────────────────────────────────────┘   │  │
│   │                                                                  │  │
│   │   validate(context):                                            │  │
│   │   ├── rule[0].validate(context) → ALLOW                        │  │
│   │   ├── rule[1].validate(context) → WARN (85% of limit)          │  │
│   │   ├── rule[2].validate(context) → BLOCK (size too large)       │  │
│   │   └── SHORT-CIRCUIT: Stop here, return BLOCK                   │  │
│   │                                                                  │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│        │                                                                │
│        │ RuleEngineResult:                                              │
│        │   action=BLOCK, blocked_by=MaxPositionSizeRule,               │
│        │   warnings=[MaxDrawdown WARN], evaluation_time_ms=12.5        │
│        ▼                                                                │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                   Execution Flow                                 │  │
│   │                                                                  │  │
│   │   if result.is_blocked:                                         │  │
│   │       log("Trade blocked: {result.blocking_reason}")            │  │
│   │       send_notification(...)                                     │  │
│   │       return  # Don't execute                                   │  │
│   │                                                                  │  │
│   │   if result.has_warnings:                                       │  │
│   │       for warn in result.warnings:                              │  │
│   │           send_notification(warn.message)                        │  │
│   │                                                                  │  │
│   │   # Proceed with trade execution                                │  │
│   │   zmq_adapter.send_order(...)                                   │  │
│   │                                                                  │  │
│   └─────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### RuleEngine Class Design

```python
# src/rules/engine.py
import logging
import time
from typing import TYPE_CHECKING, Any

from .base_rule import BaseRule, RuleAction, RuleResult
from .engine_result import RuleEngineResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type alias to reduce repetition
RuleList = list[BaseRule]


class RuleValidationError(Exception):
    """Raised when rule validation fails unexpectedly."""
    pass


class RuleEngine:
    """Engine that evaluates multiple rules against a trading context.

    The RuleEngine is the core component that:
    1. Maintains a sorted list of rules (by priority)
    2. Evaluates all rules against a trading context
    3. Aggregates results and determines final action
    4. Implements fail-safe behavior (errors = BLOCK)

    Attributes:
        account_id: The account this engine validates for
        rules: Sorted list of rules (critical first)
        strict_mode: If True, any error = BLOCK (default: True)
    """

    def __init__(
        self,
        account_id: str,
        rules: RuleList,
        strict_mode: bool = True,
    ):
        """Initialize RuleEngine for an account.

        Args:
            account_id: Account identifier this engine belongs to
            rules: List of rules to evaluate
            strict_mode: If True, rule errors cause BLOCK
        """
        self.account_id = account_id
        self.strict_mode = strict_mode

        # Sort rules by priority (lower = higher priority, evaluated first)
        # Python's sorted() is stable - equal priorities maintain insertion order
        self._rules = sorted(
            rules,
            key=lambda r: getattr(r, "priority", 50)
        )

        logger.info(
            f"RuleEngine initialized for account '{account_id}' "
            f"with {len(self._rules)} rules"
        )

    def validate(
        self,
        context: dict[str, Any],
        continue_after_block: bool = False,
    ) -> RuleEngineResult:
        """Validate a trading context against all rules.

        NOTE: This method is intentionally SYNCHRONOUS for performance.
        Async operations should happen before (build context) or after (log results).

        Args:
            context: Trading context with account state and signal info
            continue_after_block: If True, evaluate all rules even after BLOCK

        Returns:
            RuleEngineResult with combined action and details
        """
        start_time = time.perf_counter()
        all_results: list[tuple[BaseRule, RuleResult]] = []
        warnings: list[RuleResult] = []
        blocked_by: BaseRule | None = None
        blocking_reason: str | None = None

        for rule in self._rules:
            try:
                result = rule.validate(context)
                all_results.append((rule, result))

                if result.action == RuleAction.WARN:
                    warnings.append(result)
                    logger.warning(
                        f"Rule warning: {rule.rule_type} - {result.message}"
                    )

                if result.action == RuleAction.BLOCK:
                    blocked_by = rule
                    blocking_reason = result.message or f"Blocked by {rule.rule_type}"
                    logger.warning(
                        f"Rule BLOCKED trade: {rule.rule_type} - {blocking_reason}"
                    )

                    if not continue_after_block:
                        # Short-circuit: stop evaluating
                        logger.debug(
                            f"Short-circuit: stopping after {rule.rule_type}"
                        )
                        break

            except Exception as e:
                error_msg = f"Error in {rule.rule_type}: {e}"
                logger.exception(error_msg)

                if self.strict_mode:
                    # Fail-safe: error = BLOCK
                    error_result = RuleResult(
                        action=RuleAction.BLOCK,
                        message=error_msg,
                        metadata={"error": str(e), "rule_type": rule.rule_type},
                    )
                    all_results.append((rule, error_result))
                    blocked_by = rule
                    blocking_reason = error_msg
                    break

        evaluation_time_ms = (time.perf_counter() - start_time) * 1000

        # Determine final action
        if blocked_by is not None:
            final_action = RuleAction.BLOCK
        elif warnings:
            final_action = RuleAction.WARN
        else:
            final_action = RuleAction.ALLOW

        return RuleEngineResult(
            action=final_action,
            blocked_by=blocked_by,
            blocking_reason=blocking_reason,
            warnings=warnings,
            all_results=all_results,
            evaluation_time_ms=evaluation_time_ms,
        )

    def get_rules(self) -> RuleList:
        """Get the sorted list of rules.

        Returns:
            List of rules in priority order
        """
        return self._rules.copy()

    @property
    def rule_count(self) -> int:
        """Number of rules in this engine."""
        return len(self._rules)
```

### RuleEngineResult Dataclass Design

```python
# src/rules/engine_result.py
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base_rule import BaseRule, RuleAction, RuleResult

if TYPE_CHECKING:
    pass

# Type alias for rule evaluation tuple
RuleEvaluation = tuple[BaseRule, RuleResult]


@dataclass
class RuleEngineResult:
    """Result of evaluating all rules in a RuleEngine.

    Attributes:
        action: Final action (ALLOW, WARN, BLOCK)
        blocked_by: The rule that caused BLOCK, if any
        blocking_reason: Human-readable reason for block
        warnings: All WARN results collected
        all_results: All rule evaluations for audit
        evaluation_time_ms: Total evaluation time in milliseconds
    """

    action: RuleAction
    blocked_by: BaseRule | None = None
    blocking_reason: str | None = None
    warnings: list[RuleResult] = field(default_factory=list)
    all_results: list[RuleEvaluation] = field(default_factory=list)
    evaluation_time_ms: float = 0.0

    @property
    def is_allowed(self) -> bool:
        """Check if trading is allowed (ALLOW or WARN)."""
        return self.action in (RuleAction.ALLOW, RuleAction.WARN)

    @property
    def is_blocked(self) -> bool:
        """Check if trading is blocked."""
        return self.action == RuleAction.BLOCK

    @property
    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    @property
    def warning_messages(self) -> list[str]:
        """Get list of warning messages for notifications."""
        return [w.message for w in self.warnings if w.message]

    def get_summary(self) -> str:
        """Get human-readable summary for logging.

        Returns:
            Summary string with action, warnings, and timing
        """
        parts = [f"Action: {self.action.value}"]

        if self.blocked_by:
            parts.append(f"Blocked by: {self.blocked_by.rule_type}")

        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")

        parts.append(f"Rules evaluated: {len(self.all_results)}")
        parts.append(f"Time: {self.evaluation_time_ms:.2f}ms")

        return " | ".join(parts)
```

### Extended BaseRule Protocol

```python
# Updates to src/rules/base_rule.py - ADD to existing file

@runtime_checkable
class BaseRule(Protocol):
    """Protocol defining the interface for all trading rules.

    All rule implementations must satisfy this protocol by providing:
    - rule_type: String identifier for the rule type
    - name: Human-readable rule name
    - priority: Integer priority (lower = evaluated first)
    - validate(): Check context and return result
    - get_current_value(): Get current metric value
    - get_threshold(): Get configured threshold
    - get_warning_thresholds(): Get warning percentage thresholds
    """

    rule_type: str
    """Identifier for the rule type (e.g., 'daily_loss_limit')."""

    name: str
    """Human-readable name (e.g., 'Daily Loss Limit 5%')."""

    priority: int
    """Evaluation priority (lower = evaluated first, default: 50)."""

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate a trading context against this rule.

        Args:
            context: Dictionary containing trading context data

        Returns:
            RuleResult indicating whether trading should proceed
        """
        ...

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get the current value of the metric this rule monitors.

        Args:
            context: Trading context with current state

        Returns:
            Current value (e.g., current daily loss percent)
        """
        ...

    def get_threshold(self) -> float:
        """Get the threshold value for this rule.

        Returns:
            Threshold value (e.g., 5.0 for 5% daily loss limit)
        """
        ...

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [70, 80, 90])
        """
        ...
```

### RuleContextBuilder Design

```python
# src/rules/context_builder.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# Context keys documentation (for IDE support, consider TypedDict in future)
# Required: account_id, current_balance, current_equity
# Optional: signal, symbol, side, quantity, daily_pnl, daily_pnl_percent,
#           total_drawdown_percent, open_positions_count, total_exposure,
#           initial_balance, peak_balance, timestamp


@dataclass
class RuleContextBuilder:
    """Builder for creating rule validation contexts.

    Signal type: Any object with `symbol`, `side`, `quantity` attributes (duck typing).
    The builder extracts these via getattr() with fallback to account_state.

    Example:
        >>> builder = RuleContextBuilder()
        >>> context = builder.build_validation_context(
        ...     account_id="ftmo-001",
        ...     signal=signal_obj,
        ...     account_state={"balance": 100000, "equity": 99500},
        ... )
    """

    _custom_fields: dict[str, Any] = field(default_factory=dict)

    def build_validation_context(
        self,
        account_id: str,
        signal: Any,
        account_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a complete validation context.

        Args:
            account_id: Account identifier
            signal: Trading signal (any object with symbol/side/quantity attrs)
            account_state: Current account state (balance, equity, etc.)

        Returns:
            Context dictionary for rule validation
        """
        context = {
            # Account identification
            "account_id": account_id,
            "timestamp": datetime.utcnow(),

            # Signal information (duck typing - works with any signal type)
            "signal": signal,
            "symbol": getattr(signal, "symbol", account_state.get("symbol")),
            "side": getattr(signal, "side", account_state.get("side")),
            "quantity": getattr(signal, "quantity", account_state.get("quantity", 0.0)),

            # Account state
            "current_balance": account_state.get("balance", 0.0),
            "current_equity": account_state.get("equity", 0.0),
            "initial_balance": account_state.get("initial_balance", 0.0),
            "peak_balance": account_state.get("peak_balance", 0.0),

            # P&L metrics
            "daily_pnl": account_state.get("daily_pnl", 0.0),
            "daily_pnl_percent": account_state.get("daily_pnl_percent", 0.0),
            "total_drawdown_percent": account_state.get("total_drawdown_percent", 0.0),

            # Position info
            "open_positions_count": account_state.get("open_positions_count", 0),
            "total_exposure": account_state.get("total_exposure", 0.0),
        }

        # Add custom fields
        context.update(self._custom_fields)

        return context

    def add_custom_field(self, key: str, value: Any) -> "RuleContextBuilder":
        """Add a custom field to the context.

        Args:
            key: Field name
            value: Field value

        Returns:
            Self for chaining
        """
        self._custom_fields[key] = value
        return self

    def validate_context(self, context: dict[str, Any]) -> bool:
        """Validate that context has required fields.

        Args:
            context: Context dictionary to validate

        Returns:
            True if valid, raises ValueError otherwise
        """
        required = ["account_id", "current_balance", "current_equity"]

        missing = [f for f in required if f not in context]
        if missing:
            raise ValueError(f"Context missing required fields: {missing}")

        return True
```

### File Locations (Single Source of Truth)

All paths relative to `services/trading-engine/`:

| File | Action | Purpose |
|------|--------|---------|
| **Rules Module** | | |
| `src/rules/base_rule.py` | MODIFY | Extend BaseRule protocol, extend RuleResult |
| `src/rules/engine.py` | CREATE | RuleEngine, RuleValidationError |
| `src/rules/engine_result.py` | CREATE | RuleEngineResult dataclass |
| `src/rules/engine_factory.py` | CREATE | RuleEngineFactory class |
| `src/rules/context_builder.py` | CREATE | RuleContextBuilder class |
| `src/rules/__init__.py` | MODIFY | Add exports (see below) |
| **Accounts Module** | | |
| `src/accounts/account_manager.py` | MODIFY | Add `_rule_engines` dict, `get_rule_engine()` |
| **Tests** | | |
| `tests/unit/test_rule_engine.py` | CREATE | RuleEngine unit tests |
| `tests/unit/test_engine_result.py` | CREATE | RuleEngineResult unit tests |
| `tests/unit/test_context_builder.py` | CREATE | RuleContextBuilder unit tests |
| `tests/integration/test_rule_engine_flow.py` | CREATE | Full flow integration tests |

### Required __init__.py Exports

```python
# Add to src/rules/__init__.py
from .engine import RuleEngine, RuleValidationError
from .engine_result import RuleEngineResult
from .engine_factory import RuleEngineFactory
from .context_builder import RuleContextBuilder

__all__ = [
    # Existing exports from Story 3.7...
    # New exports for Story 4.1:
    "RuleEngine",
    "RuleValidationError",
    "RuleEngineResult",
    "RuleEngineFactory",
    "RuleContextBuilder",
]
```

### CLI Commands for Testing

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_rule_engine.py tests/unit/test_engine_result.py -v

# Run integration tests
uv run pytest tests/integration/test_rule_engine_flow.py -v

# Performance test (framework overhead only - tests < 50ms for 10 rules)
# NOTE: This tests framework overhead. Real rule performance tested in Stories 4.2-4.4
uv run python -c "
import time
from src.rules.engine import RuleEngine
from src.rules.base_rule import RuleAction, RuleResult

# Create mock rules (no real computation - tests framework only)
class MockRule:
    rule_type = 'mock'
    name = 'Mock Rule'
    priority = 50

    def validate(self, context):
        return RuleResult(action=RuleAction.ALLOW)

    def get_current_value(self, context):
        return 0.0

    def get_threshold(self):
        return 100.0

    def get_warning_thresholds(self):
        return [70, 80, 90]

rules = [MockRule() for _ in range(10)]
engine = RuleEngine('test-001', rules)

start = time.perf_counter()
result = engine.validate({'account_id': 'test-001'})
elapsed_ms = (time.perf_counter() - start) * 1000

print(f'Evaluation time: {elapsed_ms:.2f}ms')
assert elapsed_ms < 50, f'Performance target missed: {elapsed_ms}ms > 50ms'
print('Performance test PASSED')
"

# Verify no regressions
uv run pytest tests/ -v && uv run ruff check src/
```

### Anti-Patterns (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Evaluate rules in random order | Non-deterministic, critical rules may not run first | Always sort by priority (stable sort) |
| Silently swallow rule errors | Masks bugs, may allow invalid trades | Use fail-safe BLOCK in strict_mode |
| Continue after BLOCK by default | Wastes cycles, may cause confusion | Short-circuit by default, opt-in continue |
| Modify rules after engine creation | Rules are immutable for thread safety | Create new engine with new rules |
| Share RuleEngine between accounts | Cross-account rule state leakage | One RuleEngine per account |
| Skip logging rule evaluations | No audit trail for compliance | Log every evaluation (debug for ALLOW) |

### Performance Requirements (NFR2)

Source: [docs/prd.md#NFR2] - Non-Functional Requirements

- Rule validation must complete in < 50ms per check
- Target: 10 rules evaluated in < 50ms
- Use short-circuit on BLOCK to minimize overhead
- Avoid expensive operations in validation path (no DB/Redis in validate())

### NautilusTrader Risk Engine Alignment

**Key patterns from NautilusTrader (Context7 research 2025-12-31):**

```python
# NautilusTrader RiskEngineConfig pattern
RiskEngineConfig(
    bypass=False,           # Our: RuleEngine with no rules = bypass
    max_order_rate="100/00:00:01",  # Our: Separate frequency rule
    max_notional_per_order={"INSTRUMENT": 100000},  # Our: MaxPositionSizeRule
    debug=False,            # Our: verbose logging option
)
```

**Alignment:**
- Our `RuleEngine` mirrors NautilusTrader's `RiskEngine` concept
- Our `RuleEngineResult` is similar to their validation result pattern
- Our fail-safe behavior (error = BLOCK) matches their conservative approach
- Our priority ordering ensures critical rules (drawdown) are checked first

### References

- [docs/architecture.md#Pluggable-Rule-Engine] - Rule engine architecture
- [docs/architecture.md#Rule-Types] - Rule type definitions
- [docs/epics.md#Epic-4] - Epic 4 requirements (Story 4.1)
- [docs/sprint-artifacts/3-7-account-rule-assignment.md] - BaseRule protocol, RuleAssignmentService
- [docs/prd.md#NFR2] - Performance requirement: < 50ms
- [docs/prd.md#FR12] - Rule real-time evaluation requirement
- [Context7 NautilusTrader 2025-12-31] - RiskEngine patterns

## Dev Agent Record

**Story created:** Epic 4 analysis, Architecture analysis, Story 3.7 patterns, Context7 NautilusTrader research

**Agent Model:** Claude Opus 4.5 (claude-opus-4-5-20251101)

**Implementation Notes:**
- FIRST story in Epic 4 (FTMO Compliance Rule Engine)
- Focuses on FRAMEWORK, not specific rule implementations
- Story 3.7 created BaseRule placeholder; this story EXTENDS it
- Stories 4.2-4.4 implement specific rule types (DailyLossLimit, MaxDrawdown, etc.)
- Story 4.6 integrates RuleEngine with execution flow

**Completion Notes (2025-12-31):**
- Extended BaseRule protocol with name, priority, get_current_value(), get_threshold(), get_warning_thresholds()
- Extended RuleResult with current_value and threshold_value optional fields
- Created RuleEngine with priority sorting, short-circuit on BLOCK, warning aggregation, fail-safe error handling
- Created RuleEngineResult with is_allowed, is_blocked, has_warnings, warning_messages, get_summary()
- Created RuleEngineFactory for account-specific engine creation with protocol validation
- Created RuleContextBuilder with duck-typed signal extraction and custom field support
- Integrated with AccountManager: _rule_engines dict, get_rule_engine(), automatic creation during _initialize_account_rules()
- Updated placeholder rules in parser.py to implement full BaseRule protocol
- 77 unit tests + 14 integration tests all pass
- Performance: 10 rules validate in < 1ms (well under 50ms target)

## File List

**New Files (Created):**
- `src/rules/engine.py` - RuleEngine class, RuleValidationError exception
- `src/rules/engine_result.py` - RuleEngineResult dataclass
- `src/rules/engine_factory.py` - RuleEngineFactory class
- `src/rules/context_builder.py` - RuleContextBuilder class
- `tests/unit/test_rule_engine.py` - RuleEngine unit tests (33 tests)
- `tests/unit/test_engine_result.py` - RuleEngineResult unit tests (19 tests)
- `tests/unit/test_engine_factory.py` - RuleEngineFactory unit tests (12 tests)
- `tests/unit/test_context_builder.py` - RuleContextBuilder unit tests (19 tests)
- `tests/integration/test_rule_engine_flow.py` - Integration tests (14 tests)

**Modified Files:**
- `src/rules/base_rule.py` - Extended BaseRule protocol with name, priority, new methods; Extended RuleResult with current_value, threshold_value
- `src/rules/__init__.py` - Added exports for new classes
- `src/rules/parser.py` - Updated placeholder rules to implement full BaseRule protocol
- `src/accounts/account_manager.py` - Added _rule_engines dict, get_rule_engine() method, RuleEngine creation in _initialize_account_rules()
- `tests/unit/test_rule_assignment.py` - Updated test_protocol_compliance for new BaseRule protocol
- `docs/sprint-artifacts/sprint-status.yaml` - Updated story status tracking

## Change Log

| Date | Change |
|------|--------|
| 2025-12-31 | Story 4.1 implementation complete - Rule Engine Framework |
| 2025-12-31 | Code review fixes: Added clear_custom_fields() to RuleContextBuilder, improved logging consistency, cleaned up unused imports, enhanced documentation, added new tests |

---

## Definition of Done

**Core Implementation:**
- [x] BaseRule protocol extended with get_current_value(), get_threshold(), get_warning_thresholds(), priority, name
- [x] RuleResult extended with current_value, threshold_value (optional fields)
- [x] RuleEngine class created with validate(), short-circuit, fail-safe behavior
- [x] RuleEngineResult dataclass created with all properties
- [x] RuleEngineFactory created for account-specific engine creation
- [x] RuleContextBuilder created for validation context construction

**Integration:**
- [x] AccountManager extended with _rule_engines dict
- [x] RuleEngine created for each account after rule assignment
- [x] get_rule_engine(account_id) method added to AccountManager

**Acceptance Criteria Verification:**
- [x] AC1: New rule types can implement extended BaseRule protocol
- [x] AC2: RuleEngine evaluates all rules before execution
- [x] AC3: BLOCK result stops evaluation and logs reason
- [x] AC4: WARN results collected and trade proceeds
- [x] AC5: Rules evaluated in priority order (stable sort for ties)
- [x] AC6: Errors in rules result in BLOCK (fail-safe)

**Testing:**
- [x] Unit tests cover RuleEngine priority sorting (including tie-breaking)
- [x] Unit tests cover short-circuit behavior
- [x] Unit tests cover warning aggregation
- [x] Unit tests cover fail-safe error handling
- [x] Integration tests verify full AccountManager -> RuleEngine flow
- [x] Performance test: 10 rules < 50ms (framework overhead)
- [x] All existing tests still pass
- [x] Code passes: `uv run ruff check src/rules/`

---

### Validation Notes (2025-12-31)

**Story validated via validate-create-story workflow. Applied improvements:**

| ID | Type | Description |
|----|------|-------------|
| C1 | Critical | Added explicit RuleResult extension guidance (Task 1.6) - extend with defaults, don't replace |
| C2 | Critical | Added signal type guidance in RuleContextBuilder - duck typing with symbol/side/quantity |
| E1 | Enhancement | Added tie-breaking clarification for equal priorities (stable sort) |
| E2 | Enhancement | Added performance benchmark context note (framework overhead only) |
| E3 | Enhancement | Clarified Task 8 extends existing `_initialize_account_rules()`, doesn't recreate |
| E4 | Enhancement | Added explicit `__init__.py` exports section |
| E5 | Enhancement | Added sync vs async design decision note |
| O1 | Optimization | Added RuleList and RuleEvaluation type aliases |
| O2 | Optimization | Added logging level guidance (debug/warning/exception) |
| O3 | Optimization | Added context keys documentation comment |
| O4 | Optimization | Added NFR2 source link to docs/prd.md |
| L1 | LLM Opt | Tasks now reference code sections instead of duplicating |
| L2 | LLM Opt | Consolidated file locations to single table |
| L3 | LLM Opt | Anti-patterns now include "Instead, do this" column |
| L4 | LLM Opt | Consolidated Context Reference into Dev Agent Record |

**Validation Score:** All improvements applied.
