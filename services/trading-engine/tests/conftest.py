"""Pytest configuration and shared fixtures."""
import pytest

from src.rules.base_rule import RuleResult


@pytest.fixture
def trading_engine():
    """Create a TradingEngine instance for testing.

    Returns:
        TradingEngine: A fresh engine instance for each test.
    """
    from src.engine import TradingEngine
    return TradingEngine()


class FakeRule:
    """Minimal rule satisfying BaseRule protocol for testing."""

    def __init__(
        self,
        rule_type: str = "daily_loss_limit",
        name: str = "FTMO Daily Loss 5%",
        priority: int = 1,
    ):
        self.rule_type = rule_type
        self.name = name
        self.priority = priority

    def validate(self, context):
        return RuleResult()

    def get_current_value(self, context):
        return 0.0

    def get_threshold(self):
        return 5.0

    def get_warning_thresholds(self):
        return [70.0, 80.0, 90.0]


@pytest.fixture
def fake_rule():
    """Create a FakeRule instance for testing."""
    return FakeRule()
