"""Integration tests for DailyLossLimitRule (Story 4.2).

Tests cover:
- RuleEngine with DailyLossLimitRule validates signals correctly
- RuleEngine short-circuits on BLOCK from DailyLossLimitRule
- Warning aggregation works with DailyLossLimitRule warnings
- Loading from ftmo.yaml preset creates correct DailyLossLimitRule instance
- Multiple accounts with different thresholds (FTMO 5%, The5ers 5%, custom 3%)
"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config
from src.config.firm_registry import FirmRegistry
from src.rules.assignment_service import RuleAssignmentService
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.context_builder import RuleContextBuilder
from src.rules.engine import RuleEngine
from src.rules.parser import RuleParser
import yaml as _yaml


# Story 10.13 — drop-in for the deleted RulePresetLoader. See
# test_order_validation_flow.py for design rationale.
_PRESETS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "backtesting" / "presets"
)


def _load_preset_rules(name: str) -> list:
    yaml_path = _PRESETS_DIR / f"{name.lower()}.yaml"
    data = _yaml.safe_load(yaml_path.read_text())
    return RuleParser().parse_rules({"rules": data["rules"]})
from src.rules.types.drawdown import DailyLossLimitRule


# Story 10.12 — see test_rule_assignment_flow.py for rationale.
_FIRMS_DIR = Path(__file__).resolve().parents[4] / "configs" / "firms"


def _service_with_firm_registry(**kwargs) -> RuleAssignmentService:
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
    """Story 10.12 — firm-bound replaces the dropped ``prop_firm`` preset."""
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


class MockRule:
    """Mock rule for testing with DailyLossLimitRule."""

    def __init__(
        self,
        rule_type: str = "mock_rule",
        name: str = "Mock Rule",
        priority: int = 50,
        action: RuleAction = RuleAction.ALLOW,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority
        self._action = action

    def validate(self, context: dict) -> RuleResult:
        return RuleResult(action=self._action)

    def get_current_value(self, context: dict) -> float:
        return 0.0

    def get_threshold(self) -> float:
        return 100.0

    def get_warning_thresholds(self) -> list[float]:
        return [70.0, 80.0, 90.0]


class MockSignal:
    """Mock signal for testing."""

    def __init__(self, symbol: str = "EURUSD", side: str = "buy", quantity: float = 1.0):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity


# =============================================================================
# RuleEngine Integration Tests
# =============================================================================


class TestRuleEngineWithDailyLossLimit:
    """Test RuleEngine with DailyLossLimitRule validates signals correctly."""

    def test_engine_allows_trade_below_threshold(self):
        """Test engine allows trade when daily loss below threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -2.0,  # 2% loss - below 5% threshold
        }

        result = engine.validate(context)

        assert result.is_allowed
        assert not result.is_blocked
        assert result.action == RuleAction.ALLOW

    def test_engine_warns_at_warning_threshold(self):
        """Test engine warns when approaching daily loss threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -3.5,  # 3.5% loss - 70% of 5%
        }

        result = engine.validate(context)

        assert result.is_allowed  # WARN still allows trading
        assert not result.is_blocked
        assert result.action == RuleAction.WARN
        assert result.has_warnings

    def test_engine_blocks_at_threshold(self):
        """Test engine blocks trade when daily loss at threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -5.0,  # 5% loss - at threshold
        }

        result = engine.validate(context)

        assert not result.is_allowed
        assert result.is_blocked
        assert result.action == RuleAction.BLOCK

    def test_engine_blocks_above_threshold(self):
        """Test engine blocks trade when daily loss exceeds threshold."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -6.5,  # 6.5% loss - above threshold
        }

        result = engine.validate(context)

        assert not result.is_allowed
        assert result.is_blocked
        assert result.action == RuleAction.BLOCK


class TestRuleEngineShortCircuit:
    """Test RuleEngine short-circuits on BLOCK from DailyLossLimitRule."""

    def test_short_circuit_stops_on_daily_loss_block(self):
        """Test short-circuit stops evaluation when DailyLossLimitRule blocks."""
        # DailyLossLimitRule has priority=1 (evaluated first)
        daily_loss_rule = DailyLossLimitRule(threshold_percent=5.0)
        mock_rule = MockRule(rule_type="should_not_run", priority=99)

        engine = RuleEngine("test-001", [daily_loss_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -5.0,  # BLOCK condition
        }

        result = engine.validate(context)

        # Should only have 1 result (short-circuited)
        # all_results is a list of (rule, result) tuples
        assert len(result.all_results) == 1
        assert result.is_blocked
        rule, rule_result = result.all_results[0]
        assert rule_result.metadata.get("rule_type") == "daily_loss_limit"

    def test_continues_evaluation_on_allow(self):
        """Test evaluation continues when DailyLossLimitRule allows."""
        daily_loss_rule = DailyLossLimitRule(threshold_percent=5.0)
        mock_rule = MockRule(rule_type="second_rule", priority=99)

        engine = RuleEngine("test-001", [daily_loss_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -2.0,  # ALLOW condition
        }

        result = engine.validate(context)

        # Should have 2 results (both rules evaluated)
        assert len(result.all_results) == 2
        assert result.is_allowed

    def test_continues_evaluation_on_warn(self):
        """Test evaluation continues when DailyLossLimitRule warns."""
        daily_loss_rule = DailyLossLimitRule(threshold_percent=5.0)
        mock_rule = MockRule(rule_type="second_rule", priority=99)

        engine = RuleEngine("test-001", [daily_loss_rule, mock_rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -3.5,  # WARN condition (70%)
        }

        result = engine.validate(context)

        # Should have 2 results (warnings don't short-circuit)
        assert len(result.all_results) == 2
        assert result.is_allowed
        assert result.has_warnings


class TestWarningAggregation:
    """Test warning aggregation works with DailyLossLimitRule warnings."""

    def test_single_warning_captured(self):
        """Test single warning from DailyLossLimitRule is captured."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -3.5,  # 70% warning
        }

        result = engine.validate(context)

        assert result.has_warnings
        assert len(result.warning_messages) == 1
        assert "70%" in result.warning_messages[0]

    def test_multiple_warnings_from_different_rules(self):
        """Test warnings from multiple rules are aggregated."""
        daily_loss_rule = DailyLossLimitRule(threshold_percent=5.0)
        warning_mock = MockRule(
            rule_type="warning_mock",
            priority=99,
            action=RuleAction.WARN,
        )

        engine = RuleEngine("test-001", [daily_loss_rule, warning_mock])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -3.5,  # 70% warning
        }

        result = engine.validate(context)

        assert result.has_warnings
        # Both rules should have warned
        # all_results is a list of (rule, result) tuples
        warn_count = sum(1 for _rule, rule_result in result.all_results if rule_result.action == RuleAction.WARN)
        assert warn_count == 2

    def test_warning_messages_content(self):
        """Test warning messages contain useful information."""
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = {
            "account_id": "test-001",
            "daily_pnl_percent": -4.0,  # 80% warning
        }

        result = engine.validate(context)

        assert result.has_warnings
        warning_msg = result.warning_messages[0]
        assert "80%" in warning_msg  # Usage percentage
        assert "5.0%" in warning_msg  # Threshold


class TestFTMOPresetLoading:
    """Test loading from ftmo.yaml preset creates correct DailyLossLimitRule."""

    def test_ftmo_preset_loads_daily_loss_rule(self):
        """Test FTMO preset loads DailyLossLimitRule correctly."""
        # Story 10.13: preset loader replaced
        rules = _load_preset_rules("ftmo")

        # Find daily_loss_limit rule
        daily_loss_rules = [r for r in rules if r.rule_type == "daily_loss_limit"]
        assert len(daily_loss_rules) == 1

        rule = daily_loss_rules[0]
        assert isinstance(rule, DailyLossLimitRule)

    def test_ftmo_preset_threshold_is_5_percent(self):
        """Test FTMO preset daily loss threshold is 5%."""
        # Story 10.13: preset loader replaced
        rules = _load_preset_rules("ftmo")

        daily_loss_rule = next(r for r in rules if r.rule_type == "daily_loss_limit")

        assert daily_loss_rule.get_threshold() == 5.0

    def test_ftmo_preset_timezone_is_cet(self):
        """Test FTMO preset uses CET timezone."""
        # Story 10.13: preset loader replaced
        rules = _load_preset_rules("ftmo")

        daily_loss_rule = next(r for r in rules if r.rule_type == "daily_loss_limit")

        assert daily_loss_rule.timezone == "CET"

    def test_ftmo_preset_warning_thresholds(self):
        """Test FTMO preset warning thresholds are [70, 80, 90]."""
        # Story 10.13: preset loader replaced
        rules = _load_preset_rules("ftmo")

        daily_loss_rule = next(r for r in rules if r.rule_type == "daily_loss_limit")

        assert daily_loss_rule.get_warning_thresholds() == [70.0, 80.0, 90.0]

    def test_ftmo_preset_validates_correctly(self):
        """Test FTMO preset rule validates correctly."""
        # Story 10.13: preset loader replaced
        rules = _load_preset_rules("ftmo")

        daily_loss_rule = next(r for r in rules if r.rule_type == "daily_loss_limit")

        # Test ALLOW
        result = daily_loss_rule.validate({"daily_pnl_percent": -2.0})
        assert result.action == RuleAction.ALLOW

        # Test WARN at 70%
        result = daily_loss_rule.validate({"daily_pnl_percent": -3.5})
        assert result.action == RuleAction.WARN

        # Test BLOCK at threshold
        result = daily_loss_rule.validate({"daily_pnl_percent": -5.0})
        assert result.action == RuleAction.BLOCK


class TestRuleParserWithDailyLossRule:
    """Test RuleParser correctly parses DailyLossLimitRule from YAML."""

    def test_parser_creates_daily_loss_rule(self):
        """Test parser creates DailyLossLimitRule from YAML dict."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "daily_loss_limit",
                    "threshold_percent": 5.0,
                    "timezone": "CET",
                    "warning_at": [70, 80, 90],
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)

        assert len(rules) == 1
        assert isinstance(rules[0], DailyLossLimitRule)
        assert rules[0].threshold_percent == 5.0
        assert rules[0].timezone == "CET"

    def test_parser_with_custom_threshold(self):
        """Test parser with custom threshold value."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "daily_loss_limit",
                    "threshold_percent": 3.0,
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        assert rules[0].threshold_percent == 3.0

    def test_parser_with_default_values(self):
        """Test parser uses default values when not specified."""
        parser = RuleParser()
        yaml_content = {
            "rules": [
                {
                    "type": "daily_loss_limit",
                }
            ]
        }

        rules = parser.parse_rules(yaml_content)
        rule = rules[0]

        assert rule.threshold_percent == 5.0  # Default
        assert rule.timezone == "UTC"  # Default
        assert rule.reset_time == "00:00"  # Default
        assert rule.warning_at == [70.0, 80.0, 90.0]  # Default


class TestMultipleAccountsWithDifferentThresholds:
    """Test multiple accounts with different thresholds."""

    def test_different_thresholds_per_account(self):
        """Test each account can have different daily loss thresholds."""
        # Create rules for different accounts
        ftmo_rule = DailyLossLimitRule(threshold_percent=5.0)
        custom_rule = DailyLossLimitRule(threshold_percent=3.0)

        # Create engines
        ftmo_engine = RuleEngine("ftmo-001", [ftmo_rule])
        custom_engine = RuleEngine("custom-001", [custom_rule])

        # Test FTMO at 4% loss - should WARN (80%)
        ftmo_context = {"account_id": "ftmo-001", "daily_pnl_percent": -4.0}
        ftmo_result = ftmo_engine.validate(ftmo_context)
        assert ftmo_result.action == RuleAction.WARN

        # Test Custom at 4% loss - should BLOCK (> 3%)
        custom_context = {"account_id": "custom-001", "daily_pnl_percent": -4.0}
        custom_result = custom_engine.validate(custom_context)
        assert custom_result.action == RuleAction.BLOCK

    def test_account_manager_assigns_correct_rules(self, mock_redis_manager):
        """Test AccountManager assigns correct rules to each account."""
        manager = AccountManager(mock_redis_manager)
        service = _service_with_firm_registry()
        manager.set_rule_assignment_service(service)

        # Create FTMO and The5ers accounts
        accounts = [
            _create_prop_firm_account("ftmo-001", firm_id="ftmo"),
            _create_prop_firm_account(
                "the5ers-001", firm_id="the5ers", product_id="bootstrap", phase="funded"
            ),
        ]
        config = AccountsConfig(accounts=accounts)
        manager.load_accounts(config)

        # Initialize rules for each account
        for acc in accounts:
            manager._initialize_account_rules(acc.id)

        # Get engines
        ftmo_engine = manager.get_rule_engine("ftmo-001")
        the5ers_engine = manager.get_rule_engine("the5ers-001")

        # Both should have daily_loss_limit rules
        ftmo_rules = ftmo_engine.get_rules()
        the5ers_rules = the5ers_engine.get_rules()

        assert any(r.rule_type == "daily_loss_limit" for r in ftmo_rules)
        assert any(r.rule_type == "daily_loss_limit" for r in the5ers_rules)


class TestContextBuilderWithDailyLossRule:
    """Test RuleContextBuilder creates valid context for DailyLossLimitRule."""

    def test_context_includes_daily_pnl_percent(self):
        """Test context includes daily_pnl_percent field."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test-001",
            signal=MockSignal(),
            account_state={
                "balance": 100000,
                "equity": 99500,
                "daily_pnl_percent": -2.5,
            },
        )

        assert "daily_pnl_percent" in context
        assert context["daily_pnl_percent"] == -2.5

    def test_context_works_with_daily_loss_rule(self):
        """Test context from builder works with DailyLossLimitRule."""
        builder = RuleContextBuilder()
        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("test-001", [rule])

        context = builder.build_validation_context(
            account_id="test-001",
            signal=MockSignal(),
            account_state={
                "balance": 100000,
                "equity": 97000,
                "daily_pnl_percent": -3.0,  # 3% loss
            },
        )

        result = engine.validate(context)

        # Should allow (3% < 5%)
        assert result.is_allowed


class TestDailyLossLimitPerformance:
    """Test DailyLossLimitRule performance meets requirements."""

    def test_validate_under_5ms(self):
        """Test validate() completes in under 5ms."""
        import time

        rule = DailyLossLimitRule(threshold_percent=5.0)
        context = {"daily_pnl_percent": -3.5}

        # Warm up
        rule.validate(context)

        # Measure
        iterations = 1000
        start = time.perf_counter()
        for _ in range(iterations):
            rule.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        avg_ms = elapsed_ms / iterations
        assert avg_ms < 5, f"Average validate() time {avg_ms:.3f}ms exceeds 5ms target"

    def test_engine_with_daily_loss_under_50ms(self):
        """Test engine with DailyLossLimitRule validates under 50ms (NFR2)."""
        import time

        rule = DailyLossLimitRule(threshold_percent=5.0)
        engine = RuleEngine("perf-test", [rule])
        context = {
            "account_id": "perf-test",
            "daily_pnl_percent": -3.5,
        }

        # Measure
        start = time.perf_counter()
        result = engine.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50, f"Validation took {elapsed_ms:.2f}ms, exceeds 50ms target"
        assert result.evaluation_time_ms < 50
