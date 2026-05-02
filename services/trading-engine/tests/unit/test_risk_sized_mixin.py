"""Unit tests for RiskSizedMixin."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.strategies.mixins.risk_sized_mixin import RiskSizedMixin
from src.strategies.risk_based_position_sizer import (
    RiskBasedPositionSizer,
    RiskBasedSizerConfig,
)


pytestmark = pytest.mark.unit


class _Host(RiskSizedMixin):
    """Bare host class for testing the mixin in isolation."""


class TestRiskSizedMixin:
    """Mixin must accept any PositionSizerProtocol implementation."""

    def test_set_and_use_sizer(self) -> None:
        host = _Host()
        sizer = RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0")))
        host.set_position_sizer(sizer)
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("1.00")

    def test_size_without_sizer_raises(self) -> None:
        host = _Host()
        with pytest.raises(RuntimeError, match="sizer"):
            host.size_from_risk(
                account_balance=Decimal("100000"),
                entry_price=Decimal("2400.00"),
                stop_price=Decimal("2390.00"),
                pip_value_per_lot=Decimal("1.0"),
                pip_size=Decimal("0.01"),
            )

    def test_swap_sizer(self) -> None:
        host = _Host()
        host.set_position_sizer(RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("1.0"))))
        host.set_position_sizer(RiskBasedPositionSizer(RiskBasedSizerConfig(risk_percent=Decimal("2.0"))))
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        # Now 2% risk
        assert result == Decimal("2.00")

    def test_accepts_duck_typed_sizer(self) -> None:
        """Any object with calculate_lot_size method satisfies the protocol."""

        class FakeSizer:
            def calculate_lot_size(
                self,
                *,
                account_balance: Decimal,
                entry_price: Decimal,
                stop_price: Decimal,
                pip_value_per_lot: Decimal,
                pip_size: Decimal,
            ) -> Decimal:
                return Decimal("0.42")

        host = _Host()
        host.set_position_sizer(FakeSizer())
        result = host.size_from_risk(
            account_balance=Decimal("100000"),
            entry_price=Decimal("2400.00"),
            stop_price=Decimal("2390.00"),
            pip_value_per_lot=Decimal("1.0"),
            pip_size=Decimal("0.01"),
        )
        assert result == Decimal("0.42")
