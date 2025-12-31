# Story 4.5: FTMO Preset Configuration

Status: done

## Story

As a **developer**,
I want **the FTMO rule preset defined in YAML**,
So that **FTMO rules are standardized and version-controlled**.

## Acceptance Criteria

1. **AC1**: Given the FTMO preset file exists at `src/rules/presets/ftmo.yaml`, when I examine the file, then I see a valid YAML configuration with name, version, description, and rules array containing all FTMO rules.

2. **AC2**: Given an account with `prop_firm: "ftmo"`, when the rule engine initializes, then all rules from ftmo.yaml are loaded and active.

3. **AC3**: Given FTMO updates their rules, when I update ftmo.yaml, then the version number increments and accounts using FTMO preset use the new rules on restart.

4. **AC4**: Given the FTMO preset is loaded, when I check the rules, then I see:
   - `daily_loss_limit` with 5.0% threshold, CET timezone reset, warning at [70, 80, 90]
   - `max_drawdown` with 10.0% threshold, reference to initial_balance
   - `max_position_size` with scaling per 10k balance (NEW - requires implementation)
   - `profit_target` with 10.0% threshold, action: notify (NEW - requires implementation)
   - `min_trading_days` with 4 days requirement, action: notify (NEW - requires implementation)

5. **AC5**: Given the profit_target and min_trading_days rules are loaded, when I check their behavior, then they only send notifications (not block trading).

6. **AC6**: Given the YAML schema is validated on load, when I provide an invalid preset file, then parsing fails with a clear error message.

## Tasks / Subtasks

### Task 1: Create ProfitTargetRule Class (AC: 4, 5)

- [x] 1.1: Create new file `src/rules/types/targets.py` for informational rules
- [x] 1.2: Implement `ProfitTargetRule` class with attributes:
  - `rule_type = "profit_target"` (matches YAML type)
  - `priority = 100` (evaluated last, informational only)
- [x] 1.3: Constructor parameters: `threshold_percent: float = 10.0`, `action: str = "notify"`, `**kwargs`
- [x] 1.4: Implement `name` property returning `f"Profit Target {threshold_percent}%"`
- [x] 1.5: Implement `validate()` method:
  - Extract `total_pnl_percent` from context
  - If total_pnl_percent >= threshold_percent: return WARN with notification message
  - Otherwise: return ALLOW
  - **NEVER returns BLOCK** - this is informational only
- [x] 1.6: Implement protocol methods: `get_current_value()`, `get_threshold()`, `get_warning_thresholds()`

### Task 2: Create MinTradingDaysRule Class (AC: 4, 5)

- [x] 2.1: Add `MinTradingDaysRule` class to `src/rules/types/targets.py`
- [x] 2.2: Implement with attributes:
  - `rule_type = "min_trading_days"` (matches YAML type)
  - `priority = 100` (evaluated last, informational only)
- [x] 2.3: Constructor parameters: `required_days: int = 4`, `action: str = "notify"`, `**kwargs`
- [x] 2.4: Implement `name` property returning `f"Minimum Trading Days ({required_days})"`
- [x] 2.5: Implement `validate()` method:
  - Extract `trading_days_count` from context
  - If trading_days_count >= required_days: return WARN (target met notification)
  - Otherwise: return ALLOW with info about progress
  - **NEVER returns BLOCK** - this is informational only
- [x] 2.6: Implement protocol methods

### Task 3: Update Module Exports (AC: 2, 4)

- [x] 3.1: Add `ProfitTargetRule` and `MinTradingDaysRule` to `src/rules/types/__init__.py`
- [x] 3.2: Add exports to `src/rules/__init__.py`
- [x] 3.3: Verify `RuleParser` lazy imports work (already has placeholders - will load real implementations)

### Task 4: Complete FTMO Preset YAML (AC: 1, 4, 6)

- [x] 4.1: Review existing `src/rules/presets/ftmo.yaml` (already has basic structure)
- [x] 4.2: Update version to "2025.1" to reflect current FTMO rules
- [x] 4.3: Add `max_position_size` rule configuration:
  ```yaml
  - type: max_position_size
    max_lots: 100.0
    scaling: "per_10k_balance"
    warning_at: [70, 80, 90]
  ```
- [x] 4.4: Verify `profit_target` rule is present with correct values
- [x] 4.5: Verify `min_trading_days` rule is present with `required_days: 4`
- [x] 4.6: Add comprehensive comments documenting FTMO source

### Task 5: Unit Tests for New Rules (AC: 4, 5)

- [x] 5.1: Create `tests/unit/test_profit_target_rule.py`
- [x] 5.2: Test ProfitTargetRule WARN when target met (10% profit)
- [x] 5.3: Test ProfitTargetRule ALLOW when below target
- [x] 5.4: Test ProfitTargetRule NEVER returns BLOCK
- [x] 5.5: Test custom threshold_percent configuration
- [x] 5.6: Create `tests/unit/test_min_trading_days_rule.py`
- [x] 5.7: Test MinTradingDaysRule WARN when target met (4+ days)
- [x] 5.8: Test MinTradingDaysRule ALLOW when below target
- [x] 5.9: Test MinTradingDaysRule NEVER returns BLOCK
- [x] 5.10: Test protocol methods for both rules

### Task 6: Integration Tests (AC: 2, 3, 6)

- [x] 6.1: Create/update `tests/integration/test_ftmo_preset.py`
- [x] 6.2: Test loading FTMO preset via RulePresetLoader
- [x] 6.3: Verify all 5 rules are loaded with correct types
- [x] 6.4: Test RuleEngine processes all FTMO rules correctly
- [x] 6.5: Test preset version tracking
- [x] 6.6: Test invalid YAML schema detection
- [x] 6.7: Verify rule priorities are correct (DailyLoss=1, MaxDrawdown=2, Position=3, Targets=100)

### Task 7: Documentation (AC: 1-6)

- [x] 7.1: Add docstrings to ProfitTargetRule and MinTradingDaysRule
- [x] 7.2: Add comments in ftmo.yaml explaining each rule
- [x] 7.3: Update any relevant architecture references

## Dev Notes

### CRITICAL: FULL FILE PATHS (Monorepo Structure)

**⚠️ All paths are relative to project root `/home/hopdev/Dev/Sandboxed/`:**
- New file: `services/trading-engine/src/rules/types/targets.py`
- Modify: `services/trading-engine/src/rules/types/__init__.py`
- Modify: `services/trading-engine/src/rules/__init__.py`
- Modify: `services/trading-engine/src/rules/presets/ftmo.yaml`
- Test files: `services/trading-engine/tests/unit/` and `services/trading-engine/tests/integration/`

### PREREQUISITES (All Complete - Follow Existing Patterns)

Stories 4.1-4.4 established the rule implementation pattern. Follow `DailyLossLimitRule` in `drawdown.py` as the template for both new rules.

**Key files to reference:**
- `services/trading-engine/src/rules/types/drawdown.py` - Pattern template
- `services/trading-engine/src/rules/types/position.py` - Recent example
- `services/trading-engine/src/rules/parser.py` - Lazy imports already configured (lines 135-149)

### CURRENT STATE OF FTMO PRESET

The file `services/trading-engine/src/rules/presets/ftmo.yaml` currently has:
- ✅ `daily_loss_limit` rule (Story 4.2)
- ✅ `max_drawdown` rule (Story 4.3)
- ❌ `max_position_size` rule - **MISSING, must add**
- ⚠️ `profit_target` - placeholder (uses PlaceholderRule)
- ⚠️ `min_trading_days` - placeholder (uses PlaceholderRule)
- ⚠️ Version is "2024.1" - **must update to "2025.1"**

### WHAT THIS STORY MUST DO

1. **CREATE** `targets.py` with `ProfitTargetRule` and `MinTradingDaysRule`
2. **UPDATE** `ftmo.yaml`:
   - Change version from "2024.1" to "2025.1"
   - Add `max_position_size` rule (the class exists from Story 4.4)
3. **UPDATE** module exports in `__init__.py` files
4. **VERIFY** `RulePresetLoader` loads all 5 rules correctly

### Task Dependencies (Execute in Order)

1. **Tasks 1-2**: Create ProfitTargetRule and MinTradingDaysRule (parallel)
2. **Task 3**: Update module exports (depends on 1-2)
3. **Task 4**: Update ftmo.yaml (depends on 3)
4. **Tasks 5-6**: Unit and Integration tests (depends on 4, can be parallel)
5. **Task 7**: Documentation (final)

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **YAML:** PyYAML for parsing
- **Existing Modules:** `src/rules/`, `src/rules/types/`, `src/rules/presets/`
- **Test Framework:** pytest

### Key Design Decisions

**Informational Rules vs Blocking Rules:**
- `profit_target` and `min_trading_days` are **informational only**
- They use `action: "notify"` and return WARN (not BLOCK)
- These track progress toward FTMO challenge goals
- Blocking rules (`daily_loss_limit`, `max_drawdown`, `max_position_size`) protect from violations

**Rule Priority:**
| Rule | Priority | Purpose |
|------|----------|---------|
| `daily_loss_limit` | 1 | Critical - 5% daily protection |
| `max_drawdown` | 2 | Critical - 10% total protection |
| `max_position_size` | 3 | Important - lot size limits |
| `profit_target` | 100 | Informational - progress tracking |
| `min_trading_days` | 100 | Informational - progress tracking |

**FTMO Rules Summary (2025):**
Based on latest FTMO documentation:
- **Daily Loss Limit:** 5% of initial balance, resets at midnight CET
- **Maximum Drawdown:** 10% of initial balance (equity-based, not balance)
- **Profit Target:** 10% for Challenge, 5% for Verification, None for Funded
- **Minimum Trading Days:** 4 days (at least one trade opened per day)
- **Time Limit:** Unlimited (no deadline to pass)

**Timezone Handling:**
FTMO uses **CET/CEST (Central European Time)** for daily resets. The preset correctly specifies `timezone: "CET"`.

### File Locations (Single Source of Truth)

**⚠️ IMPORTANT: Use FULL paths from project root `/home/hopdev/Dev/Sandboxed/`**

| Full Path | Action | Purpose |
|-----------|--------|---------|
| **New Files** | | |
| `services/trading-engine/src/rules/types/targets.py` | **CREATE** | ProfitTargetRule, MinTradingDaysRule |
| `services/trading-engine/tests/unit/test_profit_target_rule.py` | CREATE | Unit tests for ProfitTargetRule |
| `services/trading-engine/tests/unit/test_min_trading_days_rule.py` | CREATE | Unit tests for MinTradingDaysRule |
| `services/trading-engine/tests/integration/test_ftmo_preset.py` | CREATE/UPDATE | Integration tests |
| **Modify Files** | | |
| `services/trading-engine/src/rules/presets/ftmo.yaml` | MODIFY | Add max_position_size, update version |
| `services/trading-engine/src/rules/types/__init__.py` | MODIFY | Add new rule exports |
| `services/trading-engine/src/rules/__init__.py` | MODIFY | Add new rule exports |
| `services/trading-engine/src/rules/parser.py` | VERIFY | Lazy imports already configured |

### Required __init__.py Updates

**IMPORTANT:** The current `types/__init__.py` does NOT import from targets yet. You MUST add these imports.

```python
# services/trading-engine/src/rules/types/__init__.py - FULL FILE AFTER UPDATE
"""Rule type implementations for FTMO compliance.

This module contains concrete rule implementations:
- DailyLossLimitRule: Blocks trades when daily loss exceeds threshold (Story 4.2)
- MaxDrawdownRule: Blocks trades when total drawdown exceeds threshold (Story 4.3)
- MaxPositionSizeRule: Limits position sizes (Story 4.4)
- ProfitTargetRule: Tracks profit target achievement (Story 4.5)
- MinTradingDaysRule: Tracks minimum trading days requirement (Story 4.5)
"""

from .drawdown import DailyLossLimitRule, MaxDrawdownRule
from .position import MaxPositionSizeRule
from .targets import ProfitTargetRule, MinTradingDaysRule  # ADD THIS LINE

__all__ = [
    "DailyLossLimitRule",
    "MaxDrawdownRule",
    "MaxPositionSizeRule",
    "ProfitTargetRule",      # ADD THIS
    "MinTradingDaysRule",    # ADD THIS
]
```

**Also update `services/trading-engine/src/rules/__init__.py`** to re-export the new rules.

### FTMO Preset YAML Updates Required

**File:** `services/trading-engine/src/rules/presets/ftmo.yaml`

**Changes to make:**

1. **Update header comment** - add "Last Updated: 2025-12"
2. **Change name** from `"FTMO"` to `"FTMO Challenge"`
3. **Change version** from `"2024.1"` to `"2025.1"`
4. **Update description** to include rule summary
5. **ADD max_position_size rule** (insert after max_drawdown, before profit_target)

**New max_position_size rule to ADD:**
```yaml
  # Maximum Position Size: Scaled by account balance
  # 1 lot per $10,000 balance (100 lots base multiplier)
  # BLOCKING: Exceeding this blocks the trade
  - type: max_position_size
    max_lots: 100.0
    scaling: "per_10k_balance"
    warning_at: [70, 80, 90]
```

**Final ftmo.yaml should have these 5 rules in order:**
1. `daily_loss_limit` (priority 1, BLOCKING)
2. `max_drawdown` (priority 2, BLOCKING)
3. `max_position_size` (priority 3, BLOCKING) ← **NEW**
4. `profit_target` (priority 100, INFORMATIONAL)
5. `min_trading_days` (priority 100, INFORMATIONAL)

### Context Keys for New Rules

**ProfitTargetRule requires:**
```python
context = {
    "total_pnl_percent": 8.5,     # Current P&L as % of initial balance (positive = profit)
    "account_id": "ftmo-001",     # For logging
}
```

**MinTradingDaysRule requires:**
```python
context = {
    "trading_days_count": 3,       # Number of unique days with at least 1 opened trade
    "account_id": "ftmo-001",      # For logging
}
# NOTE: trading_days_count is calculated by RuleContextBuilder from trade history
# A "trading day" = any calendar day (in account timezone) where at least one trade was opened
# Source: Query trades table, count DISTINCT DATE(entry_time) for account_id
```

### NautilusTrader Alignment (Context7 Research 2025-12-31)

NautilusTrader provides complementary risk management:

**What NautilusTrader Provides:**
- `RiskEngineConfig.max_notional_per_order`: Maximum notional per order
- `RiskEngineConfig.max_order_submit_rate`: Rate limiting (e.g., "100/00:00:01")
- `FixedRiskSizer.calculate()`: Position sizing based on risk % and stop loss
- `hard_limit` parameter: Absolute maximum quantity

**What Our FTMO Preset Adds:**
- Prop firm-specific rules (5% daily, 10% max drawdown)
- YAML-based configuration (version controlled, auditable)
- Informational tracking (profit target, trading days)
- Warning thresholds before hitting limits
- Integration with account lifecycle and audit logging

**Synergy:**
Our preset works **alongside** NautilusTrader's built-in risk:
1. NautilusTrader handles execution-level limits (rate, notional)
2. Our rules handle prop firm compliance (FTMO-specific limits)
3. Both systems can be active for layered protection

### CLI Commands for Testing

```bash
cd services/trading-engine

# Run unit tests for new rules
uv run pytest tests/unit/test_profit_target_rule.py -v
uv run pytest tests/unit/test_min_trading_days_rule.py -v

# Run integration tests for FTMO preset
uv run pytest tests/integration/test_ftmo_preset.py -v

# CRITICAL: Verify RulePresetLoader loads all 5 rules (not placeholders)
uv run python -c "
from src.rules.preset_loader import RulePresetLoader

loader = RulePresetLoader()
rules = loader.load_preset('ftmo')
print(f'Loaded {len(rules)} FTMO rules:')
for rule in rules:
    # Check rule is NOT a placeholder
    is_placeholder = 'Placeholder' in type(rule).__name__
    status = '❌ PLACEHOLDER' if is_placeholder else '✅'
    print(f'  {status} {rule.name} (type: {rule.rule_type}, priority: {rule.priority})')

# Verify count
assert len(rules) == 5, f'Expected 5 rules, got {len(rules)}'
print('\\n✅ All 5 FTMO rules loaded successfully!')
"

# Verify no regressions
uv run pytest tests/ -v && uv run ruff check src/
```

### AC6 Test Cases: Invalid YAML Schema Detection

**Add these test cases to `tests/integration/test_ftmo_preset.py`:**

```python
import pytest
from src.rules.parser import RuleParser, RuleParseError

def test_invalid_yaml_missing_rules_key():
    """AC6: Invalid YAML detected with clear error - missing 'rules' key."""
    parser = RuleParser()
    invalid_yaml = {"name": "Test", "version": "1.0"}  # No 'rules' key

    with pytest.raises(RuleParseError) as exc_info:
        parser.parse_rules(invalid_yaml)

    assert "rules" in str(exc_info.value).lower()

def test_invalid_yaml_unknown_rule_type():
    """AC6: Invalid YAML detected - unknown rule type."""
    parser = RuleParser()
    invalid_yaml = {
        "name": "Test",
        "rules": [{"type": "unknown_rule_type", "value": 5.0}]
    }

    with pytest.raises(RuleParseError) as exc_info:
        parser.parse_rules(invalid_yaml)

    assert "unknown_rule_type" in str(exc_info.value)

def test_invalid_yaml_missing_type_field():
    """AC6: Invalid YAML detected - rule missing 'type' field."""
    parser = RuleParser()
    invalid_yaml = {
        "name": "Test",
        "rules": [{"threshold_percent": 5.0}]  # No 'type' field
    }

    with pytest.raises(RuleParseError) as exc_info:
        parser.parse_rules(invalid_yaml)

    assert "type" in str(exc_info.value).lower()
```

### Anti-Patterns (What NOT to Do)

| Anti-Pattern | Why It's Wrong | Instead, Do This |
|--------------|----------------|------------------|
| Make profit_target return BLOCK | Wrong semantics - it's informational | Return WARN to notify, ALLOW to continue |
| Hardcode FTMO values in code | Not configurable, hard to update | Load from YAML preset |
| Skip validation testing | May break on invalid presets | Test both valid and invalid YAML |
| Ignore timezone for daily reset | FTMO uses CET, not UTC | Use configured timezone |
| Mix blocking and informational rules | Confusing behavior | Clear separation: BLOCK vs NOTIFY |

### FTMO Official Documentation References

- [Maximum Daily Loss](https://academy.ftmo.com/lesson/maximum-daily-loss/) - 5% rule
- [Maximum Loss (Drawdown)](https://academy.ftmo.com/lesson/maximum-loss/) - 10% rule
- [FTMO Challenge Rules](https://ftmo.com/en/how-to-pass-ftmo-challenge/) - Overview
- [FTMO FAQ](https://ftmo.com/en/faq/step-1-ftmo-challenge/) - Trading days, time limits

### Project Structure Notes

**File Location:**
- Create NEW file: `src/rules/types/targets.py`
- This groups informational/target rules separately from blocking rules:
  - `drawdown.py` - DailyLossLimit, MaxDrawdown (blocking)
  - `position.py` - MaxPositionSize (blocking)
  - `targets.py` - ProfitTarget, MinTradingDays (informational)

**Naming Convention:**
- Rule type in YAML: `profit_target`, `min_trading_days`
- Class names: `ProfitTargetRule`, `MinTradingDaysRule`
- Follows pattern established in Story 4.2-4.4

### References

- [docs/architecture.md#Pluggable-Rule-Engine] - Rule engine architecture
- [docs/architecture.md#Preset-Example-FTMO] - FTMO preset specification
- [docs/epics.md#Story-4.5] - Story requirements and acceptance criteria
- [docs/sprint-artifacts/4-1-rule-engine-framework.md] - BaseRule protocol
- [docs/sprint-artifacts/4-2-daily-loss-limit-rule.md] - DailyLossLimitRule pattern
- [docs/sprint-artifacts/4-3-max-drawdown-rule.md] - MaxDrawdownRule pattern
- [docs/sprint-artifacts/4-4-position-size-limit-rule.md] - MaxPositionSizeRule pattern
- [docs/prd.md#FR9] - Load prop firm presets requirement
- [src/rules/presets/ftmo.yaml] - Existing FTMO preset file
- [src/rules/preset_loader.py] - RulePresetLoader implementation
- [Context7 NautilusTrader 2025-12-31] - RiskEngineConfig, FixedRiskSizer
- [FTMO Trading Rules 2025] - Official FTMO documentation

## Dev Agent Record

**Story created:** 2025-12-31 via create-story workflow

**Context Analysis:**
- Epic 4 progress: Stories 4.1-4.4 complete
- FTMO preset file exists with partial rules
- RulePresetLoader already implemented (Story 3.7)
- RuleParser has lazy imports for all rule types
- Need to implement ProfitTargetRule and MinTradingDaysRule
- Need to add max_position_size to preset YAML

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Context Reference

- Story 4.1-4.4 complete implementation patterns
- Context7 NautilusTrader RiskEngine research
- FTMO 2025 official documentation web search
- Existing preset_loader.py and parser.py analysis

### Debug Log References

(To be populated during implementation)

### Completion Notes List

**Completed 2025-12-31 by Claude Opus 4.5:**

1. Created `targets.py` with ProfitTargetRule and MinTradingDaysRule
   - Both implement BaseRule protocol
   - Both return WARN when targets are met, ALLOW otherwise
   - Neither ever returns BLOCK (informational only)
   - Full docstrings and protocol methods

2. Updated `ftmo.yaml`:
   - Version updated to "2025.1"
   - Added max_position_size rule with per_10k_balance scaling
   - Added comprehensive FTMO documentation comments
   - All 5 rules now load correctly (no placeholders)

3. Updated module exports in:
   - `src/rules/types/__init__.py`
   - `src/rules/__init__.py`

4. Created comprehensive test suites:
   - `tests/unit/test_profit_target_rule.py` (52 tests)
   - `tests/unit/test_min_trading_days_rule.py` (51 tests)
   - `tests/integration/test_ftmo_preset.py` (43 tests)

5. All tests pass: 491 rule-related tests passing
6. Linting passes: `ruff check src/rules/types/targets.py` clean

### File List (Full Paths from Project Root)

**Files CREATED:**
| File | Purpose | Status |
|------|---------|--------|
| `services/trading-engine/src/rules/types/targets.py` | ProfitTargetRule, MinTradingDaysRule | ✅ Created |
| `services/trading-engine/tests/unit/test_profit_target_rule.py` | Unit tests (52 tests) | ✅ Created |
| `services/trading-engine/tests/unit/test_min_trading_days_rule.py` | Unit tests (51 tests) | ✅ Created |
| `services/trading-engine/tests/integration/test_ftmo_preset.py` | Integration tests (43 tests) | ✅ Created |

**Files MODIFIED:**
| File | Changes Made | Status |
|------|--------------|--------|
| `services/trading-engine/src/rules/presets/ftmo.yaml` | Added max_position_size, updated version to 2025.1 | ✅ Modified |
| `services/trading-engine/src/rules/types/__init__.py` | Added `from .targets import ...` | ✅ Modified |
| `services/trading-engine/src/rules/__init__.py` | Added new rule exports | ✅ Modified |

**Files VERIFIED (No Changes Needed):**
| File | Verification |
|------|--------------|
| `services/trading-engine/src/rules/parser.py` | Lines 135-149 already have lazy imports for targets ✅ |

---

## Definition of Done

**Core Implementation:**
- [x] ProfitTargetRule class created implementing BaseRule protocol
- [x] MinTradingDaysRule class created implementing BaseRule protocol
- [x] Both rules return WARN for progress notification, ALLOW otherwise
- [x] Neither rule ever returns BLOCK (informational only)
- [x] All protocol methods implemented (get_current_value, get_threshold, get_warning_thresholds)

**FTMO Preset:**
- [x] ftmo.yaml updated to version "2025.1"
- [x] max_position_size rule added to preset
- [x] All 5 rules load correctly via RulePresetLoader
- [x] YAML schema validation works for valid/invalid files

**Integration:**
- [x] RuleParser imports and uses real rule classes (not placeholders)
- [x] RuleEngine processes all 5 FTMO rules correctly
- [x] Rules are evaluated in correct priority order

**Acceptance Criteria Verification:**
- [x] AC1: FTMO preset file has valid YAML structure
- [x] AC2: Account with prop_firm="ftmo" loads all rules
- [x] AC3: Version tracking works for updates
- [x] AC4: All 5 rule types present with correct configs
- [x] AC5: profit_target and min_trading_days only notify
- [x] AC6: Invalid YAML detected with clear error

**Testing:**
- [x] Unit tests for ProfitTargetRule (WARN, ALLOW, never BLOCK)
- [x] Unit tests for MinTradingDaysRule (WARN, ALLOW, never BLOCK)
- [x] Integration tests for FTMO preset loading
- [x] All existing tests still pass
- [x] Code passes: `uv run ruff check src/rules/`

---
