"""Tests for RuleContextBuilder class (Story 4.1).

Tests cover:
- RuleContextBuilder builds valid context
- Signal attribute extraction via duck typing
- Account state mapping
- Custom field support
- Context validation
"""

from datetime import datetime

import pytest

from src.rules.context_builder import RuleContextBuilder


class MockSignal:
    """Mock signal for testing."""

    def __init__(
        self,
        symbol: str = "EURUSD",
        side: str = "buy",
        quantity: float = 1.0,
    ):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity


class TestRuleContextBuilderBasic:
    """Tests for basic context building."""

    def test_build_context_returns_dict(self):
        """Test build_validation_context returns a dictionary."""
        builder = RuleContextBuilder()
        signal = MockSignal()
        account_state = {"balance": 100000, "equity": 99500}

        context = builder.build_validation_context(
            account_id="test-001",
            signal=signal,
            account_state=account_state,
        )

        assert isinstance(context, dict)

    def test_context_includes_account_id(self):
        """Test context includes account_id."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="my-account",
            signal=MockSignal(),
            account_state={},
        )

        assert context["account_id"] == "my-account"

    def test_context_includes_timestamp(self):
        """Test context includes timestamp."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert "timestamp" in context
        assert isinstance(context["timestamp"], datetime)


class TestRuleContextBuilderSignalExtraction:
    """Tests for signal attribute extraction via duck typing."""

    def test_extracts_symbol_from_signal(self):
        """Test symbol is extracted from signal object."""
        builder = RuleContextBuilder()
        signal = MockSignal(symbol="GBPUSD")
        context = builder.build_validation_context(
            account_id="test",
            signal=signal,
            account_state={},
        )

        assert context["symbol"] == "GBPUSD"

    def test_extracts_side_from_signal(self):
        """Test side is extracted from signal object."""
        builder = RuleContextBuilder()
        signal = MockSignal(side="sell")
        context = builder.build_validation_context(
            account_id="test",
            signal=signal,
            account_state={},
        )

        assert context["side"] == "sell"

    def test_extracts_quantity_from_signal(self):
        """Test quantity is extracted from signal object."""
        builder = RuleContextBuilder()
        signal = MockSignal(quantity=2.5)
        context = builder.build_validation_context(
            account_id="test",
            signal=signal,
            account_state={},
        )

        assert context["quantity"] == 2.5

    def test_signal_stored_in_context(self):
        """Test original signal object is stored in context."""
        builder = RuleContextBuilder()
        signal = MockSignal()
        context = builder.build_validation_context(
            account_id="test",
            signal=signal,
            account_state={},
        )

        assert context["signal"] is signal

    def test_fallback_to_account_state_for_symbol(self):
        """Test falls back to account_state when signal lacks attribute."""

        class PartialSignal:
            """Signal without symbol attribute."""

            side = "buy"
            quantity = 1.0

        builder = RuleContextBuilder()
        signal = PartialSignal()
        account_state = {"symbol": "USDJPY"}
        context = builder.build_validation_context(
            account_id="test",
            signal=signal,
            account_state=account_state,
        )

        assert context["symbol"] == "USDJPY"


class TestRuleContextBuilderAccountState:
    """Tests for account state mapping."""

    def test_maps_balance_to_current_balance(self):
        """Test balance is mapped to current_balance."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={"balance": 100000},
        )

        assert context["current_balance"] == 100000

    def test_maps_equity_to_current_equity(self):
        """Test equity is mapped to current_equity."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={"equity": 99500},
        )

        assert context["current_equity"] == 99500

    def test_includes_pnl_metrics(self):
        """Test P&L metrics are included."""
        builder = RuleContextBuilder()
        account_state = {
            "daily_pnl": -500,
            "daily_pnl_percent": -0.5,
            "total_drawdown_percent": 2.5,
        }
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state=account_state,
        )

        assert context["daily_pnl"] == -500
        assert context["daily_pnl_percent"] == -0.5
        assert context["total_drawdown_percent"] == 2.5

    def test_includes_position_info(self):
        """Test position info is included."""
        builder = RuleContextBuilder()
        account_state = {
            "open_positions_count": 3,
            "total_exposure": 150000,
        }
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state=account_state,
        )

        assert context["open_positions_count"] == 3
        assert context["total_exposure"] == 150000

    def test_includes_initial_and_peak_balance(self):
        """Test initial and peak balance are included."""
        builder = RuleContextBuilder()
        account_state = {
            "initial_balance": 100000,
            "peak_balance": 105000,
        }
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state=account_state,
        )

        assert context["initial_balance"] == 100000
        assert context["peak_balance"] == 105000

    def test_defaults_for_missing_values(self):
        """Test missing values have sensible defaults."""
        builder = RuleContextBuilder()
        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert context["current_balance"] == 0.0
        assert context["current_equity"] == 0.0
        assert context["daily_pnl"] == 0.0
        assert context["daily_pnl_percent"] == 0.0
        assert context["total_drawdown_percent"] == 0.0
        assert context["open_positions_count"] == 0
        assert context["total_exposure"] == 0.0


class TestRuleContextBuilderCustomFields:
    """Tests for custom field support."""

    def test_add_custom_field(self):
        """Test custom field can be added."""
        builder = RuleContextBuilder()
        builder.add_custom_field("custom_key", "custom_value")

        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert context["custom_key"] == "custom_value"

    def test_add_custom_field_returns_self(self):
        """Test add_custom_field returns self for chaining."""
        builder = RuleContextBuilder()
        result = builder.add_custom_field("key", "value")

        assert result is builder

    def test_chained_custom_fields(self):
        """Test multiple custom fields via chaining."""
        builder = RuleContextBuilder()
        builder.add_custom_field("field1", 1).add_custom_field("field2", 2)

        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert context["field1"] == 1
        assert context["field2"] == 2

    def test_clear_custom_fields(self):
        """Test clear_custom_fields removes all custom fields."""
        builder = RuleContextBuilder()
        builder.add_custom_field("field1", 1).add_custom_field("field2", 2)

        builder.clear_custom_fields()

        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert "field1" not in context
        assert "field2" not in context

    def test_clear_custom_fields_returns_self(self):
        """Test clear_custom_fields returns self for chaining."""
        builder = RuleContextBuilder()
        result = builder.clear_custom_fields()

        assert result is builder

    def test_custom_fields_persist_between_builds(self):
        """Test custom fields persist across multiple build calls."""
        builder = RuleContextBuilder()
        builder.add_custom_field("persistent", "value")

        # First build
        context1 = builder.build_validation_context(
            account_id="test1",
            signal=MockSignal(),
            account_state={},
        )

        # Second build without clearing
        context2 = builder.build_validation_context(
            account_id="test2",
            signal=MockSignal(),
            account_state={},
        )

        assert context1["persistent"] == "value"
        assert context2["persistent"] == "value"

    def test_clear_then_add_new_fields(self):
        """Test clearing and adding new fields works correctly."""
        builder = RuleContextBuilder()
        builder.add_custom_field("old_field", "old")
        builder.clear_custom_fields()
        builder.add_custom_field("new_field", "new")

        context = builder.build_validation_context(
            account_id="test",
            signal=MockSignal(),
            account_state={},
        )

        assert "old_field" not in context
        assert context["new_field"] == "new"


class TestRuleContextBuilderValidation:
    """Tests for context validation."""

    def test_validate_context_returns_true_for_valid(self):
        """Test validate_context returns True for valid context."""
        builder = RuleContextBuilder()
        context = {
            "account_id": "test",
            "current_balance": 100000,
            "current_equity": 99500,
        }

        result = builder.validate_context(context)

        assert result is True

    def test_validate_context_raises_for_missing_account_id(self):
        """Test validate_context raises ValueError for missing account_id."""
        builder = RuleContextBuilder()
        context = {
            "current_balance": 100000,
            "current_equity": 99500,
        }

        with pytest.raises(ValueError) as exc_info:
            builder.validate_context(context)

        assert "account_id" in str(exc_info.value)

    def test_validate_context_raises_for_missing_balance(self):
        """Test validate_context raises ValueError for missing current_balance."""
        builder = RuleContextBuilder()
        context = {
            "account_id": "test",
            "current_equity": 99500,
        }

        with pytest.raises(ValueError) as exc_info:
            builder.validate_context(context)

        assert "current_balance" in str(exc_info.value)

    def test_validate_context_raises_for_missing_equity(self):
        """Test validate_context raises ValueError for missing current_equity."""
        builder = RuleContextBuilder()
        context = {
            "account_id": "test",
            "current_balance": 100000,
        }

        with pytest.raises(ValueError) as exc_info:
            builder.validate_context(context)

        assert "current_equity" in str(exc_info.value)

    def test_validate_context_lists_all_missing(self):
        """Test validate_context lists all missing fields."""
        builder = RuleContextBuilder()
        context = {}

        with pytest.raises(ValueError) as exc_info:
            builder.validate_context(context)

        error_msg = str(exc_info.value)
        assert "account_id" in error_msg
        assert "current_balance" in error_msg
        assert "current_equity" in error_msg
