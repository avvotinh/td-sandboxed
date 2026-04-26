"""Unit tests for rule assignment module (Story 3.7).

Tests cover:
- RuleAssignment dataclass and from_account_config factory
- RuleParser YAML parsing
- RulePresetLoader preset loading
- CustomRuleLoader custom file loading
- RuleAssignmentService orchestration
"""

from unittest.mock import MagicMock

import pytest

from src.accounts.models import AccountConfig, AccountType, MT5Config
from src.rules.assignment import RuleAssignment
from src.rules.assignment_service import RuleAssignmentService
from src.rules.base_rule import BaseRule, RuleAction, RuleResult
from src.rules.custom_loader import CustomRuleLoader, RulesFileInvalidError, RulesFileNotFoundError
from src.rules.parser import RuleParseError, RuleParser
from src.rules.preset_loader import PresetNotFoundError, RulePresetLoader


# =============================================================================
# TEST FIXTURES
# =============================================================================


def _create_mt5_config() -> MT5Config:
    """Create a minimal MT5 config for testing."""
    return MT5Config(server="Test-Server", login=12345, password_env="TEST_PASS")


def _create_prop_firm_account(
    account_id: str = "ftmo-001",
    prop_firm: str = "ftmo",
) -> AccountConfig:
    """Create a prop firm account for testing."""
    return AccountConfig(
        id=account_id,
        name=f"Prop {account_id}",
        type=AccountType.PROP_FIRM,
        prop_firm=prop_firm,
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


# =============================================================================
# RuleAssignment Tests (Task 1)
# =============================================================================


class TestRuleAssignment:
    """Tests for RuleAssignment dataclass."""

    def test_from_account_config_prop_firm(self):
        """Test RuleAssignment.from_account_config for prop_firm account (AC1)."""
        account = _create_prop_firm_account("ftmo-001", "ftmo")
        assignment = RuleAssignment.from_account_config(account)

        assert assignment.assignment_type == "preset"
        assert assignment.preset_name == "ftmo"
        assert assignment.rules_file is None
        assert assignment.rules == []

    def test_from_account_config_the5ers(self):
        """Test RuleAssignment.from_account_config for the5ers account (AC2)."""
        account = _create_prop_firm_account("5ers-001", "the5ers")
        assignment = RuleAssignment.from_account_config(account)

        assert assignment.assignment_type == "preset"
        assert assignment.preset_name == "the5ers"

    def test_from_account_config_personal(self):
        """Test RuleAssignment.from_account_config for personal account (AC3)."""
        account = _create_personal_account("personal-001", "my_rules.yaml")
        assignment = RuleAssignment.from_account_config(account)

        assert assignment.assignment_type == "personal"
        assert assignment.rules_file == "my_rules.yaml"
        assert assignment.preset_name is None

    def test_from_account_config_demo(self):
        """Test RuleAssignment.from_account_config for demo account (AC4)."""
        account = _create_demo_account("demo-001")
        assignment = RuleAssignment.from_account_config(account)

        assert assignment.assignment_type == "none"
        assert assignment.preset_name is None
        assert assignment.rules_file is None

    def test_source_description_preset(self):
        """Test source_description property for preset assignment."""
        assignment = RuleAssignment(assignment_type="preset", preset_name="ftmo")
        assert assignment.source_description == "preset:ftmo"

    def test_source_description_personal(self):
        """Test source_description property for personal assignment."""
        assignment = RuleAssignment(assignment_type="personal", rules_file="my_rules.yaml")
        assert assignment.source_description == "personal:my_rules.yaml"

    def test_source_description_none(self):
        """Test source_description property for no assignment."""
        assignment = RuleAssignment(assignment_type="none")
        assert assignment.source_description == "none"

    def test_has_rules_property(self):
        """Test has_rules property."""
        assert RuleAssignment(assignment_type="preset", preset_name="ftmo").has_rules is True
        assert RuleAssignment(assignment_type="personal", rules_file="x.yaml").has_rules is True
        assert RuleAssignment(assignment_type="none").has_rules is False

    def test_validation_preset_requires_name(self):
        """Test that preset type requires preset_name."""
        with pytest.raises(ValueError) as exc_info:
            RuleAssignment(assignment_type="preset")  # Missing preset_name
        assert "preset_name is required" in str(exc_info.value)

    def test_validation_personal_requires_file(self):
        """Test that personal type requires rules_file."""
        with pytest.raises(ValueError) as exc_info:
            RuleAssignment(assignment_type="personal")  # Missing rules_file
        assert "rules_file is required" in str(exc_info.value)


# =============================================================================
# RuleParser Tests (Task 3)
# =============================================================================


class TestRuleParser:
    """Tests for RuleParser class."""

    def test_parse_rules_valid(self):
        """Test parsing valid YAML rules."""
        parser = RuleParser()
        yaml_content = {
            "name": "Test Rules",
            "version": "1.0",
            "rules": [
                {"type": "daily_loss_limit", "threshold_percent": 5.0},
                {"type": "max_drawdown", "threshold_percent": 10.0},
            ],
        }

        rules = parser.parse_rules(yaml_content)

        assert len(rules) == 2
        assert rules[0].rule_type == "daily_loss_limit"
        assert rules[1].rule_type == "max_drawdown"

    def test_parse_rules_missing_rules_key(self):
        """Test parsing fails when 'rules' key is missing."""
        parser = RuleParser()
        yaml_content = {"name": "Test"}  # Missing 'rules' key

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(yaml_content)
        assert "must contain 'rules' key" in str(exc_info.value)

    def test_parse_rules_invalid_rules_not_list(self):
        """Test parsing fails when 'rules' is not a list."""
        parser = RuleParser()
        yaml_content = {"rules": "not a list"}

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(yaml_content)
        assert "'rules' must be a list" in str(exc_info.value)

    def test_parse_rules_missing_type_field(self):
        """Test parsing fails when rule is missing 'type' field."""
        parser = RuleParser()
        yaml_content = {
            "rules": [{"threshold_percent": 5.0}]  # Missing 'type'
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(yaml_content)
        assert "must have 'type' field" in str(exc_info.value)

    def test_parse_rules_unknown_type(self):
        """Test parsing fails for unknown rule type."""
        parser = RuleParser()
        yaml_content = {
            "rules": [{"type": "unknown_rule_type"}]
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(yaml_content)
        assert "Unknown rule type" in str(exc_info.value)
        assert "unknown_rule_type" in str(exc_info.value)

    def test_parse_rules_all_valid_types(self):
        """Test all known rule types can be parsed."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {"type": "daily_loss_limit", "threshold_percent": 5.0},
                {"type": "max_drawdown", "threshold_percent": 10.0},
                {"type": "max_position_size", "max_risk_percent": 2.0},
                {"type": "profit_target", "threshold_percent": 10.0},
                {"type": "min_trading_days", "required_days": 4},
            ],
        }

        rules = parser.parse_rules(yaml_content)
        assert len(rules) == 5

    def test_get_available_types(self):
        """Test get_available_types returns expected types."""
        parser = RuleParser()
        types = parser.get_available_types()

        assert "daily_loss_limit" in types
        assert "max_drawdown" in types
        assert "max_position_size" in types
        assert "profit_target" in types
        assert "min_trading_days" in types


# =============================================================================
# RulePresetLoader Tests (Task 2)
# =============================================================================


class TestRulePresetLoader:
    """Tests for RulePresetLoader class."""

    def test_get_available_presets(self):
        """Test listing available presets."""
        loader = RulePresetLoader()
        presets = loader.get_available_presets()

        assert "ftmo" in presets
        assert "the5ers" in presets
        assert "wmt" in presets

    def test_load_preset_ftmo(self):
        """Test loading FTMO preset (AC1)."""
        loader = RulePresetLoader()
        rules = loader.load_preset("ftmo")

        assert len(rules) > 0
        # FTMO should have daily loss limit and max drawdown rules
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types

    def test_load_preset_the5ers(self):
        """Test loading The5ers preset (AC2)."""
        loader = RulePresetLoader()
        rules = loader.load_preset("the5ers")

        assert len(rules) > 0
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types

    def test_load_preset_wmt(self):
        """Test loading WMT preset."""
        loader = RulePresetLoader()
        rules = loader.load_preset("wmt")

        assert len(rules) > 0

    def test_load_preset_case_insensitive(self):
        """Test preset loading is case-insensitive."""
        loader = RulePresetLoader()

        # All these should load the same preset
        rules_lower = loader.load_preset("ftmo")
        loader.clear_cache()  # Clear cache between tests
        rules_upper = loader.load_preset("FTMO")
        loader.clear_cache()
        rules_mixed = loader.load_preset("Ftmo")

        assert len(rules_lower) == len(rules_upper) == len(rules_mixed)

    def test_load_preset_not_found(self):
        """Test PresetNotFoundError for unknown preset (AC5)."""
        loader = RulePresetLoader()

        with pytest.raises(PresetNotFoundError) as exc_info:
            loader.load_preset("nonexistent_preset")

        error = exc_info.value
        assert "nonexistent_preset" in str(error)
        # Should list available presets
        assert "ftmo" in str(error).lower()
        assert "the5ers" in str(error).lower()

    def test_load_preset_caching(self):
        """Test preset caching works."""
        loader = RulePresetLoader()

        # First load
        rules1 = loader.load_preset("ftmo")
        # Second load should return cached result
        rules2 = loader.load_preset("ftmo")

        # Same objects (cached)
        assert rules1 is rules2

    def test_clear_cache(self):
        """Test clearing preset cache."""
        loader = RulePresetLoader()

        rules1 = loader.load_preset("ftmo")
        loader.clear_cache()
        rules2 = loader.load_preset("ftmo")

        # Different objects after cache clear
        assert rules1 is not rules2


# =============================================================================
# CustomRuleLoader Tests (Task 4)
# =============================================================================


class TestCustomRuleLoader:
    """Tests for CustomRuleLoader class."""

    def test_load_custom_rules_valid(self, tmp_path):
        """Test loading valid custom rules file."""
        # Create a valid rules file
        rules_file = tmp_path / "test_rules.yaml"
        rules_file.write_text("""
name: "Test Rules"
version: "1.0"
rules:
  - type: daily_loss_limit
    threshold_percent: 3.0
  - type: max_drawdown
    threshold_percent: 6.0
""")

        loader = CustomRuleLoader(config_dir=tmp_path)
        rules = loader.load_custom_rules("test_rules.yaml")

        assert len(rules) == 2
        assert rules[0].rule_type == "daily_loss_limit"
        assert rules[1].rule_type == "max_drawdown"

    def test_load_custom_rules_file_not_found(self, tmp_path):
        """Test RulesFileNotFoundError for missing file (AC6)."""
        loader = CustomRuleLoader(config_dir=tmp_path)

        with pytest.raises(RulesFileNotFoundError) as exc_info:
            loader.load_custom_rules("nonexistent.yaml")

        error = exc_info.value
        assert "nonexistent.yaml" in str(error)
        # Should include full path
        assert str(tmp_path) in str(error.resolved_path)

    def test_load_custom_rules_absolute_path(self, tmp_path):
        """Test loading rules from absolute path."""
        rules_file = tmp_path / "absolute_rules.yaml"
        rules_file.write_text("""
name: "Absolute Path Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 2.0
""")

        loader = CustomRuleLoader()
        rules = loader.load_custom_rules(str(rules_file))

        assert len(rules) == 1

    def test_load_custom_rules_relative_path(self, tmp_path):
        """Test loading rules from relative path."""
        rules_file = tmp_path / "relative_rules.yaml"
        rules_file.write_text("""
name: "Relative Path Rules"
rules:
  - type: max_drawdown
    threshold_percent: 5.0
""")

        loader = CustomRuleLoader(config_dir=tmp_path)
        rules = loader.load_custom_rules("relative_rules.yaml")

        assert len(rules) == 1

    def test_load_custom_rules_invalid_yaml(self, tmp_path):
        """Test error for invalid YAML."""
        rules_file = tmp_path / "invalid.yaml"
        rules_file.write_text("invalid: yaml: content:")

        loader = CustomRuleLoader(config_dir=tmp_path)

        with pytest.raises(RulesFileInvalidError) as exc_info:
            loader.load_custom_rules("invalid.yaml")
        assert "YAML parsing error" in str(exc_info.value)

    def test_load_custom_rules_empty_file(self, tmp_path):
        """Test error for empty file."""
        rules_file = tmp_path / "empty.yaml"
        rules_file.write_text("")

        loader = CustomRuleLoader(config_dir=tmp_path)

        with pytest.raises(RulesFileInvalidError) as exc_info:
            loader.load_custom_rules("empty.yaml")
        assert "empty" in str(exc_info.value).lower()

    def test_validate_rules_file(self, tmp_path):
        """Test validate_rules_file returns metadata."""
        rules_file = tmp_path / "validate_test.yaml"
        rules_file.write_text("""
name: "Validation Test"
version: "2.0"
description: "Test description"
rules:
  - type: daily_loss_limit
    threshold_percent: 5.0
  - type: max_drawdown
    threshold_percent: 10.0
""")

        loader = CustomRuleLoader(config_dir=tmp_path)
        info = loader.validate_rules_file("validate_test.yaml")

        assert info["name"] == "Validation Test"
        assert info["version"] == "2.0"
        assert info["description"] == "Test description"
        assert info["rule_count"] == 2
        assert info["valid"] is True


# =============================================================================
# RuleAssignmentService Tests (Task 5)
# =============================================================================


class TestRuleAssignmentService:
    """Tests for RuleAssignmentService class."""

    def test_get_rules_for_prop_firm_account(self):
        """Test getting rules for prop firm account (AC1, AC2)."""
        service = RuleAssignmentService()
        account = _create_prop_firm_account("ftmo-001", "ftmo")

        rules = service.get_rules_for_account(account)

        assert len(rules) > 0
        rule_types = [r.rule_type for r in rules]
        assert "daily_loss_limit" in rule_types

    def test_get_rules_for_personal_account(self, tmp_path):
        """Test getting rules for personal account (AC3)."""
        # Create custom rules file
        rules_file = tmp_path / "personal_rules.yaml"
        rules_file.write_text("""
name: "Personal Rules"
rules:
  - type: daily_loss_limit
    threshold_percent: 2.0
""")

        # Create service with custom config dir
        preset_loader = RulePresetLoader()
        custom_loader = CustomRuleLoader(config_dir=tmp_path)
        service = RuleAssignmentService(
            preset_loader=preset_loader,
            custom_loader=custom_loader,
        )

        account = _create_personal_account("personal-001", "personal_rules.yaml")
        rules = service.get_rules_for_account(account)

        assert len(rules) == 1
        assert rules[0].rule_type == "daily_loss_limit"

    def test_get_rules_for_demo_account(self):
        """Test getting rules for demo account returns empty list (AC4)."""
        service = RuleAssignmentService()
        account = _create_demo_account("demo-001")

        rules = service.get_rules_for_account(account)

        assert rules == []

    def test_get_assignment_for_account(self):
        """Test getting assignment metadata."""
        service = RuleAssignmentService()
        account = _create_prop_firm_account("ftmo-001", "ftmo")

        assignment = service.get_assignment_for_account(account)

        assert assignment.assignment_type == "preset"
        assert assignment.preset_name == "ftmo"

    def test_get_available_presets(self):
        """Test listing available presets through service."""
        service = RuleAssignmentService()
        presets = service.get_available_presets()

        assert "ftmo" in presets
        assert "the5ers" in presets
        assert "wmt" in presets

    def test_preset_not_found_error_propagates(self):
        """Test PresetNotFoundError propagates from service (AC5)."""
        service = RuleAssignmentService()

        # Create account with invalid prop_firm (bypassing model validation)
        account = MagicMock(spec=AccountConfig)
        account.id = "test-001"
        account.type = AccountType.PROP_FIRM
        account.prop_firm = "invalid_preset"
        account.rules_file = None
        account.firm_id = None
        account.product_id = None
        account.phase = None
        account.rule_overrides = {}

        with pytest.raises(PresetNotFoundError):
            service.get_rules_for_account(account)

    def test_rules_file_not_found_error_propagates(self):
        """Test RulesFileNotFoundError propagates from service (AC6)."""
        service = RuleAssignmentService()

        # Create account with non-existent rules file (bypassing model validation)
        account = MagicMock(spec=AccountConfig)
        account.id = "test-001"
        account.type = AccountType.PERSONAL
        account.prop_firm = None
        account.rules_file = "nonexistent_rules.yaml"
        account.firm_id = None
        account.product_id = None
        account.phase = None
        account.rule_overrides = {}

        with pytest.raises(RulesFileNotFoundError):
            service.get_rules_for_account(account)


# =============================================================================
# BaseRule Protocol Tests
# =============================================================================


class TestBaseRule:
    """Tests for BaseRule protocol and related types."""

    def test_rule_action_values(self):
        """Test RuleAction enum values."""
        assert RuleAction.ALLOW.value == "allow"
        assert RuleAction.WARN.value == "warn"
        assert RuleAction.BLOCK.value == "block"

    def test_rule_result_is_allowed(self):
        """Test RuleResult.is_allowed property."""
        assert RuleResult(action=RuleAction.ALLOW).is_allowed is True
        assert RuleResult(action=RuleAction.WARN).is_allowed is True
        assert RuleResult(action=RuleAction.BLOCK).is_allowed is False

    def test_rule_result_is_blocked(self):
        """Test RuleResult.is_blocked property."""
        assert RuleResult(action=RuleAction.ALLOW).is_blocked is False
        assert RuleResult(action=RuleAction.WARN).is_blocked is False
        assert RuleResult(action=RuleAction.BLOCK).is_blocked is True

    def test_rule_result_with_message(self):
        """Test RuleResult with message."""
        result = RuleResult(
            action=RuleAction.BLOCK,
            message="Daily loss limit exceeded",
        )
        assert result.message == "Daily loss limit exceeded"

    def test_rule_result_with_metadata(self):
        """Test RuleResult with metadata."""
        result = RuleResult(
            action=RuleAction.WARN,
            metadata={"current_loss": 4.5, "limit": 5.0},
        )
        assert result.metadata["current_loss"] == 4.5
        assert result.metadata["limit"] == 5.0

    def test_protocol_compliance(self):
        """Test that a class can satisfy BaseRule protocol.

        Updated in Story 4.1 to include new protocol requirements:
        - name and priority attributes
        - get_current_value(), get_threshold(), get_warning_thresholds() methods
        """

        class TestRule:
            rule_type = "test_rule"
            name = "Test Rule"
            priority = 50

            def validate(self, context):
                return RuleResult(action=RuleAction.ALLOW)

            def get_current_value(self, context):
                return 0.0

            def get_threshold(self):
                return 100.0

            def get_warning_thresholds(self):
                return [70.0, 80.0, 90.0]

        rule = TestRule()
        assert isinstance(rule, BaseRule)
