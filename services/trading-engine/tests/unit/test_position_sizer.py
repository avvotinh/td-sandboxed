"""Unit tests for PositionSizer."""

import pytest
from decimal import Decimal

from src.strategies.position_sizer import PositionSizer, PositionSizerConfig


class TestPositionSizerConfig:
    """Tests for PositionSizerConfig."""

    def test_default_values(self):
        """Config should have sensible defaults."""
        config = PositionSizerConfig()
        assert config.risk_percent == Decimal("1.0")
        assert config.max_lot_size == Decimal("10.0")
        assert config.min_lot_size == Decimal("0.01")
        assert config.fixed_lot_size is None

    def test_custom_values(self):
        """Config should accept custom values."""
        config = PositionSizerConfig(
            risk_percent=Decimal("2.5"),
            max_lot_size=Decimal("5.0"),
            min_lot_size=Decimal("0.1"),
            fixed_lot_size=Decimal("1.0"),
        )
        assert config.risk_percent == Decimal("2.5")
        assert config.max_lot_size == Decimal("5.0")
        assert config.min_lot_size == Decimal("0.1")
        assert config.fixed_lot_size == Decimal("1.0")

    def test_risk_percent_min_validation(self):
        """Risk percent should not be negative."""
        with pytest.raises(ValueError):
            PositionSizerConfig(risk_percent=Decimal("-1.0"))

    def test_risk_percent_max_validation(self):
        """Risk percent should not exceed 100."""
        with pytest.raises(ValueError):
            PositionSizerConfig(risk_percent=Decimal("101.0"))

    def test_lot_size_positive_validation(self):
        """Lot sizes should be positive."""
        with pytest.raises(ValueError):
            PositionSizerConfig(min_lot_size=Decimal("0"))
        with pytest.raises(ValueError):
            PositionSizerConfig(max_lot_size=Decimal("-1"))


class TestPositionSizerInit:
    """Tests for PositionSizer initialization."""

    def test_default_config(self):
        """Sizer should use default config if none provided."""
        sizer = PositionSizer()
        assert sizer.config.risk_percent == Decimal("1.0")

    def test_custom_config(self):
        """Sizer should use provided config."""
        config = PositionSizerConfig(risk_percent=Decimal("3.0"))
        sizer = PositionSizer(config)
        assert sizer.config.risk_percent == Decimal("3.0")


class TestFixedLotSize:
    """Tests for fixed lot sizing."""

    def test_fixed_lot_size_used(self):
        """calculate_size should return fixed size when configured."""
        config = PositionSizerConfig(fixed_lot_size=Decimal("0.5"))
        sizer = PositionSizer(config)

        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
        )

        assert result == Decimal("0.5")

    def test_get_fixed_size_returns_configured(self):
        """get_fixed_size should return configured fixed size."""
        config = PositionSizerConfig(fixed_lot_size=Decimal("1.5"))
        sizer = PositionSizer(config)

        assert sizer.get_fixed_size() == Decimal("1.5")

    def test_get_fixed_size_returns_min_when_not_configured(self):
        """get_fixed_size should return min when no fixed size configured."""
        config = PositionSizerConfig(min_lot_size=Decimal("0.05"))
        sizer = PositionSizer(config)

        assert sizer.get_fixed_size() == Decimal("0.05")

    def test_fixed_size_respects_max_constraint(self):
        """Fixed size should be capped at max."""
        config = PositionSizerConfig(
            fixed_lot_size=Decimal("15.0"),
            max_lot_size=Decimal("10.0"),
        )
        sizer = PositionSizer(config)

        assert sizer.get_fixed_size() == Decimal("10.0")


class TestRiskBasedSizing:
    """Tests for risk-based position sizing."""

    def test_standard_risk_calculation(self):
        """Should calculate correct lot size based on risk parameters."""
        config = PositionSizerConfig(risk_percent=Decimal("1.0"))
        sizer = PositionSizer(config)

        # 1% of $100,000 = $1000 risk
        # $1000 / (20 pips * $10/pip) = 5 lots
        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("10.0"),
        )

        assert result == Decimal("5.0")

    def test_higher_risk_percent(self):
        """Higher risk percent should result in larger position."""
        config = PositionSizerConfig(risk_percent=Decimal("2.0"))
        sizer = PositionSizer(config)

        # 2% of $100,000 = $2000 risk
        # $2000 / (20 pips * $10/pip) = 10 lots
        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("10.0"),
        )

        assert result == Decimal("10.0")

    def test_wider_stop_loss_reduces_size(self):
        """Wider stop loss should reduce position size."""
        config = PositionSizerConfig(risk_percent=Decimal("1.0"))
        sizer = PositionSizer(config)

        # 1% of $100,000 = $1000 risk
        # $1000 / (50 pips * $10/pip) = 2 lots
        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("50"),
            pip_value=Decimal("10.0"),
        )

        assert result == Decimal("2.0")

    def test_smaller_account_reduces_size(self):
        """Smaller account should result in smaller position."""
        config = PositionSizerConfig(risk_percent=Decimal("1.0"))
        sizer = PositionSizer(config)

        # 1% of $10,000 = $100 risk
        # $100 / (20 pips * $10/pip) = 0.5 lots
        result = sizer.calculate_size(
            account_balance=Decimal("10000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("10.0"),
        )

        assert result == Decimal("0.5")


class TestConstraints:
    """Tests for min/max lot size constraints."""

    def test_min_lot_size_enforced(self):
        """Result should not be below min lot size."""
        config = PositionSizerConfig(
            risk_percent=Decimal("0.1"),
            min_lot_size=Decimal("0.01"),
        )
        sizer = PositionSizer(config)

        # Very small risk on tiny account might calculate below min
        result = sizer.calculate_size(
            account_balance=Decimal("100"),
            stop_loss_pips=Decimal("100"),
            pip_value=Decimal("10.0"),
        )

        assert result >= Decimal("0.01")

    def test_max_lot_size_enforced(self):
        """Result should not exceed max lot size."""
        config = PositionSizerConfig(
            risk_percent=Decimal("10.0"),
            max_lot_size=Decimal("5.0"),
        )
        sizer = PositionSizer(config)

        # Large risk might calculate above max
        result = sizer.calculate_size(
            account_balance=Decimal("1000000"),
            stop_loss_pips=Decimal("10"),
            pip_value=Decimal("10.0"),
        )

        assert result <= Decimal("5.0")

    def test_result_rounded_to_two_decimals(self):
        """Result should be rounded to 2 decimal places."""
        config = PositionSizerConfig(risk_percent=Decimal("1.0"))
        sizer = PositionSizer(config)

        # This would normally calculate to many decimals
        result = sizer.calculate_size(
            account_balance=Decimal("10000"),
            stop_loss_pips=Decimal("33"),
            pip_value=Decimal("10.0"),
        )

        # Should be rounded
        assert result == round(result, 2)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_stop_loss_returns_min(self):
        """Zero stop loss should return minimum lot size."""
        sizer = PositionSizer()

        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("0"),
        )

        assert result == sizer.config.min_lot_size

    def test_negative_stop_loss_returns_min(self):
        """Negative stop loss should return minimum lot size."""
        sizer = PositionSizer()

        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("-10"),
        )

        assert result == sizer.config.min_lot_size

    def test_zero_pip_value_returns_min(self):
        """Zero pip value should return minimum lot size."""
        sizer = PositionSizer()

        result = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("0"),
        )

        assert result == sizer.config.min_lot_size


class TestGetLotSize:
    """Tests for get_lot_size convenience method."""

    def test_returns_fixed_size_when_configured(self):
        """Should return fixed size if configured."""
        config = PositionSizerConfig(fixed_lot_size=Decimal("0.5"))
        sizer = PositionSizer(config)

        result = sizer.get_lot_size(
            current_price=Decimal("2000.0"),
        )

        assert result == Decimal("0.5")

    def test_calculates_when_params_provided(self):
        """Should calculate when balance and stop loss provided."""
        sizer = PositionSizer()

        result = sizer.get_lot_size(
            current_price=Decimal("2000.0"),
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
        )

        assert result == Decimal("5.0")

    def test_returns_min_when_params_missing(self):
        """Should return min when required params missing."""
        sizer = PositionSizer()

        result = sizer.get_lot_size(
            current_price=Decimal("2000.0"),
        )

        assert result == sizer.config.min_lot_size
