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
    AccountConfig,
    AccountsConfig,
    AccountType,
    MT5Config,
    SignalFilter,
)
from src.config.loader import ConfigLoader, ConfigSyntaxError, ConfigValidationError


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
        """Test that duplicate account IDs are rejected."""
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
        assert "unique" in str(exc_info.value).lower() or "ids" in str(exc_info.value).lower()


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
