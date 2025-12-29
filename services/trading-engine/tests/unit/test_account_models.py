"""Unit tests for Account Pydantic models.

Tests cover:
- Valid account configurations
- Invalid configurations (missing fields, wrong types)
- Environment variable resolution
- Edge cases (empty strategy_params, missing optional fields)
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.accounts.models import (
    MAX_ACCOUNTS,
    VALID_PROP_FIRMS,
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)
from src.config.loader import ConfigLoader, ConfigSyntaxError, ConfigValidationError, warn_missing_password_env


class TestMT5Config:
    """Tests for MT5Config model."""

    def test_valid_mt5_config(self):
        """Test valid MT5 configuration loads correctly."""
        config = MT5Config(
            server="FTMO-Server",
            login=12345678,
            password_env="FTMO_PASS_001",
        )
        assert config.server == "FTMO-Server"
        assert config.login == 12345678
        assert config.password_env == "FTMO_PASS_001"

    def test_invalid_login_zero(self):
        """Test that login must be greater than 0."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                login=0,
                password_env="TEST_PASS",
            )
        assert "login" in str(exc_info.value)

    def test_invalid_login_negative(self):
        """Test that login must be positive."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                login=-1,
                password_env="TEST_PASS",
            )
        assert "login" in str(exc_info.value)

    def test_invalid_password_env_lowercase(self):
        """Test that password_env must be uppercase."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                login=12345,
                password_env="ftmo_pass",  # Invalid: lowercase
            )
        assert "password_env" in str(exc_info.value)

    def test_invalid_password_env_special_chars(self):
        """Test that password_env rejects special characters."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                login=12345,
                password_env="FTMO@PASS",  # Invalid: special character
            )
        assert "password_env" in str(exc_info.value)

    def test_valid_password_env_with_underscores(self):
        """Test that password_env accepts underscores."""
        config = MT5Config(
            server="Test-Server",
            login=12345,
            password_env="FTMO_GOLD_PASS_001",
        )
        assert config.password_env == "FTMO_GOLD_PASS_001"


class TestSignalFilter:
    """Tests for SignalFilter model."""

    def test_default_signal_filter(self):
        """Test that SignalFilter has sensible defaults."""
        config = SignalFilter()
        assert config.symbols == []
        assert config.sessions == []
        assert config.max_spread_pips is None

    def test_signal_filter_with_values(self):
        """Test SignalFilter with custom values."""
        config = SignalFilter(
            symbols=["EURUSD", "GBPUSD"],
            sessions=["london", "new_york"],
            max_spread_pips=2.5,
        )
        assert config.symbols == ["EURUSD", "GBPUSD"]
        assert config.sessions == ["london", "new_york"]
        assert config.max_spread_pips == 2.5

    def test_invalid_max_spread_negative(self):
        """Test that max_spread_pips must be non-negative."""
        with pytest.raises(ValidationError) as exc_info:
            SignalFilter(max_spread_pips=-1.0)
        assert "max_spread_pips" in str(exc_info.value)


class TestAccountType:
    """Tests for AccountType enum."""

    def test_account_type_values(self):
        """Test all account type values exist."""
        assert AccountType.PROP_FIRM.value == "prop_firm"
        assert AccountType.PERSONAL.value == "personal"
        assert AccountType.DEMO.value == "demo"

    def test_account_type_from_string(self):
        """Test AccountType can be created from string."""
        assert AccountType("prop_firm") == AccountType.PROP_FIRM
        assert AccountType("personal") == AccountType.PERSONAL
        assert AccountType("demo") == AccountType.DEMO


class TestAccountConfig:
    """Tests for AccountConfig model."""

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
                password_env="FTMO_PASS_001",
            ),
            strategy="ma_crossover",
            strategy_params={"fast_period": 20, "slow_period": 50},
        )
        assert config.id == "ftmo-gold-001"
        assert config.name == "FTMO Gold Challenge"
        assert config.type == AccountType.PROP_FIRM
        assert config.status == "active"  # Default value

    def test_valid_account_with_rules_file(self):
        """Test prop_firm account with rules_file instead of prop_firm preset."""
        config = AccountConfig(
            id="custom-001",
            name="Custom Rules Account",
            type=AccountType.PERSONAL,
            rules_file="configs/custom_rules.yaml",
            mt5=MT5Config(
                server="Personal-Server",
                login=99999,
                password_env="PERSONAL_PASS",
            ),
            strategy="breakout",
        )
        assert config.rules_file == "configs/custom_rules.yaml"
        assert config.prop_firm is None

    def test_default_values(self):
        """Test that optional fields have sensible defaults."""
        config = AccountConfig(
            id="demo-001",
            name="Demo Account",
            type=AccountType.DEMO,
            mt5=MT5Config(
                server="Demo-Server",
                login=12345,
                password_env="DEMO_PASS",
            ),
            strategy="test",
        )
        assert config.status == "active"
        assert config.strategy_params == {}
        assert config.signal_filter.symbols == []
        assert config.prop_firm is None
        assert config.rules_file is None

    def test_missing_required_field_name(self):
        """Test that missing name field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test",
                # Missing: name
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
            )
        assert "name" in str(exc_info.value)

    def test_missing_required_field_mt5(self):
        """Test that missing mt5 field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test",
                name="Test",
                type=AccountType.DEMO,
                # Missing: mt5
                strategy="test",
            )
        assert "mt5" in str(exc_info.value)

    def test_missing_required_field_strategy(self):
        """Test that missing strategy field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test",
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                # Missing: strategy
            )
        assert "strategy" in str(exc_info.value)

    def test_invalid_account_id_special_chars(self):
        """Test that invalid account ID format is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="invalid@id!",  # Invalid characters
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="Test", login=1, password_env="TEST_PASS"),
                strategy="test",
            )
        assert "id" in str(exc_info.value)

    def test_valid_account_id_with_dash_underscore(self):
        """Test that account ID accepts dashes and underscores."""
        config = AccountConfig(
            id="ftmo_gold-001",
            name="Test",
            type=AccountType.DEMO,
            mt5=MT5Config(server="Test", login=1, password_env="TEST_PASS"),
            strategy="test",
        )
        assert config.id == "ftmo_gold-001"

    def test_empty_account_id_rejected(self):
        """Test that empty account ID is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="",
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
            )
        assert "id" in str(exc_info.value)

    def test_prop_firm_requires_rules_source(self):
        """Test that prop_firm accounts require prop_firm or rules_file."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="ftmo-001",
                name="FTMO Account",
                type=AccountType.PROP_FIRM,
                # Missing: prop_firm or rules_file
                mt5=MT5Config(server="S", login=1, password_env="PASS"),
                strategy="test",
            )
        error_str = str(exc_info.value)
        assert "prop_firm" in error_str or "rules_file" in error_str

    def test_personal_requires_rules_source(self):
        """Test that personal accounts also require prop_firm or rules_file."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="personal-001",
                name="Personal Account",
                type=AccountType.PERSONAL,
                # Missing: prop_firm or rules_file
                mt5=MT5Config(server="S", login=1, password_env="PASS"),
                strategy="test",
            )
        error_str = str(exc_info.value)
        assert "prop_firm" in error_str or "rules_file" in error_str

    def test_demo_account_no_rules_required(self):
        """Test that demo accounts don't require prop_firm or rules_file."""
        config = AccountConfig(
            id="demo-001",
            name="Demo Account",
            type=AccountType.DEMO,
            # No prop_firm or rules_file - should be valid for demo
            mt5=MT5Config(server="S", login=1, password_env="DEMO_PASS"),
            strategy="test",
        )
        assert config.type == AccountType.DEMO
        assert config.prop_firm is None
        assert config.rules_file is None

    def test_invalid_status_value(self):
        """Test that invalid status values are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test-001",
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
                status="invalid_status",
            )
        assert "status" in str(exc_info.value)

    def test_valid_status_values(self):
        """Test that all valid status values are accepted."""
        for status in ["active", "paused", "stopped"]:
            config = AccountConfig(
                id="test-001",
                name="Test",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
                status=status,
            )
            assert config.status == status


class TestAccountsConfig:
    """Tests for AccountsConfig model (collection of accounts)."""

    def test_empty_accounts_list(self):
        """Test that empty accounts list is valid."""
        config = AccountsConfig(accounts=[])
        assert config.accounts == []

    def test_single_account(self):
        """Test AccountsConfig with single account."""
        account = AccountConfig(
            id="demo-001",
            name="Demo",
            type=AccountType.DEMO,
            mt5=MT5Config(server="S", login=1, password_env="P"),
            strategy="test",
        )
        config = AccountsConfig(accounts=[account])
        assert len(config.accounts) == 1
        assert config.accounts[0].id == "demo-001"

    def test_multiple_accounts(self):
        """Test AccountsConfig with multiple accounts."""
        accounts = [
            AccountConfig(
                id="demo-001",
                name="Demo 1",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
            ),
            AccountConfig(
                id="demo-002",
                name="Demo 2",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=2, password_env="P"),
                strategy="test",
            ),
        ]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 2

    def test_duplicate_account_ids_rejected(self):
        """Test that duplicate account IDs are rejected with AC3-compliant error format."""
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(
                accounts=[
                    AccountConfig(
                        id="same-id",
                        name="A",
                        type=AccountType.DEMO,
                        mt5=MT5Config(server="S", login=1, password_env="P"),
                        strategy="s",
                    ),
                    AccountConfig(
                        id="same-id",
                        name="B",
                        type=AccountType.DEMO,
                        mt5=MT5Config(server="S", login=2, password_env="P"),
                        strategy="s",
                    ),
                ]
            )
        # AC3: Error message must be "Duplicate account ID: {id}"
        assert "Duplicate account ID: same-id" in str(exc_info.value)


class TestConfigLoader:
    """Tests for ConfigLoader class."""

    def test_load_valid_yaml(self, tmp_path):
        """Test loading a valid YAML configuration file."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: demo-001
    name: Demo Account
    type: demo
    mt5:
      server: Demo-Server
      login: 12345
      password_env: DEMO_PASS
    strategy: ma_crossover
    strategy_params:
      fast_period: 20
      slow_period: 50
"""
        )

        loader = ConfigLoader(config_file)
        config = loader.load()

        assert len(config.accounts) == 1
        assert config.accounts[0].id == "demo-001"
        assert config.accounts[0].strategy_params == {"fast_period": 20, "slow_period": 50}

    def test_load_file_not_found(self, tmp_path):
        """Test that FileNotFoundError is raised for missing file."""
        loader = ConfigLoader(tmp_path / "nonexistent.yaml")
        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load()
        assert "not found" in str(exc_info.value).lower()

    def test_load_empty_file(self, tmp_path):
        """Test that empty config file raises ValueError."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        loader = ConfigLoader(config_file)
        with pytest.raises(ValueError) as exc_info:
            loader.load()
        assert "empty" in str(exc_info.value).lower()

    def test_load_invalid_yaml_raises_config_error(self, tmp_path):
        """Test that invalid config raises ConfigValidationError."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(
            """
accounts:
  - id: test
    # Missing required fields: name, type, mt5, strategy
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()
        assert "validation failed" in str(exc_info.value).lower()

    def test_config_validation_error_formatting(self, tmp_path):
        """Test that ConfigValidationError formats errors clearly."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(
            """
accounts:
  - id: test
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()

        error_message = str(exc_info.value)
        # Should contain field location indicators
        assert "name" in error_message or "type" in error_message

    def test_resolve_password_success(self):
        """Test that password is resolved from environment variable."""
        loader = ConfigLoader("dummy.yaml")

        with patch.dict(os.environ, {"TEST_MT5_PASS": "secret123"}):
            password = loader.resolve_password("TEST_MT5_PASS")
            assert password == "secret123"

    def test_resolve_password_missing_env_var(self):
        """Test that missing environment variable raises ValueError."""
        loader = ConfigLoader("dummy.yaml")

        # Ensure the env var is not set
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                loader.resolve_password("NONEXISTENT_VAR")
            assert "not set" in str(exc_info.value).lower()

    def test_load_multiple_accounts(self, tmp_path):
        """Test loading multiple accounts from YAML."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: ftmo-001
    name: FTMO Gold
    type: prop_firm
    prop_firm: ftmo
    mt5:
      server: FTMO-Server
      login: 11111
      password_env: FTMO_PASS_001
    strategy: ma_crossover

  - id: demo-001
    name: Demo Account
    type: demo
    mt5:
      server: Demo-Server
      login: 22222
      password_env: DEMO_PASS
    strategy: breakout
"""
        )

        loader = ConfigLoader(config_file)
        config = loader.load()

        assert len(config.accounts) == 2
        assert config.accounts[0].id == "ftmo-001"
        assert config.accounts[0].type == AccountType.PROP_FIRM
        assert config.accounts[1].id == "demo-001"
        assert config.accounts[1].type == AccountType.DEMO

    def test_load_malformed_yaml_raises_syntax_error(self, tmp_path):
        """Test that malformed YAML raises ConfigSyntaxError with helpful message."""
        config_file = tmp_path / "malformed.yaml"
        config_file.write_text(
            """
accounts:
  - id: test
    name  missing colon here
    type: demo
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigSyntaxError) as exc_info:
            loader.load()

        error_message = str(exc_info.value)
        assert "YAML syntax error" in error_message
        assert "malformed.yaml" in error_message
        # Should provide helpful guidance
        assert "missing colons" in error_message.lower() or "indentation" in error_message.lower()

    def test_load_yaml_with_tabs_raises_syntax_error(self, tmp_path):
        """Test that YAML with tabs raises ConfigSyntaxError."""
        config_file = tmp_path / "tabs.yaml"
        # YAML doesn't allow tabs for indentation
        config_file.write_text("accounts:\n\t- id: test\n")

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigSyntaxError) as exc_info:
            loader.load()

        assert "YAML syntax error" in str(exc_info.value)

    def test_resolve_password_empty_env_var(self):
        """Test that empty environment variable raises ValueError."""
        loader = ConfigLoader("dummy.yaml")

        with patch.dict(os.environ, {"EMPTY_PASS": ""}):
            with pytest.raises(ValueError) as exc_info:
                loader.resolve_password("EMPTY_PASS")
            assert "not set" in str(exc_info.value).lower()

    def test_example_config_is_valid(self):
        """Validate the example config file is syntactically correct and parseable."""
        from pathlib import Path

        # Navigate from tests/unit/ to configs/
        example_path = Path(__file__).parent.parent.parent.parent.parent / "configs" / "accounts.yaml.example"

        if example_path.exists():
            loader = ConfigLoader(example_path)
            config = loader.load()
            # Example should have multiple accounts demonstrating different types
            assert len(config.accounts) >= 1
            # Verify we have different account types represented
            account_types = {acc.type for acc in config.accounts}
            assert AccountType.PROP_FIRM in account_types
            assert AccountType.DEMO in account_types


# =============================================================================
# MULTI-ACCOUNT CONFIGURATION TESTS (Story 3.1)
# =============================================================================


def _create_demo_account(account_id: str) -> AccountConfig:
    """Create a minimal demo account for testing.

    Args:
        account_id: Unique identifier for the account.

    Returns:
        A demo AccountConfig instance.
    """
    return AccountConfig(
        id=account_id,
        name=f"Demo {account_id}",
        type=AccountType.DEMO,
        mt5=MT5Config(server="Demo-Server", login=1, password_env="DEMO_PASS"),
        strategy="test",
    )


def _create_prop_firm_account(account_id: str, prop_firm: str = "ftmo") -> AccountConfig:
    """Create a prop firm account for testing.

    Args:
        account_id: Unique identifier for the account.
        prop_firm: Prop firm preset name. Defaults to "ftmo".

    Returns:
        A prop firm AccountConfig instance.
    """
    return AccountConfig(
        id=account_id,
        name=f"Prop {account_id}",
        type=AccountType.PROP_FIRM,
        prop_firm=prop_firm,
        mt5=MT5Config(server="FTMO-Server", login=12345, password_env="FTMO_PASS"),
        strategy="ma_crossover",
    )


def _create_personal_account(account_id: str, rules_file: str = "rules.yaml") -> AccountConfig:
    """Create a personal account with custom rules for testing.

    Args:
        account_id: Unique identifier for the account.
        rules_file: Path to custom rules file. Defaults to "rules.yaml".

    Returns:
        A personal AccountConfig instance with custom rules.
    """
    return AccountConfig(
        id=account_id,
        name=f"Personal {account_id}",
        type=AccountType.PERSONAL,
        rules_file=rules_file,
        mt5=MT5Config(server="Personal-Server", login=99999, password_env="PERSONAL_PASS"),
        strategy="scalper",
    )


class TestMaxAccountsValidation:
    """Tests for maximum accounts validation (AC2)."""

    def test_constants_defined(self):
        """Verify MAX_ACCOUNTS and VALID_PROP_FIRMS constants are defined."""
        assert MAX_ACCOUNTS == 5
        assert VALID_PROP_FIRMS == frozenset({"ftmo", "the5ers", "wmt"})

    def test_zero_accounts_allowed(self):
        """Boundary: zero accounts should be valid (well under max)."""
        config = AccountsConfig(accounts=[])
        assert len(config.accounts) == 0

    def test_exactly_five_accounts_allowed(self):
        """Boundary: exactly 5 accounts (the limit) must pass (AC2)."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(5)]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 5

    def test_four_accounts_allowed(self):
        """Test 4 accounts is well under the limit."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(4)]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 4

    def test_three_accounts_allowed(self):
        """Test 3 accounts is well under the limit."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(3)]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 3

    def test_two_accounts_allowed(self):
        """Test 2 accounts loads correctly."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(2)]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 2

    def test_max_accounts_exceeded_six(self):
        """6 accounts must fail with specific error message (AC2)."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(6)]
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(accounts=accounts)
        # AC2: Error must be "Maximum 5 accounts supported"
        assert "Maximum 5 accounts supported" in str(exc_info.value)

    def test_max_accounts_exceeded_seven(self):
        """7 accounts must also fail."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(7)]
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(accounts=accounts)
        assert "Maximum 5 accounts supported" in str(exc_info.value)

    def test_max_accounts_error_includes_helpful_suggestion(self):
        """Error message should suggest how to fix the issue."""
        accounts = [_create_demo_account(f"demo-{i}") for i in range(8)]
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(accounts=accounts)
        error_msg = str(exc_info.value)
        assert "Got 8 accounts" in error_msg
        assert "Remove 3 account(s)" in error_msg


class TestDuplicateIdValidation:
    """Tests for duplicate account ID validation (AC3)."""

    def test_duplicate_account_id_error_format(self):
        """Error message must match AC3: 'Duplicate account ID: {id}'"""
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(
                accounts=[
                    _create_demo_account("dup-001"),
                    _create_demo_account("dup-001"),
                ]
            )
        assert "Duplicate account ID: dup-001" in str(exc_info.value)

    def test_first_duplicate_reported(self):
        """When multiple duplicates exist, the first one encountered is reported."""
        with pytest.raises(ValidationError) as exc_info:
            AccountsConfig(
                accounts=[
                    _create_demo_account("first"),
                    _create_demo_account("first"),
                    _create_demo_account("second"),
                    _create_demo_account("second"),
                ]
            )
        # Should report the first duplicate found
        assert "Duplicate account ID: first" in str(exc_info.value)

    def test_unique_ids_allowed(self):
        """Accounts with unique IDs should load successfully."""
        config = AccountsConfig(
            accounts=[
                _create_demo_account("account-a"),
                _create_demo_account("account-b"),
                _create_demo_account("account-c"),
            ]
        )
        assert len(config.accounts) == 3


class TestPropFirmValidation:
    """Tests for prop firm preset validation (AC4)."""

    def test_invalid_prop_firm_preset(self):
        """Unknown prop firm must fail with helpful error (AC4)."""
        with pytest.raises(ValidationError) as exc_info:
            AccountConfig(
                id="test-001",
                name="Test Account",
                type=AccountType.PROP_FIRM,
                prop_firm="Invalid_Firm",
                mt5=MT5Config(server="S", login=1, password_env="P"),
                strategy="test",
            )
        error_msg = str(exc_info.value)
        # AC4: Error must be "Unknown prop firm preset: {prop_firm}"
        # Note: prop_firm is normalized to lowercase before validation
        assert "Unknown prop firm preset: 'invalid_firm'" in error_msg
        # Should list valid presets
        assert "ftmo" in error_msg
        assert "the5ers" in error_msg
        assert "wmt" in error_msg

    def test_prop_firm_case_insensitive_uppercase(self):
        """FTMO (uppercase) should be normalized to lowercase."""
        acc = _create_prop_firm_account("test-001", prop_firm="FTMO")
        assert acc.prop_firm == "ftmo"

    def test_prop_firm_case_insensitive_mixed(self):
        """Ftmo (mixed case) should be normalized to lowercase."""
        acc = _create_prop_firm_account("test-001", prop_firm="Ftmo")
        assert acc.prop_firm == "ftmo"

    def test_prop_firm_case_insensitive_lowercase(self):
        """ftmo (lowercase) should work as-is."""
        acc = _create_prop_firm_account("test-001", prop_firm="ftmo")
        assert acc.prop_firm == "ftmo"

    def test_all_valid_prop_firms(self):
        """All valid prop firm presets should be accepted."""
        for prop_firm in VALID_PROP_FIRMS:
            acc = _create_prop_firm_account(f"test-{prop_firm}", prop_firm=prop_firm)
            assert acc.prop_firm == prop_firm

    def test_the5ers_case_variations(self):
        """The5ers case variations should all work."""
        for variant in ["the5ers", "THE5ERS", "The5ers"]:
            acc = _create_prop_firm_account("test-001", prop_firm=variant)
            assert acc.prop_firm == "the5ers"

    def test_wmt_case_variations(self):
        """WMT case variations should all work."""
        for variant in ["wmt", "WMT", "Wmt"]:
            acc = _create_prop_firm_account("test-001", prop_firm=variant)
            assert acc.prop_firm == "wmt"


class TestMT5ConfigValidation:
    """Tests for MT5 configuration validation (AC5)."""

    def test_missing_mt5_server(self):
        """Missing MT5 server should fail validation (AC5)."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                # server missing
                login=12345,
                password_env="TEST_PASS",
            )
        assert "server" in str(exc_info.value).lower()

    def test_missing_mt5_login(self):
        """Missing MT5 login should fail validation (AC5)."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                # login missing
                password_env="TEST_PASS",
            )
        assert "login" in str(exc_info.value).lower()

    def test_missing_mt5_password_env(self):
        """Missing MT5 password_env should fail validation (AC5)."""
        with pytest.raises(ValidationError) as exc_info:
            MT5Config(
                server="Test-Server",
                login=12345,
                # password_env missing
            )
        assert "password_env" in str(exc_info.value).lower()


class TestMixedAccountTypes:
    """Tests for loading mixed account types (AC1)."""

    def test_load_mixed_account_types(self):
        """prop_firm + custom + demo accounts load together (AC1)."""
        accounts = [
            _create_prop_firm_account("ftmo-001"),
            _create_personal_account("personal-001"),
            _create_demo_account("demo-001"),
        ]
        config = AccountsConfig(accounts=accounts)

        types = {acc.type for acc in config.accounts}
        assert types == {AccountType.PROP_FIRM, AccountType.PERSONAL, AccountType.DEMO}

    def test_multiple_prop_firm_accounts(self):
        """Multiple prop firm accounts with different firms should load."""
        accounts = [
            _create_prop_firm_account("ftmo-001", prop_firm="ftmo"),
            _create_prop_firm_account("5ers-001", prop_firm="the5ers"),
            _create_prop_firm_account("wmt-001", prop_firm="wmt"),
        ]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 3

        prop_firms = {acc.prop_firm for acc in config.accounts}
        assert prop_firms == {"ftmo", "the5ers", "wmt"}

    def test_mixed_five_accounts_at_limit(self):
        """5 mixed accounts (the limit) should load successfully."""
        accounts = [
            _create_prop_firm_account("ftmo-001"),
            _create_prop_firm_account("5ers-001", prop_firm="the5ers"),
            _create_personal_account("personal-001"),
            _create_demo_account("demo-001"),
            _create_demo_account("demo-002"),
        ]
        config = AccountsConfig(accounts=accounts)
        assert len(config.accounts) == 5


class TestWarnMissingPasswordEnv:
    """Tests for warn_missing_password_env utility function."""

    def test_warns_when_env_not_set(self, caplog):
        """Should log warning when password env var is not set."""
        import logging

        with caplog.at_level(logging.WARNING):
            accounts = [_create_demo_account("test-001")]
            # DEMO_PASS is not set in environment
            with patch.dict(os.environ, {}, clear=True):
                warn_missing_password_env(accounts)

        assert "Account 'test-001'" in caplog.text
        assert "DEMO_PASS" in caplog.text
        assert "is not set" in caplog.text

    def test_no_warning_when_env_is_set(self, caplog):
        """Should not log warning when password env var is set."""
        import logging

        with caplog.at_level(logging.WARNING):
            accounts = [_create_demo_account("test-001")]
            with patch.dict(os.environ, {"DEMO_PASS": "secret123"}):
                warn_missing_password_env(accounts)

        assert "test-001" not in caplog.text

    def test_warns_for_each_missing_env(self, caplog):
        """Should warn for each account with missing env var."""
        import logging

        # Create accounts with different password env vars
        accounts = [
            AccountConfig(
                id="acc-1",
                name="Account 1",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=1, password_env="PASS_ONE"),
                strategy="test",
            ),
            AccountConfig(
                id="acc-2",
                name="Account 2",
                type=AccountType.DEMO,
                mt5=MT5Config(server="S", login=2, password_env="PASS_TWO"),
                strategy="test",
            ),
        ]

        with caplog.at_level(logging.WARNING):
            with patch.dict(os.environ, {}, clear=True):
                warn_missing_password_env(accounts)

        assert "acc-1" in caplog.text
        assert "PASS_ONE" in caplog.text
        assert "acc-2" in caplog.text
        assert "PASS_TWO" in caplog.text


class TestConfigLoaderMultiAccount:
    """Integration tests for ConfigLoader with multi-account configs."""

    def test_load_five_accounts_from_yaml(self, tmp_path):
        """Load 5 accounts (at limit) from YAML file."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: demo-1
    name: Demo 1
    type: demo
    mt5: {server: S, login: 1, password_env: P}
    strategy: test
  - id: demo-2
    name: Demo 2
    type: demo
    mt5: {server: S, login: 2, password_env: P}
    strategy: test
  - id: demo-3
    name: Demo 3
    type: demo
    mt5: {server: S, login: 3, password_env: P}
    strategy: test
  - id: demo-4
    name: Demo 4
    type: demo
    mt5: {server: S, login: 4, password_env: P}
    strategy: test
  - id: demo-5
    name: Demo 5
    type: demo
    mt5: {server: S, login: 5, password_env: P}
    strategy: test
"""
        )

        loader = ConfigLoader(config_file)
        config = loader.load()
        assert len(config.accounts) == 5

    def test_load_six_accounts_fails(self, tmp_path):
        """Loading 6 accounts should fail with clear error."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: demo-1
    name: Demo 1
    type: demo
    mt5: {server: S, login: 1, password_env: P}
    strategy: test
  - id: demo-2
    name: Demo 2
    type: demo
    mt5: {server: S, login: 2, password_env: P}
    strategy: test
  - id: demo-3
    name: Demo 3
    type: demo
    mt5: {server: S, login: 3, password_env: P}
    strategy: test
  - id: demo-4
    name: Demo 4
    type: demo
    mt5: {server: S, login: 4, password_env: P}
    strategy: test
  - id: demo-5
    name: Demo 5
    type: demo
    mt5: {server: S, login: 5, password_env: P}
    strategy: test
  - id: demo-6
    name: Demo 6
    type: demo
    mt5: {server: S, login: 6, password_env: P}
    strategy: test
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()
        assert "Maximum 5 accounts supported" in str(exc_info.value)

    def test_load_duplicate_id_fails(self, tmp_path):
        """Loading config with duplicate IDs should fail with clear error."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: same-id
    name: Account A
    type: demo
    mt5: {server: S, login: 1, password_env: P}
    strategy: test
  - id: same-id
    name: Account B
    type: demo
    mt5: {server: S, login: 2, password_env: P}
    strategy: test
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()
        assert "Duplicate account ID: same-id" in str(exc_info.value)

    def test_load_invalid_prop_firm_fails(self, tmp_path):
        """Loading config with invalid prop_firm should fail with clear error."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: prop-001
    name: Prop Account
    type: prop_firm
    prop_firm: nonexistent_firm
    mt5: {server: S, login: 1, password_env: P}
    strategy: test
"""
        )

        loader = ConfigLoader(config_file)
        with pytest.raises(ConfigValidationError) as exc_info:
            loader.load()
        assert "Unknown prop firm preset" in str(exc_info.value)

    def test_load_mixed_account_types_from_yaml(self, tmp_path):
        """Load mixed account types from YAML file."""
        config_file = tmp_path / "accounts.yaml"
        config_file.write_text(
            """
accounts:
  - id: ftmo-001
    name: FTMO Gold
    type: prop_firm
    prop_firm: FTMO
    mt5:
      server: FTMO-Server
      login: 12345678
      password_env: FTMO_PASS
    strategy: ma_crossover

  - id: personal-001
    name: Personal Trading
    type: personal
    rules_file: configs/custom_rules.yaml
    mt5:
      server: Personal-Server
      login: 87654321
      password_env: PERSONAL_PASS
    strategy: scalper

  - id: demo-001
    name: Demo Testing
    type: demo
    mt5:
      server: Demo-Server
      login: 99999999
      password_env: DEMO_PASS
    strategy: test
"""
        )

        loader = ConfigLoader(config_file)
        config = loader.load()

        assert len(config.accounts) == 3

        # Verify prop_firm was normalized to lowercase
        ftmo_acc = next(a for a in config.accounts if a.id == "ftmo-001")
        assert ftmo_acc.prop_firm == "ftmo"  # Normalized from "FTMO"

        # Verify all types are present
        types = {acc.type for acc in config.accounts}
        assert types == {AccountType.PROP_FIRM, AccountType.PERSONAL, AccountType.DEMO}
