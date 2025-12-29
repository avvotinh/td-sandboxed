# Story 3.1: Multi-Account Configuration

Status: Done

## Story

As a **trader**,
I want **to configure multiple accounts in a single YAML file**,
So that **I can manage all my trading accounts in one place**.

## Acceptance Criteria

1. **AC1:** Given I create an `accounts.yaml` with multiple accounts (2-5 accounts with different prop firms), When the trading engine loads the configuration, Then all accounts are recognized, validated, and ready for trading

2. **AC2:** Given I configure more than 5 accounts, When the engine loads the configuration, Then I receive a clear error: "Maximum 5 accounts supported"

3. **AC3:** Given two accounts have the same ID, When the engine loads the configuration, Then I receive a clear error: "Duplicate account ID: {id}"

4. **AC4:** Given an account references a non-existent prop_firm preset, When the engine loads the configuration, Then I receive a clear error: "Unknown prop firm preset: {prop_firm}"

5. **AC5:** Given an account has invalid MT5 configuration (missing server, login, or password_env), When the engine loads the configuration, Then I receive a descriptive validation error

## Tasks / Subtasks

- [x] Task 1: Consolidate account list validators (AC: #2, #3)
  - [x] 1.1: Define `MAX_ACCOUNTS = 5` constant in `src/accounts/models.py`
  - [x] 1.2: **MODIFY existing `validate_unique_ids`** to become `validate_accounts` combining:
    - Max accounts check (run FIRST - more common user error)
    - Unique ID check with AC3-compliant error format: `"Duplicate account ID: {id}"`
  - [x] 1.3: Error messages must match AC requirements exactly

- [x] Task 2: Validate prop_firm preset existence (AC: #4)
  - [x] 2.1: Define `VALID_PROP_FIRMS = frozenset({"ftmo", "the5ers", "wmt"})` in models.py
  - [x] 2.2: Add model_validator to `AccountConfig` checking prop_firm against valid presets
  - [x] 2.3: **Normalize prop_firm to lowercase** for case-insensitive matching (user may type "FTMO")
  - [x] 2.4: Keep validation flexible - type="custom" with rules_file bypasses prop_firm check

- [x] Task 3: Update ConfigLoader for multi-account loading (AC: #1)
  - [x] 3.1: **Verify existing loader** - Pydantic validators auto-trigger, likely no code changes needed
  - [x] 3.2: Add success logging for multi-account load summary
  - [x] 3.3: Implement `warn_missing_password_env()` helper (warning only, see Dev Notes)

- [x] Task 4: Enhance error messages (AC: #2, #3, #4, #5)
  - [x] 4.1: Ensure ConfigValidationError formats multi-account errors clearly
  - [x] 4.2: Include account ID context in all account-level validation errors
  - [x] 4.3: Add helpful suggestions in error messages (e.g., "Reduce accounts to 5 or fewer")

- [x] Task 5: Unit tests for all validation scenarios (AC: #1-5)
  - [x] 5.1: Test valid multi-account config (2, 3, 4, 5 accounts)
  - [x] 5.2: **Test exactly 5 accounts (boundary condition)** - must pass
  - [x] 5.3: Test max accounts exceeded (6+ accounts)
  - [x] 5.4: Test duplicate account IDs - verify exact error message format
  - [x] 5.5: Test invalid prop_firm preset (including case variations: "FTMO", "Ftmo")
  - [x] 5.6: Test invalid MT5 configurations
  - [x] 5.7: Test mixed account types (prop_firm + custom + demo)

- [x] Task 6: Create example multi-account configs (AC: #1)
  - [x] 6.1: Update `configs/accounts.yaml.example` with multi-account examples
  - [x] 6.2: Include examples for all account types (prop_firm, custom, demo)
  - [x] 6.3: Add custom rules account example with rules_file path

## Dev Notes

### Technical Stack

- **Python:** 3.11+ (required by NautilusTrader)
- **Validation:** Pydantic v2 (already in use)
- **Config:** YAML with PyYAML

### File Locations

| File | Action | Purpose |
|------|--------|---------|
| `src/accounts/models.py` | MODIFY | Add MAX_ACCOUNTS, VALID_PROP_FIRMS, update validators |
| `src/config/loader.py` | VERIFY | Pydantic validators auto-trigger - likely no changes |
| `tests/unit/test_account_models.py` | ADD | Multi-account validation tests |
| `configs/accounts.yaml.example` | UPDATE | Multi-account examples |

### ConfigLoader Integration

**IMPORTANT:** The existing `ConfigLoader.load()` method returns `AccountsConfig` which triggers Pydantic validation automatically. Adding validators to the models is sufficient - no loader code changes expected.

```python
# src/config/loader.py - Existing pattern (verify by reading file)
class ConfigLoader:
    def load(self) -> AccountsConfig:
        # Pydantic validators auto-trigger on model instantiation
        return AccountsConfig(**yaml_data)
```

**Only add logging enhancement:**
```python
logger.info(f"Loaded {len(config.accounts)} accounts successfully")
for acc in config.accounts:
    logger.debug(f"  - {acc.id}: {acc.name} ({acc.type.value})")
```

### Password Environment Variable Warning

Implement in loader.py or as utility function:

```python
import os
import logging

logger = logging.getLogger(__name__)

def warn_missing_password_env(accounts: list[AccountConfig]) -> None:
    """Warn about missing MT5 password environment variables (non-blocking)."""
    for acc in accounts:
        if not os.getenv(acc.mt5.password_env):
            logger.warning(
                f"Account '{acc.id}': Environment variable '{acc.mt5.password_env}' "
                "is not set. MT5 connection will fail at runtime."
            )
```

### Reference Implementation

**Constants and consolidated validator (models.py):**

```python
MAX_ACCOUNTS = 5
VALID_PROP_FIRMS = frozenset({"ftmo", "the5ers", "wmt"})

class AccountsConfig(BaseModel):
    accounts: list[AccountConfig] = Field(default_factory=list)

    @field_validator("accounts")
    @classmethod
    def validate_accounts(cls, v: list[AccountConfig]) -> list[AccountConfig]:
        """Validate account list constraints (max count, unique IDs)."""
        # 1. Check max accounts FIRST (more common user error)
        if len(v) > MAX_ACCOUNTS:
            raise ValueError(
                f"Maximum {MAX_ACCOUNTS} accounts supported. "
                f"Got {len(v)} accounts. Remove {len(v) - MAX_ACCOUNTS} account(s)."
            )

        # 2. Check unique IDs with AC3-compliant error format
        seen = set()
        for acc in v:
            if acc.id in seen:
                raise ValueError(f"Duplicate account ID: {acc.id}")
            seen.add(acc.id)

        return v

class AccountConfig(BaseModel):
    # ... existing fields ...

    @model_validator(mode="after")
    def validate_prop_firm_preset(self) -> "AccountConfig":
        """Validate prop_firm preset with case-insensitive matching."""
        if self.prop_firm:
            normalized = self.prop_firm.lower()
            if normalized not in VALID_PROP_FIRMS:
                raise ValueError(
                    f"Unknown prop firm preset: '{self.prop_firm}'. "
                    f"Valid presets: {', '.join(sorted(VALID_PROP_FIRMS))}"
                )
            # Normalize to lowercase for consistency
            object.__setattr__(self, 'prop_firm', normalized)
        return self
```

### Multi-Account Config Schema

```yaml
# configs/accounts.yaml
accounts:
  # Prop firm account with preset rules
  - id: "ftmo-gold-001"
    name: "FTMO Gold Challenge"
    type: "prop_firm"
    prop_firm: "ftmo"           # Case-insensitive: "FTMO", "Ftmo" also work
    mt5:
      server: "FTMO-Server"
      login: 12345678
      password_env: "FTMO_PASS_001"
    strategy: "ma_crossover"
    strategy_params:
      fast_period: 20
      slow_period: 50
    signal_filter:
      symbols: ["XAUUSD"]
    status: "active"

  # Another prop firm
  - id: "5ers-btc-001"
    name: "The5ers BTC Account"
    type: "prop_firm"
    prop_firm: "the5ers"
    mt5:
      server: "The5ers-Server"
      login: 87654321
      password_env: "FIVE_ERS_PASS_001"
    strategy: "breakout"
    signal_filter:
      symbols: ["BTCUSD"]
    status: "active"

  # Custom rules account (personal trading)
  - id: "personal-scalper"
    name: "My Scalping Account"
    type: "custom"
    rules_file: "configs/custom_rules/conservative.yaml"  # Path relative to project
    mt5:
      server: "ICMarkets-MT5"
      login: 11111111
      password_env: "PERSONAL_MT5_PASS"
    strategy: "scalper"
    signal_filter:
      symbols: ["EURUSD", "GBPUSD"]
      max_spread_pips: 1.5
    status: "active"

  # Demo account (no rules enforced)
  - id: "demo-test-001"
    name: "Paper Trading Demo"
    type: "demo"
    mt5:
      server: "Demo-Server"
      login: 99999999
      password_env: "DEMO_PASS"
    strategy: "ma_crossover"
    signal_filter:
      symbols: ["EURUSD"]
    status: "active"
```

### Testing Requirements

**Framework:** pytest | **Location:** `tests/unit/` | **Naming:** `test_*.py`

```python
# tests/unit/test_account_models.py

class TestMaxAccountsValidation:
    def test_exactly_five_accounts_allowed(self):
        """Boundary: exactly 5 accounts (the limit) must pass."""
        config = create_config_with_n_accounts(5)
        assert len(config.accounts) == 5

    def test_max_accounts_exceeded(self):
        """6+ accounts must fail with specific error message."""
        with pytest.raises(ValueError, match="Maximum 5 accounts supported"):
            create_config_with_n_accounts(6)

class TestDuplicateIdValidation:
    def test_duplicate_account_id_error_format(self):
        """Error message must match AC3: 'Duplicate account ID: {id}'"""
        with pytest.raises(ValueError, match=r"Duplicate account ID: dup-001"):
            create_config_with_duplicate_id("dup-001")

class TestPropFirmValidation:
    def test_invalid_prop_firm_preset(self):
        """Unknown prop firm must fail with helpful error."""
        with pytest.raises(ValueError, match="Unknown prop firm preset"):
            create_account(prop_firm="invalid_firm")

    def test_prop_firm_case_insensitive(self):
        """FTMO, Ftmo, ftmo should all work."""
        for variant in ["FTMO", "Ftmo", "ftmo"]:
            acc = create_account(prop_firm=variant)
            assert acc.prop_firm == "ftmo"  # Normalized

class TestMixedAccountTypes:
    def test_load_mixed_account_types(self):
        """prop_firm + custom + demo accounts load together."""
        config = create_mixed_config()
        types = {acc.type for acc in config.accounts}
        assert types == {AccountType.PROP_FIRM, AccountType.CUSTOM, AccountType.DEMO}
```

### Context & Constraints

**NautilusTrader Alignment:**
- Pydantic v2 validation mirrors NautilusTrader's msgspec patterns
- Per-account MT5 connections align with per-broker execution clients
- YAML config → model validation on load

**From Epic 2 Learnings:**
- `@field_validator` and `@model_validator` decorators for Pydantic v2
- ConfigLoader wraps ValidationError in ConfigValidationError
- All validation at load time, not runtime
- Tests use pytest fixtures

**Anti-Patterns (DO NOT):**
- ❌ Create new validation framework - use Pydantic
- ❌ Validate at runtime - all at load time
- ❌ Modify account_manager.py - already handles multi-account
- ❌ Hard-code prop firm rules - just validate preset names
- ❌ Create new config format - extend accounts.yaml

### References

- [Source: docs/architecture.md#Multi-Account Architecture] - Account Manager design
- [Source: docs/epics.md#Story 3.1] - Story requirements and acceptance criteria
- [Source: services/trading-engine/src/accounts/models.py] - Existing account models
- [Source: services/trading-engine/src/config/loader.py] - Config loading patterns

## Dev Agent Record

### Context Reference

Story created via create-story workflow with:
- NautilusTrader documentation research via MCP Context7
- Architecture analysis from docs/architecture.md
- Existing code analysis from services/trading-engine/src/accounts/

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Initial story creation

### Completion Notes List

- Story context created with comprehensive developer guidance
- Multi-account configuration patterns documented
- All technical requirements extracted from architecture
- Testing requirements specified with clear patterns

### Implementation Completion Notes (2025-12-29)

**All acceptance criteria satisfied:**

- **AC1:** Multi-account configs (2-5) load successfully with all types (prop_firm, personal, demo)
- **AC2:** >5 accounts raises "Maximum 5 accounts supported. Got N accounts. Remove X account(s)."
- **AC3:** Duplicate IDs raise "Duplicate account ID: {id}" (exact format)
- **AC4:** Invalid prop_firm raises "Unknown prop firm preset: '{prop_firm}'. Valid presets: ftmo, the5ers, wmt"
- **AC5:** Missing MT5 fields raise descriptive validation errors

**Implementation highlights:**
- Added `MAX_ACCOUNTS = 5` and `VALID_PROP_FIRMS = frozenset({"ftmo", "the5ers", "wmt"})` constants
- Renamed `validate_unique_ids` → `validate_accounts` with consolidated max+unique validation
- Added `validate_prop_firm_preset` model validator with case-insensitive normalization
- Added logging to ConfigLoader for multi-account load summaries
- Added `warn_missing_password_env()` utility function (non-blocking warning)
- Added 32 new tests covering all validation scenarios
- Updated example config with multi-account documentation

### Validation Notes (2025-12-29)

**Story validated via validate-create-story workflow. Applied improvements:**

| ID | Type | Description |
|----|------|-------------|
| C1 | Critical | Fixed duplicate ID error format to match AC3: "Duplicate account ID: {id}" |
| C2 | Critical | Added ConfigLoader integration details - validators auto-trigger |
| C3 | Critical | Consolidated validators to fix ordering (max accounts → unique IDs) |
| E1 | Enhancement | Added boundary test for exactly 5 accounts |
| E2 | Enhancement | Added case-insensitive prop_firm validation with normalization |
| E3 | Enhancement | Added `warn_missing_password_env()` implementation |
| E4 | Enhancement | Added custom rules and demo account examples |
| O1 | Optimization | Consolidated reference implementation into single section |
| O2 | Optimization | Reduced redundant file listings and context |

### File List

Files modified:
- `services/trading-engine/src/accounts/models.py` - Added MAX_ACCOUNTS, VALID_PROP_FIRMS, consolidated validate_accounts, added validate_prop_firm_preset
- `services/trading-engine/src/config/loader.py` - Added logging, warn_missing_password_env() utility
- `services/trading-engine/tests/unit/test_account_models.py` - Added 32 new tests for multi-account validation
- `configs/accounts.yaml.example` - Updated with multi-account examples (ftmo, the5ers, personal with rules_file, demo)

### Code Review Record (2025-12-29)

**Reviewer:** Claude Opus 4.5 (code-review workflow)

**Findings Summary:** 0 Critical, 0 High, 4 Medium, 3 Low

**Issues Fixed:**
| ID | Severity | Description | Resolution |
|----|----------|-------------|------------|
| M1 | Medium | `warn_missing_password_env()` defined but never called | Added call in `ConfigLoader.load()` after successful load |
| M2 | Medium | Example config referenced non-existent "custom" type | Updated to reference "personal" type correctly |
| M3 | Medium | Missing zero accounts edge case test | Added `test_zero_accounts_allowed` test |
| M4 | Medium | `object.__setattr__` hack for prop_firm normalization | Refactored to use `@field_validator(mode="before")` for cleaner normalization |
| L3 | Low | Test helpers lacked docstrings | Added comprehensive docstrings with Args/Returns |

**Post-Fix Test Results:** 74 tests passing (1 new test added)

**Final Assessment:** All acceptance criteria implemented, all tests pass, code quality verified with ruff. Story approved for done status.

### Change Log

| Date | Change |
|------|--------|
| 2025-12-29 | Code review: Fixed 4 medium issues (M1-M4) and 1 low issue (L3). Added 1 new test. |
| 2025-12-29 | Implemented story 3.1: Multi-account configuration validation with MAX_ACCOUNTS=5 limit, VALID_PROP_FIRMS presets, case-insensitive prop_firm validation, and comprehensive test coverage |
