"""Integration tests for RuleEngine flow (Story 4.1).

Tests cover:
- Full flow: AccountManager -> RuleEngine -> validation (11.1)
- Multiple accounts have independent rule engines (11.2)
- Rule engine with mixed FTMO preset rules (11.3)
- Validation performance: 10 rules < 50ms (11.4, NFR2)
"""

import time
from unittest.mock import AsyncMock

import pytest

from src.accounts.account_manager import AccountManager
from src.accounts.models import AccountConfig, AccountsConfig, AccountType, MT5Config
from src.rules.assignment_service import RuleAssignmentService
from src.rules.base_rule import RuleAction, RuleResult
from src.rules.context_builder import RuleContextBuilder
from src.rules.engine import RuleEngine
from src.rules.engine_factory import RuleEngineFactory


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


class MockRule:
    """Mock rule for performance testing."""

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
# Full Flow Integration Tests
# =============================================================================


class TestAccountManagerRuleEngineFlow:
    """Test full flow: AccountManager -> RuleEngine -> validation (11.1)."""

    def test_account_manager_creates_rule_engine(self, mock_redis_manager):
        """Test AccountManager creates RuleEngine for account with rules."""
        # Setup
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        # Load FTMO account
        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)

        # Initialize rules
        manager._initialize_account_rules("ftmo-001")

        # Verify RuleEngine was created
        engine = manager.get_rule_engine("ftmo-001")
        assert engine is not None
        assert isinstance(engine, RuleEngine)
        assert engine.account_id == "ftmo-001"

    def test_rule_engine_validates_context(self, mock_redis_manager):
        """Test RuleEngine validates context correctly."""
        # Setup
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)
        manager._initialize_account_rules("ftmo-001")

        engine = manager.get_rule_engine("ftmo-001")
        assert engine is not None

        # Build context
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="ftmo-001",
            signal=MockSignal(),
            account_state={
                "balance": 100000,
                "equity": 99500,
                "daily_pnl_percent": -1.0,  # -1% loss - within limits
                "total_drawdown_percent": 2.0,  # 2% drawdown - within limits
            },
        )

        # Validate
        result = engine.validate(context)

        # Should allow trade (values within limits)
        assert result.is_allowed
        assert len(result.all_results) > 0

    def test_demo_account_has_no_engine(self, mock_redis_manager):
        """Test demo accounts don't have a RuleEngine."""
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        account = _create_demo_account("demo-001")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)
        manager._initialize_account_rules("demo-001")

        engine = manager.get_rule_engine("demo-001")
        assert engine is None


class TestMultipleAccountRuleEngines:
    """Test multiple accounts have independent rule engines (11.2)."""

    def test_accounts_have_independent_engines(self, mock_redis_manager):
        """Test each account has its own independent RuleEngine."""
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        # Create multiple accounts
        accounts = [
            _create_prop_firm_account("ftmo-001", "ftmo"),
            _create_prop_firm_account("the5ers-001", "the5ers"),
        ]
        config = AccountsConfig(accounts=accounts)
        manager.load_accounts(config)

        # Initialize all
        for acc in accounts:
            manager._initialize_account_rules(acc.id)

        # Get engines
        engine_ftmo = manager.get_rule_engine("ftmo-001")
        engine_5ers = manager.get_rule_engine("the5ers-001")

        # Verify both exist and are independent
        assert engine_ftmo is not None
        assert engine_5ers is not None
        assert engine_ftmo is not engine_5ers
        assert engine_ftmo.account_id == "ftmo-001"
        assert engine_5ers.account_id == "the5ers-001"

    def test_validation_isolated_between_accounts(self, mock_redis_manager):
        """Test validation on one account doesn't affect another."""
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        accounts = [
            _create_prop_firm_account("ftmo-001", "ftmo"),
            _create_prop_firm_account("ftmo-002", "ftmo"),
        ]
        config = AccountsConfig(accounts=accounts)
        manager.load_accounts(config)

        for acc in accounts:
            manager._initialize_account_rules(acc.id)

        engine_1 = manager.get_rule_engine("ftmo-001")
        engine_2 = manager.get_rule_engine("ftmo-002")

        builder = RuleContextBuilder()

        # Create different contexts with different values
        context_1 = builder.build_validation_context(
            account_id="ftmo-001",
            signal=MockSignal(),
            account_state={
                "balance": 100000,
                "equity": 99500,
                "daily_pnl_percent": -1.0,
            },
        )

        context_2 = builder.build_validation_context(
            account_id="ftmo-002",
            signal=MockSignal(),
            account_state={
                "balance": 50000,
                "equity": 48000,
                "daily_pnl_percent": -2.5,
            },
        )

        # Validate both
        result_1 = engine_1.validate(context_1)
        result_2 = engine_2.validate(context_2)

        # Both should complete independently
        assert result_1 is not result_2
        assert len(result_1.all_results) > 0
        assert len(result_2.all_results) > 0


class TestRuleEngineMixedRules:
    """Test rule engine with mixed FTMO preset rules (11.3)."""

    def test_ftmo_preset_rules_load_correctly(self, mock_redis_manager):
        """Test FTMO preset rules are loaded into engine correctly."""
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)
        manager._initialize_account_rules("ftmo-001")

        engine = manager.get_rule_engine("ftmo-001")
        assert engine is not None

        # Get rules from engine
        rules = engine.get_rules()
        rule_types = [r.rule_type for r in rules]

        # FTMO should have at least these rule types
        assert "daily_loss_limit" in rule_types
        assert "max_drawdown" in rule_types

    def test_rules_sorted_by_priority(self, mock_redis_manager):
        """Test rules in engine are sorted by priority."""
        manager = AccountManager(mock_redis_manager)
        service = RuleAssignmentService()
        manager.set_rule_assignment_service(service)

        account = _create_prop_firm_account("ftmo-001", "ftmo")
        config = AccountsConfig(accounts=[account])
        manager.load_accounts(config)
        manager._initialize_account_rules("ftmo-001")

        engine = manager.get_rule_engine("ftmo-001")
        rules = engine.get_rules()

        # Verify sorted by priority (lower first)
        priorities = [getattr(r, "priority", 50) for r in rules]
        assert priorities == sorted(priorities)


class TestValidationPerformance:
    """Test validation performance: 10 rules < 50ms (11.4, NFR2).

    Note: This tests framework overhead only. Real rule performance
    will be tested in Stories 4.2-4.4.
    """

    def test_ten_rules_under_50ms(self):
        """Test 10 mock rules validate in under 50ms."""
        # Create 10 mock rules
        rules = [MockRule(rule_type=f"rule_{i}", priority=i) for i in range(10)]
        engine = RuleEngine("perf-test", rules)

        context = {
            "account_id": "perf-test",
            "current_balance": 100000,
            "current_equity": 99500,
        }

        # Measure validation time
        start = time.perf_counter()
        result = engine.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Assert performance target
        assert elapsed_ms < 50, f"Validation took {elapsed_ms:.2f}ms, exceeds 50ms target"
        assert result.evaluation_time_ms < 50

        # Verify all 10 rules evaluated
        assert len(result.all_results) == 10

    def test_twenty_rules_still_fast(self):
        """Test 20 mock rules validate in reasonable time."""
        rules = [MockRule(rule_type=f"rule_{i}", priority=i) for i in range(20)]
        engine = RuleEngine("perf-test-20", rules)

        context = {
            "account_id": "perf-test-20",
            "current_balance": 100000,
            "current_equity": 99500,
        }

        start = time.perf_counter()
        result = engine.validate(context)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should still be well under 100ms
        assert elapsed_ms < 100, f"Validation took {elapsed_ms:.2f}ms"
        assert len(result.all_results) == 20

    def test_short_circuit_improves_performance(self):
        """Test short-circuit on BLOCK improves performance."""
        # First 5 rules ALLOW, then BLOCK, then 4 more ALLOW
        rules = (
            [MockRule(rule_type=f"allow_{i}", priority=i, action=RuleAction.ALLOW) for i in range(5)]
            + [MockRule(rule_type="blocker", priority=5, action=RuleAction.BLOCK)]
            + [MockRule(rule_type=f"after_{i}", priority=6 + i, action=RuleAction.ALLOW) for i in range(4)]
        )
        engine = RuleEngine("short-circuit-test", rules)

        context = {"account_id": "test"}

        result = engine.validate(context)

        # Should only evaluate 6 rules (5 ALLOWs + 1 BLOCK)
        assert len(result.all_results) == 6
        assert result.is_blocked


class TestRuleEngineFactoryIntegration:
    """Test RuleEngineFactory creates engines correctly."""

    def test_factory_creates_working_engine(self):
        """Test factory creates a fully functional engine."""
        rules = [
            MockRule(rule_type="rule_1", priority=1),
            MockRule(rule_type="rule_2", priority=2),
        ]

        engine = RuleEngineFactory.create_for_account("test-001", rules)

        # Verify engine works
        result = engine.validate({"account_id": "test-001"})
        assert result.is_allowed
        assert len(result.all_results) == 2

    def test_factory_logs_creation(self, caplog):
        """Test factory logs engine creation."""
        import logging

        caplog.set_level(logging.INFO)

        rules = [MockRule()]
        RuleEngineFactory.create_for_account("logged-account", rules)

        # Verify log message
        assert any("logged-account" in record.message for record in caplog.records)
        assert any("1 rules" in record.message for record in caplog.records)


class TestContextBuilderIntegration:
    """Test RuleContextBuilder integration with RuleEngine."""

    def test_builder_creates_valid_context_for_engine(self):
        """Test context builder creates context that engine can validate."""
        rules = [MockRule()]
        engine = RuleEngine("integration-test", rules)
        builder = RuleContextBuilder()

        signal = MockSignal(symbol="GBPUSD", side="sell", quantity=0.5)
        account_state = {
            "balance": 100000,
            "equity": 99000,
            "daily_pnl_percent": -0.5,
            "total_drawdown_percent": 1.0,
        }

        context = builder.build_validation_context(
            account_id="integration-test",
            signal=signal,
            account_state=account_state,
        )

        # Verify context is valid
        assert builder.validate_context(context)

        # Verify engine can use it
        result = engine.validate(context)
        assert result is not None
        assert result.action in (RuleAction.ALLOW, RuleAction.WARN, RuleAction.BLOCK)

    def test_context_includes_all_needed_fields(self):
        """Test context includes all fields needed by rules."""
        builder = RuleContextBuilder()
        signal = MockSignal()
        account_state = {
            "balance": 100000,
            "equity": 99500,
            "initial_balance": 100000,
            "peak_balance": 100500,
            "daily_pnl": -500,
            "daily_pnl_percent": -0.5,
            "total_drawdown_percent": 0.5,
            "open_positions_count": 2,
            "total_exposure": 50000,
        }

        context = builder.build_validation_context(
            account_id="test-001",
            signal=signal,
            account_state=account_state,
        )

        # Verify all expected fields
        expected_fields = [
            "account_id",
            "timestamp",
            "signal",
            "symbol",
            "side",
            "quantity",
            "current_balance",
            "current_equity",
            "initial_balance",
            "peak_balance",
            "daily_pnl",
            "daily_pnl_percent",
            "total_drawdown_percent",
            "open_positions_count",
            "total_exposure",
        ]

        for field in expected_fields:
            assert field in context, f"Missing field: {field}"
