# Story 4.4: Position Size Limit Rule

Status: Ready for Review

## Story

As a **trader**,
I want **position sizes limited per my account rules**,
So that **I don't take on excessive risk per trade**.

## Acceptance Criteria

1. **AC1**: Given an account with max position size of 1.0 lots, when a signal requests 1.5 lots, then the trade is BLOCKED with reason: "Position size 1.5 exceeds limit 1.0 lots".

2. **AC2**: Given a signal requests 0.5 lots, when the rule evaluates, then the trade is ALLOWED.

3. **AC3**: Given an account with scaling rule "1 lot per $10k balance", when balance is $50,000 and signal requests 6.0 lots, then the trade is BLOCKED (max allowed: 5.0 lots).

4. **AC4**: Given I have an existing 0.5 lot position, when a signal requests 0.8 lots (total would be 1.3 lots), then the trade is BLOCKED based on total exposure.

5. **AC5**: Given a signal requests exactly the maximum allowed (1.0 lots with 1.0 limit), then the trade is ALLOWED.

6. **AC6**: Given warning thresholds [70, 80, 90], when signal requests 0.8 lots of 1.0 lot limit (80% usage), then a WARNING is generated.

## Tasks / Subtasks

### Task 1: Create MaxPositionSizeRule Class (AC: 1, 2, 5)

- [x] 1.1: Create new file `src/rules/types/position.py` for position-related rules
- [x] 1.2: Implement `MaxPositionSizeRule` class with attributes:
  - `rule_type = "max_position_size"` (matches YAML type)
  - `priority = 3` (evaluated after drawdown rules)
- [x] 1.3: Constructor parameters: `max_lots: float`, `scaling: str | None = None`, `warning_at: list[float] | None = None`, `action: str = "block_trading"`, `**kwargs`
- [x] 1.4: Implement `name` property returning `f"Position Size Limit {max_lots} lots"`

### Task 2: Implement validate() Method - Basic Check (AC: 1, 2, 5)

- [x] 2.1: Extract `requested_lots` from context (new order size)
- [x] 2.2: Extract `current_position_lots` from context (existing open positions)
- [x] 2.3: Calculate `total_exposure = current_position_lots + requested_lots`
- [x] 2.4: If `requested_lots > max_lots`: return BLOCK with message
- [x] 2.5: If at or below max: return ALLOW
- [x] 2.6: Include `current_value` and `threshold_value` in RuleResult

### Task 3: Implement Scaling Logic (AC: 3)

- [x] 3.1: Extract `account_balance` from context
- [x] 3.2: If `scaling == "per_10k_balance"`: calculate `effective_max = (balance / 10000) * base_max_lots`
- [x] 3.3: Support other scaling modes: `None` (fixed), `"per_10k_balance"`, potentially more
- [x] 3.4: Use `effective_max` instead of `max_lots` when scaling is enabled
- [x] 3.5: Validate scaling string format and log warning for unknown scaling modes

### Task 4: Implement Total Exposure Check (AC: 4)

- [x] 4.1: Calculate total exposure: `current_position_lots + requested_lots`
- [x] 4.2: If total exposure exceeds effective max: return BLOCK
- [x] 4.3: Message should clarify: "Total exposure X.X lots would exceed limit Y.Y lots (current: C.C + requested: R.R)"
- [x] 4.4: Handle both new positions and additions to existing positions

### Task 5: Implement Warning Thresholds (AC: 6)

- [x] 5.1: Default warning thresholds: `[70, 80, 90]` (percentages of limit)
- [x] 5.2: Calculate usage percent: `(total_exposure / effective_max) * 100`
- [x] 5.3: If at warning threshold but not blocking: return WARN with message
- [x] 5.4: Return highest applicable warning threshold

### Task 6: Implement Protocol Methods (AC: 1-6)

- [x] 6.1: Implement `get_current_value(context)` -> returns total exposure from context
- [x] 6.2: Implement `get_threshold()` -> returns `self.max_lots` (base, not scaled)
- [x] 6.3: Implement `get_warning_thresholds()` -> returns `self.warning_at.copy()`

### Task 7: Update Module Exports (AC: 1-6)

- [x] 7.1: Create `src/rules/types/position.py` with MaxPositionSizeRule
- [x] 7.2: Add `MaxPositionSizeRule` to `src/rules/types/__init__.py` exports
- [x] 7.3: Add `MaxPositionSizeRule` to `src/rules/__init__.py` exports
- [x] 7.4: Verify `src/rules/parser.py` lazy import works (parser already expects `MaxPositionSizeRule` - no changes needed if class name matches)

### Task 8: Unit Tests (AC: 1-6)

- [x] 8.1: Create `tests/unit/test_max_position_size_rule.py`
- [x] 8.2: Test ALLOW when below limit (0.5 of 1.0)
- [x] 8.3: Test ALLOW when exactly at limit (1.0 of 1.0)
- [x] 8.4: Test BLOCK when above limit (1.5 of 1.0)
- [x] 8.5: Test scaling with "per_10k_balance" - ALLOW case ($50k = 5.0 max, request 4.0)
- [x] 8.6: Test scaling with "per_10k_balance" - BLOCK case ($50k = 5.0 max, request 6.0)
- [x] 8.7: Test total exposure blocking (0.5 existing + 0.8 requested > 1.0 limit)
- [x] 8.8: Test WARN at 70% threshold
- [x] 8.9: Test WARN at 80% threshold
- [x] 8.10: Test WARN at 90% threshold
- [x] 8.11: Test with custom warning thresholds
- [x] 8.12: Test RuleResult includes correct current_value and threshold_value
- [x] 8.13: Test get_current_value(), get_threshold(), get_warning_thresholds()
- [x] 8.14: Test invalid max_lots <= 0 logs warning

### Task 9: Integration Tests (AC: 1-6)

- [x] 9.1: Create `tests/integration/test_max_position_size_integration.py`
- [x] 9.2: Test RuleEngine with MaxPositionSizeRule validates signals correctly
- [x] 9.3: Test RuleEngine short-circuits on BLOCK from MaxPositionSizeRule
- [x] 9.4: Test loading from YAML parser creates correct MaxPositionSizeRule (FTMO preset doesn't have max_position_size rule yet - tested via RuleParser)
- [x] 9.5: Test multiple rules together (DailyLoss + MaxDrawdown + PositionSize)
- [x] 9.6: Test scaling rule loaded from YAML correctly

### Task 10: Documentation and Logging (AC: 1-6)

- [x] 10.1: Add comprehensive docstrings to MaxPositionSizeRule class and methods
- [x] 10.2: Add logging for BLOCK decisions at WARNING level
- [x] 10.3: Add logging for WARN decisions at WARNING level
- [x] 10.4: Add logging for ALLOW decisions at DEBUG level
- [x] 10.5: Include example usage in class docstring

## Dev Notes

### CRITICAL DEPENDENCIES & PREREQUISITES

**Story 4.1 Foundation (COMPLETE):**
This story builds directly on Story 4.1 (Rule Engine Framework) which created:
- `BaseRule` protocol in `src/rules/base_rule.py` with:
  - `rule_type: str`, `name: str`, `priority: int` attributes
  - `validate(context) -> RuleResult` method
  - `get_current_value(context) -> float` method
  - `get_threshold() -> float` method
  - `get_warning_thresholds() -> list[float]` method
- `RuleAction` enum: ALLOW, WARN, BLOCK
- `RuleResult` dataclass with: action, message, metadata, current_value, threshold_value
- `RuleEngine` class with priority sorting and short-circuit on BLOCK
- `RuleEngineResult` with is_allowed, is_blocked, has_warnings, warning_messages
- `RuleContextBuilder` for building validation contexts
- `RuleParser` with placeholder support for rule types

**Story 4.2 & 4.3 Foundation (COMPLETE):**
DailyLossLimitRule and MaxDrawdownRule implementations provide the pattern to follow:
- Class structure: rule_type, priority, constructor, validate(), protocol methods
- Logging patterns: WARNING for BLOCK/WARN, DEBUG for ALLOW
- Test structure: unit tests + integration tests
- File organization: `src/rules/types/` directory

**Story 3.6 Foundation (COMPLETE):**
Account metrics tracking:
- `RiskState` dataclass in `src/accounts/risk_state.py`
- `RiskStateRegistry` for per-account risk state management

**Dependencies:**
- Story 4.1: Rule Engine Framework (COMPLETE)
- Story 4.2: Daily Loss Limit Rule (COMPLETE) - **PATTERN TO FOLLOW**
- Story 4.3: Max Drawdown Rule (COMPLETE) - **PATTERN TO FOLLOW**
- Story 3.6: Per-Account Equity and Balance Tracking (COMPLETE)
- Story 3.7: Account Rule Assignment (COMPLETE) - **Established `MaxPositionSizeRule` naming convention in parser.py**

**Subsequent Stories Depend On:**
- Story 4.5: FTMO Preset Configuration (uses this rule)
- Story 4.6: Rule Validation Before Trade (integrates with execution flow)

### Task Dependencies

```
Task 1 (Create MaxPositionSizeRule class)
    |
Task 2 (Basic validate logic)
    |
    +-- Task 3 (Scaling logic)
    |
    +-- Task 4 (Total exposure check)
    |
    +-- Task 5 (Warning thresholds)
    |
Task 6 (Protocol methods)
    |
Task 7 (Module exports)
    |
Task 8 (Unit tests) --> Task 9 (Integration tests)
    |
Task 10 (Documentation)
```

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Decimal:** Use `decimal.Decimal` for all financial calculations (precision)
- **Existing Modules:** `src/rules/`, `src/accounts/`
- **Test Framework:** pytest with fixtures from Story 4.1-4.3

### Key Design Decisions

**Position Size vs Notional Value:**
- This rule checks **lot sizes** (volume), not notional value
- NautilusTrader's RiskEngine uses `max_notional_per_order` for notional checks
- Our rule is complementary - FTMO and prop firms use lot-based limits

**Scaling Modes:**
- `None` or `"fixed"`: Use max_lots as-is
- `"per_10k_balance"`: Scale limit based on account balance
  - Formula: `effective_max = (balance / 10000) * base_lot_factor`
  - Example: $50k balance with 1.0 base = 5.0 lots max

**Total Exposure Check:**
- CRITICAL: Must consider EXISTING positions + NEW order
- Get `current_position_lots` from context (sum of all open positions for this account)
- Calculate total: `current + requested`
- Block if total exceeds limit

**Sync vs Async:**
`MaxPositionSizeRule.validate()` is **synchronous** per the RuleEngine design from Story 4.1. Position data is passed via context dict - async queries happen OUTSIDE the validate loop (in RuleContextBuilder).

**Context Keys Required:**
The calling code (or RuleContextBuilder) must provide:
```python
context = {
    "requested_lots": 0.5,           # The order being validated
    "current_position_lots": 0.5,    # Existing open position size
    "account_balance": 50000.0,      # For scaling calculation
    "account_id": "ftmo-gold-001",   # For logging
}
```

**Warning Threshold Behavior:**
Same as other rules - returns HIGHEST applicable warning per validate() call:
- At 75% usage -> returns 70% warning
- At 85% usage -> returns 80% warning
- At 95% usage -> returns 90% warning

**Logging Levels:**
- ALLOW results: `logger.debug()` (high volume)
- WARN results: `logger.warning()` (important notification trigger)
- BLOCK results: `logger.warning()` (critical, trade stopped)

### MaxPositionSizeRule Class Design

**Key Implementation Points:**
- Class name: `MaxPositionSizeRule` (matches parser.py lazy import from Story 3.7)
- rule_type: `"max_position_size"` (matches YAML config)
- priority: `3` (after daily loss and max drawdown)
- Supports fixed and scaled (`per_10k_balance`) limits
- Checks both single order size AND total exposure (existing + new)

```python
# src/rules/types/position.py - NEW FILE

"""Position-related rule implementations.

This module contains rules for monitoring and limiting position sizes:
- MaxPositionSizeRule: Blocks trades when position size exceeds limit (Story 4.4)
"""

import logging
from decimal import Decimal
from typing import Any

from ..base_rule import RuleAction, RuleResult

logger = logging.getLogger(__name__)


class MaxPositionSizeRule:
    """Position size limit rule - blocks trades when position size exceeds limit.

    FTMO Default: 100 lots with scaling "per_10k_balance" (1 lot per $10k).

    This rule monitors requested trade sizes and total exposure, and:
    - BLOCKS trading when position size exceeds the calculated limit
    - WARNS when approaching the limit (configurable warning levels)
    - ALLOWS trading when safely below all thresholds

    Supports two modes:
    1. Fixed limit: max_lots is used directly
    2. Scaled limit: max_lots is adjusted based on account balance

    Attributes:
        rule_type: "max_position_size"
        name: Human-readable name with limit (e.g., "Position Size Limit 1.0 lots")
        priority: 3 (evaluated after drawdown rules)
        max_lots: Maximum allowed position size in lots
        scaling: Scaling mode ("per_10k_balance" or None for fixed)
        warning_at: List of warning percentages (default: [70, 80, 90])

    Example:
        >>> rule = MaxPositionSizeRule(max_lots=1.0)
        >>> context = {"requested_lots": 0.5, "current_position_lots": 0.0}
        >>> result = rule.validate(context)
        >>> result.action  # Returns ALLOW
        <RuleAction.ALLOW: 'allow'>

        >>> context = {"requested_lots": 1.5, "current_position_lots": 0.0}
        >>> result = rule.validate(context)
        >>> result.action  # Returns BLOCK
        <RuleAction.BLOCK: 'block'>
    """

    rule_type: str = "max_position_size"
    priority: int = 3  # After daily loss (1) and max drawdown (2)

    def __init__(
        self,
        max_lots: float = 1.0,
        scaling: str | None = None,
        warning_at: list[float] | None = None,
        action: str = "block_trading",  # From YAML, for documentation
        **kwargs: Any,  # Accept additional YAML fields
    ) -> None:
        """Initialize MaxPositionSizeRule.

        Args:
            max_lots: Maximum position size in lots (default: 1.0).
                For scaling mode, this is the base multiplier.
            scaling: Scaling mode for dynamic limits:
                - None or "fixed": Use max_lots directly
                - "per_10k_balance": Scale by account balance (1 lot per $10k)
            warning_at: Warning thresholds as percentages of limit.
                Default: [70, 80, 90] means warn at 70%, 80%, 90% of limit.
            action: Action to take (for YAML compatibility, always blocks).
            **kwargs: Additional YAML fields (ignored for forward compatibility).
        """
        self.max_lots = float(max_lots)
        self.scaling = scaling
        self.warning_at = sorted(
            warning_at if warning_at is not None else [70.0, 80.0, 90.0]
        )

        # Validate max_lots - must be positive
        if self.max_lots <= 0:
            logger.warning(
                "MaxPositionSizeRule created with invalid max_lots=%.2f. "
                "Limit must be > 0. This will block all trades.",
                self.max_lots,
            )

        # Validate scaling mode
        valid_scaling = [None, "fixed", "per_10k_balance"]
        if self.scaling is not None and self.scaling not in valid_scaling:
            logger.warning(
                "Unknown scaling mode '%s'. Supported: %s. Using fixed limit.",
                self.scaling,
                valid_scaling,
            )
            self.scaling = None

    @property
    def name(self) -> str:
        """Human-readable name with limit."""
        if self.scaling == "per_10k_balance":
            return f"Position Size Limit (scaled: {self.max_lots} lots per $10k)"
        return f"Position Size Limit {self.max_lots} lots"

    def _calculate_effective_max(self, context: dict[str, Any]) -> float:
        """Calculate effective max lots considering scaling.

        Args:
            context: Trading context with account_balance if scaling enabled.

        Returns:
            Effective max lots (scaled or fixed).
        """
        if self.scaling == "per_10k_balance":
            account_balance = context.get("account_balance", 0.0)
            if isinstance(account_balance, Decimal):
                account_balance = float(account_balance)

            if account_balance <= 0:
                logger.warning(
                    "Invalid account_balance %.2f for scaling. Using fixed limit.",
                    account_balance,
                )
                return self.max_lots

            # Scale: 1 lot per $10k of balance * base multiplier
            effective_max = (account_balance / 10000.0) * self.max_lots
            logger.debug(
                "Scaled position limit: $%.2f / $10k * %.2f = %.2f lots max",
                account_balance,
                self.max_lots,
                effective_max,
            )
            return effective_max

        return self.max_lots

    def validate(self, context: dict[str, Any]) -> RuleResult:
        """Validate trading context against position size limit.

        Checks both the requested order size and total exposure (existing + new)
        against the configured limit. Returns appropriate action.

        Args:
            context: Trading context with position size keys.
                Expected keys:
                - requested_lots (float|Decimal): Size of the order being validated
                - current_position_lots (float|Decimal): Existing open position size
                - account_balance (float|Decimal): For scaling calculation (optional)

        Returns:
            RuleResult with:
            - BLOCK if size exceeds limit
            - WARN if approaching limit (at warning level)
            - ALLOW if safely below all thresholds
        """
        # Extract values from context
        requested_lots = context.get("requested_lots", 0.0)
        current_position_lots = context.get("current_position_lots", 0.0)

        # Convert Decimal to float
        if isinstance(requested_lots, Decimal):
            requested_lots = float(requested_lots)
        if isinstance(current_position_lots, Decimal):
            current_position_lots = float(current_position_lots)

        # Calculate effective limit (may be scaled)
        effective_max = self._calculate_effective_max(context)

        # Calculate total exposure
        total_exposure = abs(current_position_lots) + abs(requested_lots)

        # If no request, always allow
        if requested_lots <= 0:
            logger.debug(
                "Position size ALLOWED: no position requested (%.2f lots)",
                requested_lots,
            )
            return RuleResult(
                action=RuleAction.ALLOW,
                current_value=total_exposure,
                threshold_value=effective_max,
            )

        # Check if single order exceeds limit (even without existing positions)
        if requested_lots > effective_max:
            logger.warning(
                "Position size BLOCKED: requested %.2f lots > %.2f lots limit",
                requested_lots,
                effective_max,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Position size {requested_lots:.2f} lots "
                    f"exceeds limit of {effective_max:.2f} lots"
                ),
                current_value=requested_lots,
                threshold_value=effective_max,
                metadata={
                    "rule_type": self.rule_type,
                    "requested_lots": requested_lots,
                    "effective_max": effective_max,
                    "scaling": self.scaling,
                },
            )

        # Check total exposure (existing + new)
        if total_exposure > effective_max:
            logger.warning(
                "Position size BLOCKED: total exposure %.2f lots > %.2f lots limit "
                "(current: %.2f + requested: %.2f)",
                total_exposure,
                effective_max,
                current_position_lots,
                requested_lots,
            )
            return RuleResult(
                action=RuleAction.BLOCK,
                message=(
                    f"Total exposure {total_exposure:.2f} lots would exceed limit "
                    f"of {effective_max:.2f} lots "
                    f"(current: {current_position_lots:.2f} + requested: {requested_lots:.2f})"
                ),
                current_value=total_exposure,
                threshold_value=effective_max,
                metadata={
                    "rule_type": self.rule_type,
                    "requested_lots": requested_lots,
                    "current_position_lots": current_position_lots,
                    "total_exposure": total_exposure,
                    "effective_max": effective_max,
                    "scaling": self.scaling,
                },
            )

        # Check warning thresholds based on total exposure
        usage_percent = (total_exposure / effective_max) * 100 if effective_max > 0 else 100
        for warning_threshold in sorted(self.warning_at, reverse=True):
            if usage_percent >= warning_threshold:
                logger.warning(
                    "Position size WARNING: at %.1f%% of limit (%.2f of %.2f lots)",
                    usage_percent,
                    total_exposure,
                    effective_max,
                )
                return RuleResult(
                    action=RuleAction.WARN,
                    message=(
                        f"Position size at {usage_percent:.0f}% of "
                        f"{effective_max:.2f} lots limit ({total_exposure:.2f} lots)"
                    ),
                    current_value=total_exposure,
                    threshold_value=effective_max,
                    metadata={
                        "rule_type": self.rule_type,
                        "warning_threshold": warning_threshold,
                        "usage_percent": usage_percent,
                    },
                )

        # Below all thresholds - ALLOW
        logger.debug(
            "Position size ALLOWED: %.2f lots < %.2f lots limit",
            total_exposure,
            effective_max,
        )
        return RuleResult(
            action=RuleAction.ALLOW,
            current_value=total_exposure,
            threshold_value=effective_max,
        )

    def get_current_value(self, context: dict[str, Any]) -> float:
        """Get total position exposure from context.

        Args:
            context: Trading context with position size keys.

        Returns:
            Total exposure in lots (current + requested).
        """
        requested_lots = context.get("requested_lots", 0.0)
        current_position_lots = context.get("current_position_lots", 0.0)

        if isinstance(requested_lots, Decimal):
            requested_lots = float(requested_lots)
        if isinstance(current_position_lots, Decimal):
            current_position_lots = float(current_position_lots)

        return abs(current_position_lots) + abs(requested_lots)

    def get_threshold(self) -> float:
        """Get the base position size limit.

        Returns:
            Base max_lots (not scaled). For scaled limit, use validate().
        """
        return self.max_lots

    def get_warning_thresholds(self) -> list[float]:
        """Get warning threshold percentages.

        Returns:
            List of percentages at which to warn (e.g., [70.0, 80.0, 90.0]).
        """
        return self.warning_at.copy()

    def __repr__(self) -> str:
        """Return string representation for debugging."""
        return (
            f"MaxPositionSizeRule(max_lots={self.max_lots}, "
            f"scaling={self.scaling}, "
            f"warnings={self.warning_at})"
        )
```

### File Locations (Single Source of Truth)

All paths relative to `services/trading-engine/`:

| File | Action | Purpose |
|------|--------|---------|
| **Rules Module** | | |
| `src/rules/types/position.py` | **CREATE** | New file for MaxPositionSizeRule |
| `src/rules/types/__init__.py` | MODIFY | Add MaxPositionSizeRule to exports |
| `src/rules/__init__.py` | MODIFY | Add MaxPositionSizeRule to exports |
| `src/rules/parser.py` | VERIFY | Lazy import already expects MaxPositionSizeRule (Story 3.7) |
| **Tests** | | |
| `tests/unit/test_max_position_size_rule.py` | CREATE | Unit tests for rule |
| `tests/integration/test_max_position_size_integration.py` | CREATE | Integration tests |

### Required __init__.py Updates

```python
# src/rules/types/__init__.py - ADD to existing exports
from .drawdown import DailyLossLimitRule, MaxDrawdownRule
from .position import MaxPositionSizeRule

__all__ = [
    "DailyLossLimitRule",
    "MaxDrawdownRule",
    "MaxPositionSizeRule",
]

# src/rules/__init__.py - ADD to existing exports
from .types.drawdown import DailyLossLimitRule, MaxDrawdownRule
from .types.position import MaxPositionSizeRule

__all__ = [
    # ... existing exports ...
    "DailyLossLimitRule",
    "MaxDrawdownRule",
    "MaxPositionSizeRule",
]
```

### parser.py Status (No Changes Required)

The `parser.py` file already has lazy import configured from Story 3.7:

```python
# src/rules/parser.py - ALREADY CONFIGURED (lines 128-131)
try:
    from .types.position import MaxPositionSizeRule
    self._rule_types["max_position_size"] = MaxPositionSizeRule
    logger.debug("Loaded MaxPositionSizeRule")
except ImportError:
    pass  # Uses placeholder until position.py is created
```

**No modifications needed** - once `position.py` is created with `MaxPositionSizeRule`, the lazy import will automatically work.

### CLI Commands for Testing

```bash
cd services/trading-engine

# Run unit tests
uv run pytest tests/unit/test_max_position_size_rule.py -v

# Run integration tests
uv run pytest tests/integration/test_max_position_size_integration.py -v

# Run all position rule tests
uv run pytest tests/ -k "position" -v

# Quick validation test
uv run python -c "
from src.rules.types.position import MaxPositionSizeRule
from src.rules.base_rule import RuleAction

# Test ALLOW
rule = MaxPositionSizeRule(max_lots=1.0)
result = rule.validate({'requested_lots': 0.5, 'current_position_lots': 0.0})
assert result.action == RuleAction.ALLOW, 'Expected ALLOW for 0.5 lots'
print('ALLOW test passed: 0.5 lots is allowed')

# Test BLOCK - single order
result = rule.validate({'requested_lots': 1.5, 'current_position_lots': 0.0})
assert result.action == RuleAction.BLOCK, 'Expected BLOCK for 1.5 lots'
print('BLOCK test passed: 1.5 lots is blocked')

# Test BLOCK - total exposure
result = rule.validate({'requested_lots': 0.8, 'current_position_lots': 0.5})
assert result.action == RuleAction.BLOCK, 'Expected BLOCK for total 1.3 lots'
print('BLOCK test passed: total exposure 1.3 lots is blocked')

# Test scaling
rule_scaled = MaxPositionSizeRule(max_lots=1.0, scaling='per_10k_balance')
result = rule_scaled.validate({
    'requested_lots': 4.0,
    'current_position_lots': 0.0,
    'account_balance': 50000.0
})
assert result.action == RuleAction.ALLOW, 'Expected ALLOW with scaling (50k = 5.0 max)'
print('SCALING test passed: 4.0 lots allowed with \$50k balance')

result = rule_scaled.validate({
    'requested_lots': 6.0,
    'current_position_lots': 0.0,
    'account_balance': 50000.0
})
assert result.action == RuleAction.BLOCK, 'Expected BLOCK with scaling (50k = 5.0 max)'
print('SCALING test passed: 6.0 lots blocked with \$50k balance')

print('All validation tests PASSED')
"

# Verify no regressions
uv run pytest tests/ -v && uv run ruff check src/
```

### Anti-Patterns (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Query MT5 for positions in validate() | Violates sync design, slow | Pass data via context dict |
| Ignore existing positions | Allows over-exposure | Always calculate total exposure |
| Use float for lot calculations | Precision issues | Use Decimal or round consistently |
| Hardcode 1.0 lot limit | Not configurable | Accept max_lots as constructor param |
| Log at INFO for every ALLOW | Log spam, performance | Use DEBUG for ALLOW |
| Confuse lots with notional | Different metrics | This rule uses lots (volume) |
| Forget scaling when validating | Incorrect limit applied | Always call _calculate_effective_max() |

### Performance Requirements (NFR2)

Source: [docs/prd.md#NFR2] - Non-Functional Requirements

- Rule validation must complete in < 50ms per check
- `MaxPositionSizeRule.validate()` should complete in < 5ms (simple comparisons)
- No I/O operations in validate() - all data via context dict

### Context Keys Used

From `RuleContextBuilder.build_validation_context()`:

| Key | Type | Description | Source |
|-----|------|-------------|--------|
| `requested_lots` | float/Decimal | Size of order being validated | Order request |
| `current_position_lots` | float/Decimal | Existing open position size | Portfolio/Cache |
| `account_balance` | float/Decimal | Current account balance | Account state |
| `account_id` | str | Account identifier | Required |

### FTMO Preset Configuration

From `src/rules/presets/ftmo.yaml`:
```yaml
- type: max_position_size
  max_lots: 100.0  # Base multiplier
  scaling: "per_10k_balance"  # 1 lot per $10k
```

Example calculations:
- $10,000 balance: 1.0 lot max
- $50,000 balance: 5.0 lots max
- $100,000 balance: 10.0 lots max

### NautilusTrader Alignment (Context7 Research 2025-12-31)

NautilusTrader's RiskEngine provides complementary risk management:

**What NautilusTrader Provides:**
- `max_notional_per_order`: Maximum notional value per order (USD value)
- `max_order_submit_rate`: Rate limiting for order submission
- `FixedRiskSizer`: Position sizing based on risk percentage and stop loss
- `hard_limit` parameter: Absolute maximum quantity

**What Our Rule Adds:**
- **Lot-based limits**: FTMO and prop firms specify limits in lots, not notional
- **Scaling by balance**: Dynamic limits that adjust with account size
- **Total exposure tracking**: Consider existing positions + new orders
- **Warning thresholds**: Alert before hitting hard limit
- **Integration with RuleEngine**: Unified validation pipeline

**Synergy:**
Our `MaxPositionSizeRule` works alongside NautilusTrader's risk checks:
1. NautilusTrader handles notional limits and rate limiting
2. Our rule handles lot-based limits and prop firm compliance
3. Both can be active simultaneously for layered protection

### Differences from Drawdown Rules

| Aspect | DailyLossLimitRule (4.2) | MaxDrawdownRule (4.3) | MaxPositionSizeRule (4.4) |
|--------|--------------------------|----------------------|----------------------------|
| Context Key | `daily_pnl_percent` | `total_drawdown_percent` | `requested_lots`, `current_position_lots` |
| Metric Type | Percentage | Percentage | Absolute (lots) |
| Dimension | Loss/Profit | Drawdown | Position Size |
| Scaling | N/A | N/A | Optional (per_10k_balance) |
| Reset | Daily at midnight | Never (cumulative) | N/A (per-order check) |
| Default Threshold | 5% (FTMO) | 10% (FTMO) | 100 lots with scaling |
| Default Warnings | [70, 80, 90] | [50, 70, 85] | [70, 80, 90] |
| Priority | 1 (first) | 2 (second) | 3 (third) |

### Project Structure Notes

**File Location:**
- Create NEW file: `src/rules/types/position.py`
- This follows the established pattern of grouping related rules by category:
  - `drawdown.py` - DailyLossLimit, MaxDrawdown
  - `position.py` - MaxPositionSize (this story), future position rules

**Naming Convention:**
- Rule type in YAML: `max_position_size`
- Class name: `MaxPositionSizeRule`
- Follows pattern: `max_{metric}` -> `Max{Metric}Rule` (consistent with MaxDrawdownRule)
- **IMPORTANT:** This name matches the lazy import in `parser.py` (Story 3.7)

### References

- [docs/architecture.md#Pluggable-Rule-Engine] - Rule engine architecture
- [docs/architecture.md#Rule-Types] - Rule type definitions (max_position_size)
- [docs/epics.md#Story-4.4] - Story requirements and acceptance criteria
- [docs/sprint-artifacts/4-1-rule-engine-framework.md] - BaseRule protocol, RuleEngine
- [docs/sprint-artifacts/4-2-daily-loss-limit-rule.md] - First rule implementation pattern
- [docs/sprint-artifacts/4-3-max-drawdown-rule.md] - Second rule implementation pattern
- [docs/prd.md#NFR2] - Performance requirement: < 50ms
- [docs/prd.md#FR17] - Position size limit requirement
- [src/rules/presets/ftmo.yaml] - FTMO preset configuration
- [Context7 NautilusTrader 2025-12-31] - RiskEngine, FixedRiskSizer, max_notional patterns

## Dev Agent Record

**Story created:** Epic 4 analysis, Story 4.1-4.3 patterns, Context7 NautilusTrader research

**Agent Model:** Claude Opus 4.5 (claude-opus-4-5-20251101)

**Implementation Notes:**
- THIRD concrete rule implementation in Epic 4
- Uses BaseRule protocol established in Story 4.1
- Follows DailyLossLimitRule/MaxDrawdownRule patterns from Story 4.2/4.3
- NEW file: `src/rules/types/position.py` (different category from drawdown)
- Supports both fixed and scaled limits (per_10k_balance)
- Tracks total exposure: existing positions + new order

### Context Reference

- Story 4.1 complete implementation patterns
- Story 4.2 DailyLossLimitRule as template
- Story 4.3 MaxDrawdownRule as template
- Context7 NautilusTrader RiskEngine research
- FTMO preset YAML configuration

### Debug Log References

(To be populated during implementation)

### Completion Notes List

(To be populated after implementation)

### File List

**Files to Create:**
- `services/trading-engine/src/rules/types/position.py` - MaxPositionSizeRule class
- `services/trading-engine/tests/unit/test_max_position_size_rule.py` - Unit tests
- `services/trading-engine/tests/integration/test_max_position_size_integration.py` - Integration tests

**Files to Modify:**
- `services/trading-engine/src/rules/types/__init__.py` - Add MaxPositionSizeRule export
- `services/trading-engine/src/rules/__init__.py` - Add MaxPositionSizeRule export
- `services/trading-engine/src/rules/parser.py` - No changes needed (lazy import already expects MaxPositionSizeRule)
- `docs/sprint-artifacts/sprint-status.yaml` - Update story status

---

## Definition of Done

**Core Implementation:**
- [ ] MaxPositionSizeRule class created implementing BaseRule protocol
- [ ] validate() returns BLOCK when requested_lots > limit
- [ ] validate() returns BLOCK when total exposure > limit
- [ ] validate() returns WARN at warning thresholds
- [ ] validate() returns ALLOW below all thresholds
- [ ] Scaling mode "per_10k_balance" works correctly
- [ ] RuleResult includes current_value and threshold_value
- [ ] get_current_value(), get_threshold(), get_warning_thresholds() implemented

**Integration:**
- [ ] RuleParser imports and uses MaxPositionSizeRule (not placeholder)
- [ ] FTMO preset loads MaxPositionSizeRule with correct config
- [ ] RuleEngine evaluates MaxPositionSizeRule correctly

**Acceptance Criteria Verification:**
- [ ] AC1: Trade blocked when size > limit (1.5 > 1.0)
- [ ] AC2: Trade allowed when size <= limit (0.5 <= 1.0)
- [ ] AC3: Scaling works (6.0 blocked with $50k = 5.0 max)
- [ ] AC4: Total exposure checked (0.5 + 0.8 = 1.3 > 1.0)
- [ ] AC5: Exact limit allowed (1.0 of 1.0)
- [ ] AC6: Warning at threshold (80% of limit)

**Testing:**
- [ ] Unit tests cover ALLOW, WARN, BLOCK scenarios
- [ ] Unit tests cover scaling logic
- [ ] Unit tests cover total exposure logic
- [ ] Unit tests cover protocol method implementations
- [ ] Integration tests with RuleEngine
- [ ] Integration tests with FTMO preset loading
- [ ] All existing tests still pass
- [ ] Code passes: `uv run ruff check src/rules/`

---
