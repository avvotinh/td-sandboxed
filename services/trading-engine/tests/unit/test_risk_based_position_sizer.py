"""Unit tests for RiskBasedPositionSizer and PositionSizerProtocol."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.strategies.position_sizer import PositionSizer, PositionSizerConfig
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)
from src.strategies.sizing import PositionSizerProtocol


pytestmark = pytest.mark.unit


class TestRiskBasedSizerConfig:
    """Validation of RiskBasedSizerConfig."""

    def test_default_values(self) -> None:
        cfg = RiskBasedSizerConfig()
        assert cfg.risk_percent == Decimal("1.0")
        assert cfg.max_lot_size == Decimal("10.0")
        assert cfg.min_lot_size == Decimal("0.01")
        assert cfg.lot_step == Decimal("0.01")

    def test_risk_percent_must_be_in_range(self) -> None:
        with pytest.raises(ValueError):
            RiskBasedSizerConfig(risk_percent=Decimal("-0.1"))
        with pytest.raises(ValueError):
            RiskBasedSizerConfig(risk_percent=Decimal("100.1"))

    def test_lot_sizes_positive(self) -> None:
        with pytest.raises(ValueError):
            RiskBasedSizerConfig(max_lot_size=Decimal("0"))
        with pytest.raises(ValueError):
            RiskBasedSizerConfig(min_lot_size=Decimal("0"))
        with pytest.raises(ValueError):
            RiskBasedSizerConfig(lot_step=Decimal("0"))


class TestProtocolConformance:
    """Both sizers must satisfy PositionSizerProtocol."""

    def test_risk_based_sizer_satisfies_protocol(self) -> None:
        sizer = RiskBasedPositionSizer()
        assert isinstance(sizer, PositionSizerProtocol)

    def test_legacy_sizer_satisfies_protocol(self) -> None:
        # PositionSizer must adopt the new calculate_lot_size method too
        sizer = PositionSizer()
        assert isinstance(sizer, PositionSizerProtocol)


class TestCalculateLotSizeBasic:
    """Standard XAUUSD-style risk calculations."""

    def test_long_basic(self) -> None:
        # $100k account, 1% risk, entry 2400, stop 2390, pip_size 0.01
        # stop_distance = 10.00, pips = 10 / 0.01 = 1000 pips
        # risk = $1000, loss_per_lot = 1000 * $1 = $1000
        # lot_size = $1000 / $1000 = 1.0 lot
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("1.00")

    def test_short_basic(self) -> None:
        # Same calc, short side (stop above entry)
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2410.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("1.00")

    def test_higher_risk_pct_increases_size(self) -> None:
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("2.0")))
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("2.00")

    def test_wider_stop_reduces_size(self) -> None:
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2380.00"),  # 20 dollar stop
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0.50")

    def test_smaller_account_reduces_size(self) -> None:
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        result = sizer.calculate_lot_size(
            account_balance=Decimal("10000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0.10")


class TestCalculateLotSizeConstraints:
    """Min/max/step constraints."""

    def test_clamps_to_max_lot(self) -> None:
        sizer = RiskBasedPositionSizer(
            RiskBasedSizerConfig(risk_percent=Decimal("10"), max_lot_size=Decimal("5.0"))
        )
        # Would calculate 50 lots, must clamp to 5
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2399.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("5.0")

    def test_returns_zero_when_below_min_lot(self) -> None:
        """Insufficient-capital trades must be refused (return 0), not upsized.

        Promoting to min_lot would silently inflate realised risk above the
        configured target — an FTMO-fatal bug on small accounts with wide stops.
        """
        sizer = RiskBasedPositionSizer(
            RiskBasedSizerConfig(
                risk_percent=Decimal("0.01"),
                min_lot_size=Decimal("0.10"),
            )
        )
        result = sizer.calculate_lot_size(
            account_balance=Decimal("1000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2300.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0")

    def test_rounds_down_to_lot_step(self) -> None:
        sizer = RiskBasedPositionSizer(
            RiskBasedSizerConfig(
                risk_percent=Decimal("1.0"),
                lot_step=Decimal("0.01"),
            )
        )
        # 0.337 should round DOWN to 0.33 (never round up — risk would exceed target)
        result = sizer.calculate_lot_size(
            account_balance=Decimal("33700"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0.33")

    def test_lot_step_quarter(self) -> None:
        sizer = RiskBasedPositionSizer(
            RiskBasedSizerConfig(
                risk_percent=Decimal("1.0"),
                lot_step=Decimal("0.25"),
                min_lot_size=Decimal("0.25"),
            )
        )
        # ideal 1.0 → snaps to 1.0 (multiple of 0.25)
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("1.00")


class TestCalculateLotSizeEdgeCases:
    """Edge cases — must NOT crash and must return 0 to signal "skip trade"."""

    def test_zero_distance_returns_zero(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2400.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0")

    def test_zero_pip_value_returns_zero(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0")

    def test_zero_pip_size_returns_zero(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0"),
        )
        assert result == Decimal("0")

    def test_zero_balance_returns_zero(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("0"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0")

    def test_negative_balance_returns_zero(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("-1000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0")


class TestDecimalPrecision:
    """Must use Decimal end-to-end — no float drift."""

    def test_no_float_drift_on_repeating_decimal(self) -> None:
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        # 1/3 case — must stay deterministic Decimal
        result = sizer.calculate_lot_size(
            account_balance=Decimal("30000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        # 30000 * 0.01 / (1000 * 1) = 0.3
        assert result == Decimal("0.30")
        assert isinstance(result, Decimal)

    def test_returns_decimal_type(self) -> None:
        sizer = RiskBasedPositionSizer()
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert isinstance(result, Decimal)


class TestLegacyPositionSizerAdapter:
    """Legacy PositionSizer must implement calculate_lot_size for protocol."""

    def test_legacy_sizer_calculate_lot_size(self) -> None:
        sizer = PositionSizer(PositionSizerConfig(risk_percent=Decimal("1.0")))
        # Same scenario as RiskBased basic long
        result = sizer.calculate_lot_size(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("1.00")
