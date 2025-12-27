"""Unit tests for BaseStrategyConfig."""

import pytest
from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.data import BarType

from src.strategies.config import BaseStrategyConfig


class TestBaseStrategyConfig:
    """Tests for BaseStrategyConfig."""

    @pytest.fixture
    def instrument_id(self):
        """Create a test instrument ID."""
        return InstrumentId.from_str("XAUUSD.BROKER")

    @pytest.fixture
    def bar_type(self):
        """Create a test bar type."""
        return BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL")

    def test_create_config_with_required_fields(self, instrument_id, bar_type):
        """Should create config with required fields."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        assert config.instrument_id == instrument_id
        assert config.bar_type == bar_type

    def test_default_trade_size(self, instrument_id, bar_type):
        """Default trade size should be 0.1."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        assert config.trade_size == Decimal("0.1")

    def test_custom_trade_size(self, instrument_id, bar_type):
        """Should accept custom trade size."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
            trade_size=Decimal("0.5"),
        )
        assert config.trade_size == Decimal("0.5")

    def test_default_account_id_empty(self, instrument_id, bar_type):
        """Default account_id should be empty string."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        assert config.account_id == ""

    def test_custom_account_id(self, instrument_id, bar_type):
        """Should accept custom account_id."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
            account_id="ftmo-main",
        )
        assert config.account_id == "ftmo-main"

    def test_default_order_id_tag(self, instrument_id, bar_type):
        """Default order_id_tag should be '001'."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        assert config.order_id_tag == "001"

    def test_custom_order_id_tag(self, instrument_id, bar_type):
        """Should accept custom order_id_tag."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
            order_id_tag="strategy_001",
        )
        assert config.order_id_tag == "strategy_001"

    def test_config_is_frozen(self, instrument_id, bar_type):
        """Config should be immutable (frozen=True)."""
        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        # Attempting to modify should raise an error
        with pytest.raises(Exception):  # msgspec raises ValidationError
            config.trade_size = Decimal("1.0")

    def test_inherits_from_strategy_config(self, instrument_id, bar_type):
        """BaseStrategyConfig should inherit from NautilusTrader StrategyConfig."""
        from nautilus_trader.config import StrategyConfig

        config = BaseStrategyConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
        )
        assert isinstance(config, StrategyConfig)
