"""Integration tests for FTMO preset loading and rule processing (Story 4.5).

Tests cover:
- Loading FTMO preset via RulePresetLoader (AC2)
- All 5 rules are loaded with correct types (AC1, AC4)
- RuleEngine processes all FTMO rules correctly
- Preset version tracking (AC3)
- Invalid YAML schema detection (AC6)
- Rule priorities are correct
"""

import pytest

from src.rules import (
    DailyLossLimitRule,
    MaxDrawdownRule,
    MaxPositionSizeRule,
    RuleAction,
    RuleEngine,
    RuleEngineFactory,
    RuleParseError,
    RuleParser,
)
from src.rules.preset_loader import RulePresetLoader
from src.rules.types.targets import MinTradingDaysRule, ProfitTargetRule


class TestFTMOPresetLoading:
    """Tests for loading FTMO preset via RulePresetLoader (AC2)."""

    def test_load_ftmo_preset_returns_rules(self):
        """Load FTMO preset should return a list of rules."""
        loader = RulePresetLoader()
        rules = loader.load_preset("ftmo")

        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_load_ftmo_preset_returns_5_rules(self):
        """FTMO preset should contain exactly 5 rules (AC4)."""
        loader = RulePresetLoader()
        rules = loader.load_preset("ftmo")

        assert len(rules) == 5

    def test_ftmo_preset_case_insensitive(self):
        """Preset name should be case-insensitive."""
        loader = RulePresetLoader()

        rules_lower = loader.load_preset("ftmo")
        loader.clear_cache()  # Clear cache to force reload
        rules_upper = loader.load_preset("FTMO")

        assert len(rules_lower) == len(rules_upper)

    def test_ftmo_preset_is_cached(self):
        """FTMO preset should be cached after first load."""
        loader = RulePresetLoader()

        rules1 = loader.load_preset("ftmo")
        rules2 = loader.load_preset("ftmo")

        # Same object references (from cache)
        assert rules1 is rules2


class TestFTMOPresetRuleTypes:
    """Tests for verifying correct rule types are loaded (AC1, AC4)."""

    @pytest.fixture
    def ftmo_rules(self):
        """Load FTMO rules for testing."""
        loader = RulePresetLoader()
        loader.clear_cache()
        return loader.load_preset("ftmo")

    def test_contains_daily_loss_limit_rule(self, ftmo_rules):
        """FTMO preset should contain DailyLossLimitRule."""
        daily_loss_rules = [r for r in ftmo_rules if isinstance(r, DailyLossLimitRule)]
        assert len(daily_loss_rules) == 1

    def test_contains_max_drawdown_rule(self, ftmo_rules):
        """FTMO preset should contain MaxDrawdownRule."""
        max_dd_rules = [r for r in ftmo_rules if isinstance(r, MaxDrawdownRule)]
        assert len(max_dd_rules) == 1

    def test_contains_max_position_size_rule(self, ftmo_rules):
        """FTMO preset should contain MaxPositionSizeRule."""
        pos_rules = [r for r in ftmo_rules if isinstance(r, MaxPositionSizeRule)]
        assert len(pos_rules) == 1

    def test_contains_profit_target_rule(self, ftmo_rules):
        """FTMO preset should contain ProfitTargetRule."""
        profit_rules = [r for r in ftmo_rules if isinstance(r, ProfitTargetRule)]
        assert len(profit_rules) == 1

    def test_contains_min_trading_days_rule(self, ftmo_rules):
        """FTMO preset should contain MinTradingDaysRule."""
        days_rules = [r for r in ftmo_rules if isinstance(r, MinTradingDaysRule)]
        assert len(days_rules) == 1

    def test_no_placeholder_rules(self, ftmo_rules):
        """FTMO preset should NOT contain any placeholder rules."""
        for rule in ftmo_rules:
            assert "Placeholder" not in type(rule).__name__, (
                f"Placeholder rule found: {type(rule).__name__}"
            )


class TestFTMOPresetRuleConfiguration:
    """Tests for verifying correct rule configurations (AC4)."""

    @pytest.fixture
    def ftmo_rules_by_type(self):
        """Load FTMO rules indexed by type."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")
        return {r.rule_type: r for r in rules}

    def test_daily_loss_limit_threshold_is_5_percent(self, ftmo_rules_by_type):
        """Daily loss limit should be 5%."""
        rule = ftmo_rules_by_type["daily_loss_limit"]
        assert rule.threshold_percent == 5.0

    def test_daily_loss_limit_timezone_is_cet(self, ftmo_rules_by_type):
        """Daily loss limit should use CET timezone."""
        rule = ftmo_rules_by_type["daily_loss_limit"]
        assert rule.timezone == "CET"

    def test_daily_loss_limit_warnings(self, ftmo_rules_by_type):
        """Daily loss limit should warn at 70, 80, 90%."""
        rule = ftmo_rules_by_type["daily_loss_limit"]
        assert rule.warning_at == [70.0, 80.0, 90.0]

    def test_max_drawdown_threshold_is_10_percent(self, ftmo_rules_by_type):
        """Max drawdown should be 10%."""
        rule = ftmo_rules_by_type["max_drawdown"]
        assert rule.threshold_percent == 10.0

    def test_max_drawdown_reference_is_initial_balance(self, ftmo_rules_by_type):
        """Max drawdown should reference initial_balance."""
        rule = ftmo_rules_by_type["max_drawdown"]
        assert rule.reference == "initial_balance"

    def test_max_position_size_has_scaling(self, ftmo_rules_by_type):
        """Max position size should use per_10k_balance scaling."""
        rule = ftmo_rules_by_type["max_position_size"]
        assert rule.scaling == "per_10k_balance"
        assert rule.max_lots == 100.0

    def test_profit_target_threshold_is_10_percent(self, ftmo_rules_by_type):
        """Profit target should be 10%."""
        rule = ftmo_rules_by_type["profit_target"]
        assert rule.threshold_percent == 10.0

    def test_min_trading_days_is_4(self, ftmo_rules_by_type):
        """Minimum trading days should be 4."""
        rule = ftmo_rules_by_type["min_trading_days"]
        assert rule.required_days == 4


class TestFTMOPresetRulePriorities:
    """Tests for verifying correct rule priorities."""

    @pytest.fixture
    def ftmo_rules_by_type(self):
        """Load FTMO rules indexed by type."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")
        return {r.rule_type: r for r in rules}

    def test_daily_loss_limit_priority_is_1(self, ftmo_rules_by_type):
        """Daily loss limit should have priority 1 (critical)."""
        rule = ftmo_rules_by_type["daily_loss_limit"]
        assert rule.priority == 1

    def test_max_drawdown_priority_is_2(self, ftmo_rules_by_type):
        """Max drawdown should have priority 2 (critical)."""
        rule = ftmo_rules_by_type["max_drawdown"]
        assert rule.priority == 2

    def test_max_position_size_priority_is_3(self, ftmo_rules_by_type):
        """Max position size should have priority 3 (important)."""
        rule = ftmo_rules_by_type["max_position_size"]
        assert rule.priority == 3

    def test_profit_target_priority_is_100(self, ftmo_rules_by_type):
        """Profit target should have priority 100 (informational)."""
        rule = ftmo_rules_by_type["profit_target"]
        assert rule.priority == 100

    def test_min_trading_days_priority_is_100(self, ftmo_rules_by_type):
        """Min trading days should have priority 100 (informational)."""
        rule = ftmo_rules_by_type["min_trading_days"]
        assert rule.priority == 100


class TestFTMOPresetVersionTracking:
    """Tests for preset version tracking (AC3)."""

    def test_preset_has_version_2025_1(self):
        """FTMO preset should have version 2025.1."""
        loader = RulePresetLoader()
        info = loader.get_preset_info("ftmo")

        assert info["version"] == "2025.1"

    def test_preset_has_name(self):
        """FTMO preset should have a name."""
        loader = RulePresetLoader()
        info = loader.get_preset_info("ftmo")

        assert info["name"] == "FTMO Challenge"

    def test_preset_has_description(self):
        """FTMO preset should have a description."""
        loader = RulePresetLoader()
        info = loader.get_preset_info("ftmo")

        assert info["description"]
        assert "5 rules" in info["description"]

    def test_preset_info_shows_5_rules(self):
        """Preset info should show 5 rules."""
        loader = RulePresetLoader()
        info = loader.get_preset_info("ftmo")

        assert info["rule_count"] == 5


class TestFTMORuleEngineIntegration:
    """Tests for RuleEngine processing all FTMO rules."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")
        return RuleEngine(account_id="test-ftmo-001", rules=rules)

    def test_engine_validates_all_rules(self, ftmo_engine):
        """RuleEngine should validate all 5 FTMO rules."""
        context = {
            "daily_pnl_percent": -2.0,  # 2% loss
            "total_drawdown_percent": 5.0,  # 5% drawdown
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 5.0,  # 5% profit
            "trading_days_count": 3,  # 3 days
        }

        result = ftmo_engine.validate(context, continue_after_block=True)

        # Should evaluate all rules
        assert len(result.all_results) == 5

    def test_engine_allows_compliant_trade(self, ftmo_engine):
        """RuleEngine should allow a trade within all limits."""
        context = {
            "daily_pnl_percent": -1.0,  # 1% loss (within 5%)
            "total_drawdown_percent": 2.0,  # 2% drawdown (within 10%)
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 3.0,  # 3% profit
            "trading_days_count": 2,  # 2 days
        }

        result = ftmo_engine.validate(context)

        assert result.is_allowed
        assert not result.is_blocked

    def test_engine_blocks_daily_loss_violation(self, ftmo_engine):
        """RuleEngine should block when daily loss limit is exceeded."""
        context = {
            "daily_pnl_percent": -5.5,  # 5.5% loss (exceeds 5%)
            "total_drawdown_percent": 2.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": -5.0,
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        assert result.is_blocked

    def test_engine_blocks_max_drawdown_violation(self, ftmo_engine):
        """RuleEngine should block when max drawdown is exceeded."""
        context = {
            "daily_pnl_percent": -1.0,
            "total_drawdown_percent": 11.0,  # 11% drawdown (exceeds 10%)
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": -10.0,
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        assert result.is_blocked

    def test_engine_returns_warnings(self, ftmo_engine):
        """RuleEngine should return warnings when approaching limits."""
        context = {
            "daily_pnl_percent": -3.5,  # 70% of 5% = warning
            "total_drawdown_percent": 2.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 3.0,
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        # Should have at least one warning
        assert len(result.warnings) >= 1

    def test_informational_rules_notify_when_met(self, ftmo_engine):
        """Informational rules should WARN when targets/requirements are met."""
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 10.0,  # 10% profit (target met!)
            "trading_days_count": 4,  # 4 days (requirement met!)
        }

        result = ftmo_engine.validate(context)

        # Should still be allowed (informational rules don't block)
        assert result.is_allowed

        # Should have warnings for both informational rules
        assert len(result.warnings) >= 2


class TestInvalidYAMLSchemaDetection:
    """Tests for invalid YAML schema detection (AC6)."""

    def test_invalid_yaml_missing_rules_key(self):
        """AC6: Invalid YAML detected with clear error - missing 'rules' key."""
        parser = RuleParser()
        invalid_yaml = {"name": "Test", "version": "1.0"}  # No 'rules' key

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(invalid_yaml)

        assert "rules" in str(exc_info.value).lower()

    def test_invalid_yaml_unknown_rule_type(self):
        """AC6: Invalid YAML detected - unknown rule type."""
        parser = RuleParser()
        invalid_yaml = {
            "name": "Test",
            "rules": [{"type": "unknown_rule_type", "value": 5.0}]
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(invalid_yaml)

        assert "unknown_rule_type" in str(exc_info.value)

    def test_invalid_yaml_missing_type_field(self):
        """AC6: Invalid YAML detected - rule missing 'type' field."""
        parser = RuleParser()
        invalid_yaml = {
            "name": "Test",
            "rules": [{"threshold_percent": 5.0}]  # No 'type' field
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(invalid_yaml)

        assert "type" in str(exc_info.value).lower()

    def test_invalid_yaml_rules_not_a_list(self):
        """AC6: Invalid YAML detected - 'rules' not a list."""
        parser = RuleParser()
        invalid_yaml = {
            "name": "Test",
            "rules": "not_a_list"
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(invalid_yaml)

        assert "list" in str(exc_info.value).lower()

    def test_invalid_yaml_rule_not_a_dict(self):
        """AC6: Invalid YAML detected - rule is not a dictionary."""
        parser = RuleParser()
        invalid_yaml = {
            "name": "Test",
            "rules": ["not_a_dict"]
        }

        with pytest.raises(RuleParseError) as exc_info:
            parser.parse_rules(invalid_yaml)

        assert "dictionary" in str(exc_info.value).lower()


class TestInformationalRulesNeverBlock:
    """Tests ensuring informational rules (profit_target, min_trading_days) NEVER block (AC5)."""

    @pytest.fixture
    def ftmo_engine(self):
        """Create RuleEngine with FTMO rules."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")
        return RuleEngine(account_id="test-ftmo-001", rules=rules)

    def test_profit_target_met_doesnt_block(self, ftmo_engine):
        """Profit target met should WARN but not BLOCK."""
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 15.0,  # 15% profit (above 10% target)
            "trading_days_count": 2,
        }

        result = ftmo_engine.validate(context)

        # Should be allowed (profit target doesn't block)
        assert result.is_allowed
        assert not result.is_blocked

    def test_min_trading_days_met_doesnt_block(self, ftmo_engine):
        """Min trading days met should WARN but not BLOCK."""
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 3.0,
            "trading_days_count": 10,  # 10 days (above 4 requirement)
        }

        result = ftmo_engine.validate(context)

        # Should be allowed (min trading days doesn't block)
        assert result.is_allowed
        assert not result.is_blocked

    def test_both_informational_targets_met_doesnt_block(self, ftmo_engine):
        """Both informational targets met should WARN but not BLOCK."""
        context = {
            "daily_pnl_percent": 0.0,
            "total_drawdown_percent": 0.0,
            "requested_lots": 1.0,
            "current_position_lots": 0.0,
            "account_balance": 100000.0,
            "total_pnl_percent": 12.0,  # 12% profit
            "trading_days_count": 5,  # 5 days
        }

        result = ftmo_engine.validate(context)

        # Should be allowed (informational rules don't block)
        assert result.is_allowed
        assert not result.is_blocked


class TestRuleEngineFactoryWithFTMO:
    """Tests for RuleEngineFactory creating FTMO-configured engines."""

    def test_factory_creates_engine_with_ftmo_preset(self):
        """Factory should create engine with FTMO rules loaded from preset."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")

        factory = RuleEngineFactory()
        engine = factory.create_for_account(
            account_id="ftmo-account-001",
            rules=rules,
        )

        assert engine is not None
        assert engine.rule_count == 5

    def test_factory_engine_has_correct_rule_types(self):
        """Factory-created engine should have correct FTMO rule types."""
        loader = RulePresetLoader()
        loader.clear_cache()
        rules = loader.load_preset("ftmo")

        factory = RuleEngineFactory()
        engine = factory.create_for_account(
            account_id="ftmo-account-001",
            rules=rules,
        )

        rule_types = {r.rule_type for r in engine.get_rules()}
        expected = {
            "daily_loss_limit",
            "max_drawdown",
            "max_position_size",
            "profit_target",
            "min_trading_days",
        }

        assert rule_types == expected
