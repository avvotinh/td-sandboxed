"""Pytest configuration and shared fixtures."""
import pytest


@pytest.fixture
def trading_engine():
    """Create a TradingEngine instance for testing.

    Returns:
        TradingEngine: A fresh engine instance for each test.
    """
    from src.engine import TradingEngine
    return TradingEngine()
