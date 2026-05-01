"""Integration tests for rule assignment flow (Story 3.7).

Tests cover:
- Full flow: load account config → assign FTMO rules → verify rule count (AC1)
- Full flow: load account config → assign custom rules → verify rules applied (AC3)
- Demo account has no rules after initialization (AC4)
- Account rules isolation: Account A rules don't affect Account B
- AccountManager integration with RuleAssignmentService
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config
from src.config.firm_registry import FirmRegistry
from src.rules.assignment_service import RuleAssignmentService
from src.rules.custom_loader import CustomRuleLoader
from src.rules.preset_loader import RulePresetLoader


# Story 10.12 — every prop-firm-flavoured test now resolves rules
# through the firm registry. Loading the shipped configs once keeps
# the firm-bound branch hot without each test re-reading YAML.
_FIRMS_DIR = Path(__file__).resolve().parents[4] / "configs" / "firms"


def _service_with_firm_registry(**kwargs) -> RuleAssignmentService:
    """Build a :class:`RuleAssignmentService` with the firm registry wired.

    Mirrors what the production lifecycle does — every test that exercises
    a prop-firm account needs the registry to resolve ``firm:ftmo/...``.
    """
    registry = FirmRegistry(_FIRMS_DIR)
    registry.load()
    return RuleAssignmentService(firm_registry=registry, **kwargs)


# =============================================================================
# TEST FIXTURES
# =============================================================================


def _create_mt5_config() -> MT5Config:
    """Create a minimal MT5 config for testing."""
    return MT5Config(server="Test-Server", login=12345, password_env="TEST_PASS")


def _create_prop_firm_account(
    account_id: str = "ftmo-001",
    firm_id: str = "ftmo",
    product_id: str = "challenge",
    phase: str = "evaluation",
) -> AccountConfig:
    """Create a firm-bound prop firm account for testing.

    Story 10.12 — the legacy ``prop_firm`` preset source is gone.
    """
    return AccountConfig(
        id=account_id,
        name=f"Prop {account_id}",
        type=AccountType.PROP_FIRM,
        firm_id=firm_id,
        product_id=product_id,
        phase=phase,
        mt5=_create_mt5_config(),
        strategy="ma_crossover",
    )


def _create_personal_account(
    account_id: str = "personal-001",
    rules_file: str = "custom_rules.yaml",
) -> AccountConfig:
    """Create a personal account with custom rules for testing."""
    return AccountConfig(
        id=account_id,
        name=f"Personal {account_id}",
        type=AccountType.PERSONAL,
        rules_file=rules_file,
        mt5=_create_mt5_config(),
        strategy="scalper",
    )


def _create_demo_account(account_id: str = "demo-001") -> AccountConfig:
    """Create a demo account for testing."""
    return AccountConfig(
        id=account_id,
        name=f"Demo {account_id}",
        type=AccountType.DEMO,
        mt5=_create_mt5_config(),
        strategy="test",
    )


@pytest.fixture
def mock_redis_manager():
    """Create a mock Redis manager for testing."""
    mock = AsyncMock()
    mock.save_account_status = AsyncMock()
    mock.get_account_status = AsyncMock(return_value="active")
    mock.update_account_health = AsyncMock()
    mock.clear_account_health = AsyncMock()
    mock.publish_alert = AsyncMock()
    mock.save_account_last_error = AsyncMock()
    mock.close = AsyncMock()
    return mock


# =============================================================================
# Full Flow Integration Tests
# =============================================================================


class TestFullFlowFTMORules:
    """Test full flow: load account config → assign FTMO rules → verify rule count (AC1, 11.1)."""

    def test_ftmo_rules_full_flow(self):
        """Test complete flow for FTMO prop firm account."""
        # Create account config
        account = _create_prop_firm_account("ftmo-gold-001", "ftmo")

        # Create rule assignment service
        service = _service_with_firm_registry()

        # Get rules for account
        rules = service.get_rules_for_account(account)

        # Verify rules were loaded
        assert len(rules) >= 2, "FTMO should have at least daily_loss and max_drawdown rules"

        # Verify rule types
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types, "FTMO must have daily_loss_limit rule"
        assert "max_drawdown" in rule_types, "FTMO must have max_drawdown rule"

    def test_the5ers_rules_full_flow(self):
        """Test complete flow for The5ers prop firm account (AC2)."""
        account = _create_prop_firm_account(
            "5ers-001", firm_id="the5ers", product_id="bootstrap", phase="funded"
        )
        service = _service_with_firm_registry()

        rules = service.get_rules_for_account(account)

        assert len(rules) >= 2
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types


class TestFullFlowCustomRules:
    """Test full flow: load account config → assign custom rules → verify rules applied (AC3, 11.2)."""

    def test_custom_rules_full_flow(self, tmp_path):
        """Test complete flow for personal account with custom rules."""
        # Create custom rules file
        rules_file = tmp_path / "my_custom_rules.yaml"
        rules_file.write_text("""
name: "My Custom Rules"
version: "1.0"
description: "Custom trading rules for my personal account"
rules:
  - type: daily_loss_limit
    threshold_percent: 2.0
    action: block_trading
  - type: max_drawdown
    threshold_percent: 5.0
    action: block_trading
  - type: max_position_size
    max_risk_percent: 1.5
    action: block_trading
""")

        # Create account config
        account = _create_personal_account("personal-001", "my_custom_rules.yaml")

        # Create service with custom config dir
        custom_loader = CustomRuleLoader(config_dir=tmp_path)
        service = RuleAssignmentService(custom_loader=custom_loader)

        # Get rules for account
        rules = service.get_rules_for_account(account)

        # Verify correct number of rules
        assert len(rules) == 3, "Custom file should have 3 rules"

        # Verify rule types match file
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types
        assert "max_position_size" in rule_types


class TestDemoAccountNoRules:
    """Test demo account has no rules after initialization (AC4, 11.3)."""

    def test_demo_account_no_rules(self):
        """Test that demo accounts get no rules assigned."""
        account = _create_demo_account("demo-001")
        service = _service_with_firm_registry()

        rules = service.get_rules_for_account(account)

        assert rules == [], "Demo account should have no rules"
        assert len(rules) == 0


class TestAccountRulesIsolation:
    """Test account rules isolation: Account A rules don't affect Account B (11.4)."""

    def test_rules_isolation_between_accounts(self, tmp_path):
        """Test that rules are isolated per account."""
        # Create custom rules for Account B
        rules_file = tmp_path / "account_b_rules.yaml"
        rules_file.write_text("""
name: "Account B Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 1.0
""")

        # Create accounts
        account_a = _create_prop_firm_account("ftmo-001", "ftmo")
        account_b = _create_personal_account("personal-001", "account_b_rules.yaml")
        account_c = _create_demo_account("demo-001")

        # Service with both firm registry (for account_a) and custom loader (for account_b).
        custom_loader = CustomRuleLoader(config_dir=tmp_path)
        service = _service_with_firm_registry(custom_loader=custom_loader)

        # Get rules for each account
        rules_a = service.get_rules_for_account(account_a)
        rules_b = service.get_rules_for_account(account_b)
        rules_c = service.get_rules_for_account(account_c)

        # Verify each account has different rules
        assert len(rules_a) > 1, "Account A (FTMO) should have multiple rules"
        assert len(rules_b) == 1, "Account B (custom) should have 1 rule"
        assert len(rules_c) == 0, "Account C (demo) should have no rules"

        # Verify rules are different objects (not shared)
        if rules_a and rules_b:
            assert rules_a[0] is not rules_b[0], "Rules should not be shared between accounts"


# =============================================================================
# AccountManager Integration Tests
# =============================================================================


class TestAccountManagerRuleIntegration:
    """Tests for AccountManager integration with RuleAssignmentService."""

    def test_set_rule_assignment_service(self, mock_redis_manager):
        """Test setting rule assignment service on AccountManager."""
        manager = AccountManager(mock_redis_manager)
        service = _service_with_firm_registry()

        manager.set_rule_assignment_service(service)

        assert manager.get_rule_assignment_service() is service

    def test_get_account_rules_empty_without_service(self, mock_redis_manager):
        """Test get_account_rules returns empty when no service configured."""
        manager = AccountManager(mock_redis_manager)

        rules = manager.get_account_rules("any-account")

        assert rules == []

    def test_initialize_account_rules_loads_preset(self, mock_redis_manager):
        """Test _initialize_account_rules loads preset rules."""
        manager = AccountManager(mock_redis_manager)
        service = _service_with_firm_registry()
        manager.set_rule_assignment_service(service)

        # Load account config
        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)

        # Initialize rules
        manager._initialize_account_rules("ftmo-001")

        # Verify rules were loaded
        rules = manager.get_account_rules("ftmo-001")
        assert len(rules) > 0
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types

    def test_initialize_account_rules_demo_no_rules(self, mock_redis_manager):
        """Test _initialize_account_rules gives empty list for demo."""
        manager = AccountManager(mock_redis_manager)
        service = _service_with_firm_registry()
        manager.set_rule_assignment_service(service)

        account = _create_demo_account("demo-001")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)

        manager._initialize_account_rules("demo-001")

        rules = manager.get_account_rules("demo-001")
        assert rules == []

    def test_initialize_rules_skipped_without_service(self, mock_redis_manager):
        """Test _initialize_account_rules is a no-op without service."""
        manager = AccountManager(mock_redis_manager)
        # No rule assignment service set

        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)

        # Should not raise error
        manager._initialize_account_rules("ftmo-001")

        # Should return empty since no service
        rules = manager.get_account_rules("ftmo-001")
        assert rules == []

    def test_multiple_accounts_rules_isolation(self, mock_redis_manager, tmp_path):
        """Test rules isolation across multiple accounts in AccountManager."""
        # Create custom rules for personal account
        rules_file = tmp_path / "personal_rules.yaml"
        rules_file.write_text("""
name: "Personal Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 1.5
""")

        # Setup AccountManager
        manager = AccountManager(mock_redis_manager)
        custom_loader = CustomRuleLoader(config_dir=tmp_path)
        service = _service_with_firm_registry(custom_loader=custom_loader)
        manager.set_rule_assignment_service(service)

        # Load multiple accounts
        accounts = [
            _create_prop_firm_account("ftmo-001", "ftmo"),
            _create_personal_account("personal-001", "personal_rules.yaml"),
            _create_demo_account("demo-001"),
        ]
        config = AccountsConfig(accounts=accounts)
        manager.load_accounts(config)

        # Initialize rules for all accounts
        for acc in accounts:
            manager._initialize_account_rules(acc.id)

        # Verify isolation
        ftmo_rules = manager.get_account_rules("ftmo-001")
        personal_rules = manager.get_account_rules("personal-001")
        demo_rules = manager.get_account_rules("demo-001")

        assert len(ftmo_rules) > 1, "FTMO should have multiple rules"
        assert len(personal_rules) == 1, "Personal should have 1 rule"
        assert len(demo_rules) == 0, "Demo should have no rules"

        # Verify rules are different objects
        assert ftmo_rules is not personal_rules


# =============================================================================
# Preset File Validation Tests
# =============================================================================


class TestPresetFilesExist:
    """Tests to verify preset files exist and are valid."""

    def test_ftmo_preset_exists(self):
        """Test FTMO preset file exists and is valid."""
        loader = RulePresetLoader()
        rules = loader.load_preset("ftmo")
        assert len(rules) > 0

    def test_the5ers_preset_exists(self):
        """Test The5ers preset file exists and is valid."""
        loader = RulePresetLoader()
        rules = loader.load_preset("the5ers")
        assert len(rules) > 0

    def test_wmt_preset_exists(self):
        """Test WMT preset file exists and is valid."""
        loader = RulePresetLoader()
        rules = loader.load_preset("wmt")
        assert len(rules) > 0

    def test_preset_info_available(self):
        """Test preset info can be retrieved."""
        loader = RulePresetLoader()

        for preset in ["ftmo", "the5ers", "wmt"]:
            info = loader.get_preset_info(preset)
            assert "name" in info
            assert "version" in info
            assert "rule_count" in info
            assert info["rule_count"] > 0


class TestExampleCustomRulesFile:
    """Tests for example custom rules file."""

    def test_example_custom_rules_loadable(self):
        """Test example custom rules file can be loaded."""
        # Path to example file relative to trading-engine service
        example_path = Path(__file__).parent.parent.parent / "configs" / "example_custom_rules.yaml"

        if example_path.exists():
            loader = CustomRuleLoader(config_dir=example_path.parent)
            rules = loader.load_custom_rules("example_custom_rules.yaml")
            assert len(rules) > 0

            # Verify it has expected rule types
            rule_types = [r.rule_type for r in rules]
            assert "daily_loss_limit" in rule_types
            assert "max_drawdown" in rule_types
