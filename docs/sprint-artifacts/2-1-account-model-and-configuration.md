# Story 2.1: Account Model and Configuration

Status: Done

## Story

As a **trader**,
I want **to define my trading account configuration in a YAML file with proper validation**,
so that **I can easily set up and manage multiple MT5 accounts with type-safe configuration**.

## Acceptance Criteria

1. **AC1**: Account configuration can be loaded from a YAML file with Pydantic validation
2. **AC2**: Invalid configurations produce clear, actionable error messages with field-level details
3. **AC3**: MT5 passwords are resolved from environment variables (never stored in config files)
4. **AC4**: All required fields (id, name, type, mt5 config) are validated on load
5. **AC5**: Optional fields have sensible defaults (status="active", strategy_params={})
6. **AC6**: Configuration example template exists for user reference
7. **AC7**: Unit tests cover valid configs, invalid configs, and edge cases

## Tasks / Subtasks

### Task 1: Create Account Pydantic Models (AC: 1, 4, 5)
- [x] Create `src/accounts/models.py` with MT5Config model
- [x] Create AccountConfig model with nested MT5Config
- [x] Create AccountsConfig model for loading multiple accounts
- [x] Add proper type hints and Field validators
- [x] Add enum for account types: prop_firm, personal, demo

### Task 2: Create Configuration Loader (AC: 1, 2, 3)
- [x] Create `src/config/loader.py` with ConfigLoader class
- [x] Implement YAML file loading with pathlib
- [x] Implement environment variable resolution for password_env fields
- [x] Add error handling with clear messages for missing/invalid files
- [x] Add ConfigValidationError class for user-friendly error formatting

### Task 3: Create Example Configuration Template (AC: 6)
- [x] Create `configs/accounts.yaml.example` with documented structure
- [x] Include examples for all account types (prop_firm, personal, demo)
- [x] Document all fields with inline comments
- [x] Add environment variable naming convention examples

### Task 4: Write Unit Tests (AC: 7)
- [x] Create `tests/unit/test_account_models.py`
- [x] Test valid account configurations
- [x] Test invalid configurations (missing fields, wrong types)
- [x] Test environment variable resolution
- [x] Test edge cases (empty strategy_params, missing optional fields)

## Dev Notes

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**
- Account Manager location: `services/trading-engine/src/accounts/`
- Config location: `services/trading-engine/src/config/`
- Use Pydantic v2 for all configuration models (already in pyproject.toml)
- Use pydantic-settings for environment variable handling
- Account configs stored in `configs/accounts.yaml`

**Critical Patterns:**
- All secrets via environment variables - NEVER in config files
- Configuration validated before engine starts (fail-fast)
- Account IDs must be unique strings (e.g., "ftmo-gold-001")
- MT5 passwords referenced by env var name (e.g., "FTMO_PASS_001")

### Technical Requirements

**Pydantic v2 Patterns (from Context7 Research 2025-12-20):**
```python
from pydantic import BaseModel, Field, field_validator, ValidationError
from pydantic_settings import BaseSettings

class MyConfig(BaseModel):
    field: str = Field(default="value", description="Field description")

    @field_validator('field')
    @classmethod
    def validate_field(cls, v: str) -> str:
        if not v:
            raise ValueError('Field cannot be empty')
        return v
```

**Key Pydantic v2 Changes:**
- Use `model_validate()` instead of `parse_obj()`
- Use `model_dump()` instead of `dict()`
- Validators must be class methods with `@classmethod`
- Use `Field()` for default values and descriptions

**NautilusTrader Note (from Context7 2025-12-20):**
- NautilusTrader has moved away from pydantic to msgspec for its config
- Our account models are separate and should use pydantic v2
- Strategy configs will inherit from NautilusTrader's StrategyConfig

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── accounts/
│   │   ├── __init__.py        # Export: AccountConfig, AccountsConfig, AccountType, MT5Config, SignalFilter
│   │   └── models.py          # NEW: Account Pydantic models
│   └── config/
│       ├── __init__.py        # Export: ConfigLoader, ConfigValidationError
│       └── loader.py          # NEW: YAML config loader with error handling
├── tests/
│   └── unit/
│       └── test_account_models.py  # NEW: Unit tests
configs/
└── accounts.yaml.example      # NEW: Example configuration
```

### Package Exports

**src/accounts/__init__.py:**
```python
from .models import (
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)

__all__ = [
    "AccountConfig",
    "AccountsConfig",
    "AccountType",
    "MT5Config",
    "SignalFilter",
]
```

**src/config/__init__.py:**
```python
from .loader import ConfigLoader, ConfigValidationError

__all__ = ["ConfigLoader", "ConfigValidationError"]
```

### Expected Model Structure

```python
# src/accounts/models.py
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

class AccountType(str, Enum):
    PROP_FIRM = "prop_firm"
    PERSONAL = "personal"
    DEMO = "demo"

class MT5Config(BaseModel):
    """MT5 connection configuration."""
    server: str = Field(..., description="MT5 server name")
    login: int = Field(..., gt=0, description="MT5 login number")
    password_env: str = Field(..., description="Environment variable name for password")

    @field_validator('password_env')
    @classmethod
    def validate_password_env(cls, v: str) -> str:
        if not v.isupper() or not v.replace('_', '').isalnum():
            raise ValueError('password_env must be uppercase with underscores only')
        return v

class SignalFilter(BaseModel):
    """Signal filtering configuration."""
    symbols: list[str] = Field(default_factory=list, description="Allowed symbols")
    sessions: list[str] = Field(default_factory=list, description="Allowed sessions")
    max_spread_pips: Optional[float] = Field(default=None, ge=0, description="Max spread")

class AccountConfig(BaseModel):
    """Single trading account configuration."""
    id: str = Field(..., min_length=1, description="Unique account identifier")
    name: str = Field(..., min_length=1, description="Human-readable name")
    type: AccountType = Field(..., description="Account type")
    prop_firm: Optional[str] = Field(default=None, description="Prop firm preset name")
    rules_file: Optional[str] = Field(default=None, description="Custom rules file path")
    mt5: MT5Config
    strategy: str = Field(..., min_length=1, description="Strategy name")
    strategy_params: dict = Field(default_factory=dict, description="Strategy parameters")
    signal_filter: SignalFilter = Field(default_factory=SignalFilter)
    status: str = Field(default="active", pattern="^(active|paused|stopped)$")

    @field_validator('id')
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v.replace('-', '').replace('_', '').isalnum():
            raise ValueError('id must be alphanumeric with dashes/underscores')
        return v

    @model_validator(mode='after')
    def validate_rules_source(self) -> 'AccountConfig':
        """Validate that prop_firm or rules_file is set for non-demo accounts."""
        if self.type != AccountType.DEMO:
            if not self.prop_firm and not self.rules_file:
                raise ValueError(
                    f"Account '{self.id}' of type '{self.type.value}' must have "
                    "either 'prop_firm' or 'rules_file' specified"
                )
        return self

class AccountsConfig(BaseModel):
    """Root configuration containing all accounts."""
    accounts: list[AccountConfig] = Field(default_factory=list)

    @field_validator('accounts')
    @classmethod
    def validate_unique_ids(cls, v: list[AccountConfig]) -> list[AccountConfig]:
        ids = [acc.id for acc in v]
        if len(ids) != len(set(ids)):
            raise ValueError('Account IDs must be unique')
        return v
```

### Config Loader Pattern

```python
# src/config/loader.py
import os
from pathlib import Path
import yaml
from pydantic import ValidationError
from ..accounts.models import AccountsConfig


class ConfigValidationError(Exception):
    """User-friendly configuration validation error.

    Wraps Pydantic ValidationError with clear, actionable messages.
    """

    def __init__(self, validation_error: ValidationError):
        self.validation_error = validation_error
        self.errors = validation_error.errors()
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format validation errors into readable message."""
        lines = ["Configuration validation failed:"]
        for error in self.errors:
            location = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            lines.append(f"  • {location}: {msg}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self._format_message()


class ConfigLoader:
    """Loads and validates account configurations from YAML."""

    def __init__(self, config_path: Path | str):
        self.config_path = Path(config_path)

    def load(self) -> AccountsConfig:
        """Load and validate accounts configuration."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path) as f:
            raw_config = yaml.safe_load(f)

        if raw_config is None:
            raise ValueError(f"Config file is empty: {self.config_path}")

        try:
            return AccountsConfig.model_validate(raw_config)
        except ValidationError as e:
            raise ConfigValidationError(e) from e

    def resolve_password(self, password_env: str) -> str:
        """Resolve MT5 password from environment variable."""
        password = os.getenv(password_env)
        if not password:
            raise ValueError(f"Environment variable not set: {password_env}")
        return password
```

### Testing Requirements

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run all unit tests
uv run pytest tests/unit/test_account_models.py -v

# Run with coverage
uv run pytest tests/unit/test_account_models.py --cov=src/accounts --cov=src/config

# Run specific test
uv run pytest tests/unit/test_account_models.py::TestAccountModels::test_valid_account_config -v
```

**Test File:**
```python
# tests/unit/test_account_models.py
import pytest
from pydantic import ValidationError
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config

class TestAccountModels:
    def test_valid_account_config(self):
        """Test valid account configuration loads correctly."""
        config = AccountConfig(
            id="ftmo-gold-001",
            name="FTMO Gold Challenge",
            type=AccountType.PROP_FIRM,
            prop_firm="ftmo",
            mt5=MT5Config(
                server="FTMO-Server",
                login=12345678,
                password_env="FTMO_PASS_001"
            ),
            strategy="ma_crossover",
            strategy_params={"fast_period": 20, "slow_period": 50}
        )
        assert config.id == "ftmo-gold-001"
        assert config.status == "active"  # Default value

    def test_missing_required_field(self):
        """Test that missing required fields raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test",
                # Missing: name, type, mt5, strategy
            )
        assert "name" in str(exc_info.value)

    def test_invalid_account_id(self):
        """Test that invalid account ID format is rejected."""
        with pytest.raises(ValidationError):
            AccountConfig(
                id="invalid@id!",  # Invalid characters
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="Test", login=1, password_env="TEST_PASS"),
                strategy="test"
            )

    def test_unique_account_ids(self):
        """Test that duplicate account IDs are rejected."""
        with pytest.raises(ValidationError):
            AccountsConfig(accounts=[
                AccountConfig(id="same-id", name="A", type=AccountType.DEMO,
                    mt5=MT5Config(server="S", login=1, password_env="P"),
                    strategy="s"),
                AccountConfig(id="same-id", name="B", type=AccountType.DEMO,
                    mt5=MT5Config(server="S", login=2, password_env="P"),
                    strategy="s"),
            ])

    def test_prop_firm_requires_rules_source(self):
        """Test that prop_firm accounts require prop_firm or rules_file."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="ftmo-001",
                name="FTMO Account",
                type=AccountType.PROP_FIRM,
                # Missing: prop_firm or rules_file
                mt5=MT5Config(server="S", login=1, password_env="PASS"),
                strategy="test"
            )
        assert "prop_firm" in str(exc_info.value) or "rules_file" in str(exc_info.value)

    def test_demo_account_no_rules_required(self):
        """Test that demo accounts don't require prop_firm or rules_file."""
        config = AccountConfig(
            id="demo-001",
            name="Demo Account",
            type=AccountType.DEMO,
            # No prop_firm or rules_file - should be valid for demo
            mt5=MT5Config(server="S", login=1, password_env="DEMO_PASS"),
            strategy="test"
        )
        assert config.type == AccountType.DEMO
        assert config.prop_firm is None
        assert config.rules_file is None
```

### Project Structure Notes

- All new files follow existing project structure in `services/trading-engine/`
- Uses existing pyproject.toml dependencies (pydantic>=2.0, pydantic-settings>=2.0)
- Test files go in `tests/unit/` directory (create if not exists)
- Config example goes in project root `configs/` directory

### Environment Variables Required

```bash
# Per-account MT5 credentials
FTMO_PASS_001=<mt5_password>
THE5ERS_PASS_001=<mt5_password>
PERSONAL_PASS=<mt5_password>
```

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Service structure and config patterns
- [Source: docs/architecture.md#Multi-Account-Architecture] - Account configuration schema
- [Source: docs/epic-2-context.md#Story-2.1] - Story requirements and code patterns
- [Source: docs/prd.md#Account-Management] - Functional requirements FR1-FR8
- [Source: Context7 Pydantic v2 2025-12-20] - Latest Pydantic patterns and validators

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- PRD: `docs/prd.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Story creation phase

### Completion Notes List

- Story created with comprehensive developer context from artifact analysis
- Latest Pydantic v2 patterns researched via Context7 MCP (2025-12-20)
- NautilusTrader config patterns noted (uses msgspec, not pydantic)
- All acceptance criteria mapped to specific tasks
- Code patterns provided based on architecture and epic context
- **Implementation completed (2025-12-20):**
  - Created all Pydantic v2 models with proper validators (field_validator, model_validator)
  - Implemented ConfigLoader with user-friendly ConfigValidationError
  - Added comprehensive example config with all account types documented
  - Created 37 unit tests covering valid configs, invalid configs, and edge cases
  - All 44 tests pass (including 7 existing engine tests)
  - Linting passes with ruff

### File List

Files created/modified:
- `services/trading-engine/src/accounts/__init__.py` (modified: added exports)
- `services/trading-engine/src/accounts/models.py` (created: Account Pydantic models)
- `services/trading-engine/src/config/__init__.py` (modified: added exports, added ConfigSyntaxError)
- `services/trading-engine/src/config/loader.py` (created: YAML config loader with ConfigSyntaxError)
- `services/trading-engine/tests/unit/test_account_models.py` (created: 41 unit tests)
- `services/trading-engine/pyproject.toml` (modified: added pyyaml>=6.0)
- `services/trading-engine/uv.lock` (auto-generated: dependency lock file)
- `configs/accounts.yaml.example` (created: documented example configuration)
- `docs/sprint-artifacts/sprint-status.yaml` (modified: workflow tracking)

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies (if not already done)
uv sync

# 3. Run unit tests
uv run pytest tests/unit/test_account_models.py -v
# Expected: All tests pass

# 4. Test config loading manually (Python REPL)
uv run python -c "
from src.config.loader import ConfigLoader
from pathlib import Path

# Test with example config (copy and fill in first)
# loader = ConfigLoader(Path('../../configs/accounts.yaml'))
# config = loader.load()
# print(f'Loaded {len(config.accounts)} accounts')
print('Config loader imports successfully')
"

# 5. Test validation errors are user-friendly
uv run python -c "
from src.accounts.models import AccountConfig, AccountType, MT5Config
try:
    AccountConfig(id='test')  # Missing required fields
except Exception as e:
    print(f'Validation error (expected): {type(e).__name__}')
"
```

### Acceptance Criteria Verification

- [x] **AC1**: Run `test_valid_account_config` - config loads from YAML structure
- [x] **AC2**: Run `test_missing_required_field` - clear error with field name shown
- [x] **AC3**: Test `ConfigLoader.resolve_password()` with set/unset env var
- [x] **AC4**: Run `test_missing_required_field` - validates required fields
- [x] **AC5**: Check `test_valid_account_config` - status defaults to "active"
- [x] **AC6**: Verify `configs/accounts.yaml.example` exists with comments
- [x] **AC7**: All pytest tests pass with good coverage

---

## Troubleshooting

### Common Issues

**Import Error: "No module named 'src'"**
```bash
# Ensure you're running from trading-engine directory
cd services/trading-engine
uv run pytest tests/unit/test_account_models.py

# If still failing, check pyproject.toml has correct package config
```

**YAML Parsing Error: "expected <block end>"**
```bash
# YAML is indentation-sensitive. Common fixes:
# - Use spaces, not tabs
# - Ensure consistent 2-space indentation
# - Check for missing colons after keys
```

**ValidationError: "prop_firm or rules_file required"**
```bash
# Non-demo accounts must specify either:
# - prop_firm: "ftmo" (use a preset)
# - rules_file: "path/to/rules.yaml" (use custom rules)
# Demo accounts can omit both
```

**Environment Variable Not Set**
```bash
# MT5 passwords are resolved from env vars at runtime
export FTMO_PASS_001=your_password

# Or add to .env file and use python-dotenv
```

**Pydantic v1 vs v2 Errors**
```bash
# If you see "parse_obj" or "dict()" errors, you're using v1 patterns
# v2 uses: model_validate(), model_dump()
# Check: uv run python -c "import pydantic; print(pydantic.VERSION)"
```

---

## Definition of Done

- [x] `src/accounts/models.py` created with all models (AccountType, MT5Config, SignalFilter, AccountConfig, AccountsConfig)
- [x] `src/accounts/__init__.py` exports all models
- [x] `src/config/loader.py` created with ConfigLoader and ConfigValidationError
- [x] `src/config/__init__.py` exports loader classes
- [x] `configs/accounts.yaml.example` created with documented examples
- [x] `tests/unit/test_account_models.py` created with comprehensive tests (41 tests)
- [x] All unit tests pass: `uv run pytest tests/unit/test_account_models.py` (48 total tests pass)
- [x] Added pyyaml>=6.0 dependency to pyproject.toml for YAML support
- [x] Story status updated to `review` in sprint-status.yaml

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-20 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-20 | Latest Pydantic v2 patterns researched via Context7 MCP |
| 2025-12-20 | **Validation improvements applied:** Fixed task checkboxes (were incorrectly marked done), added ConfigValidationError class, fixed model_validator for rules validation, added __init__.py exports, added test execution commands, added Verification Checklist, added Troubleshooting section, added Definition of Done |
| 2025-12-20 | **Implementation completed:** All tasks implemented following red-green-refactor cycle. Created models.py with AccountType, MT5Config, SignalFilter, AccountConfig, AccountsConfig. Created loader.py with ConfigLoader and ConfigValidationError. Created accounts.yaml.example with comprehensive documentation. Created 37 unit tests. All 44 tests pass. Linting passes. Status updated to Ready for Review. |
| 2025-12-20 | **Code review fixes applied:** (1) Added ConfigSyntaxError for user-friendly YAML parsing errors, (2) Added 4 new tests: malformed YAML, tabs in YAML, empty password env var, example config validation, (3) Fixed type hint `dict` → `dict[str, Any]` for strategy_params, (4) Fixed bullet character `- ` → `• ` in error formatting, (5) Updated File List to include uv.lock and sprint-status.yaml, (6) Commented out extra example accounts for cleaner user experience. Total: 41 tests pass. |
