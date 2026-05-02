"""Unit tests for ATRStopMixin."""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.model.enums import OrderSide

from src.strategies.mixins.atr_stop_mixin import ATRStopMixin


pytestmark = pytest.mark.unit


class TestCalculateAtrStop:
    """ATR-based stop-loss calculation."""

    def test_long_stop_below_entry(self) -> None:
        # entry 2400, ATR 10, multiplier 1.5 → SL = 2400 - 15 = 2385
        stop = ATRStopMixin.calculate_atr_stop(
            side=OrderSide.BUY,
            entry_price=Decimal("2400.00"),
            atr_value=Decimal("10.00"),
            multiplier=Decimal("1.5"),
        )
        assert stop == Decimal("2385.00")

    def test_short_stop_above_entry(self) -> None:
        # entry 2400, ATR 10, multiplier 1.5 → SL = 2400 + 15 = 2415
        stop = ATRStopMixin.calculate_atr_stop(
            side=OrderSide.SELL,
            entry_price=Decimal("2400.00"),
            atr_value=Decimal("10.00"),
            multiplier=Decimal("1.5"),
        )
        assert stop == Decimal("2415.00")

    def test_multiplier_2x(self) -> None:
        stop = ATRStopMixin.calculate_atr_stop(
            side=OrderSide.BUY,
            entry_price=Decimal("100.00"),
            atr_value=Decimal("5.00"),
            multiplier=Decimal("2.0"),
        )
        assert stop == Decimal("90.00")

    def test_zero_atr_raises(self) -> None:
        with pytest.raises(ValueError, match="atr_value"):
            ATRStopMixin.calculate_atr_stop(
                side=OrderSide.BUY,
                entry_price=Decimal("2400.00"),
                atr_value=Decimal("0"),
                multiplier=Decimal("1.5"),
            )

    def test_negative_atr_raises(self) -> None:
        with pytest.raises(ValueError, match="atr_value"):
            ATRStopMixin.calculate_atr_stop(
                side=OrderSide.BUY,
                entry_price=Decimal("2400.00"),
                atr_value=Decimal("-10"),
                multiplier=Decimal("1.5"),
            )

    def test_zero_multiplier_raises(self) -> None:
        with pytest.raises(ValueError, match="multiplier"):
            ATRStopMixin.calculate_atr_stop(
                side=OrderSide.BUY,
                entry_price=Decimal("2400.00"),
                atr_value=Decimal("10.00"),
                multiplier=Decimal("0"),
            )

    def test_invalid_side_raises(self) -> None:
        with pytest.raises(ValueError, match="side"):
            ATRStopMixin.calculate_atr_stop(
                side=OrderSide.NO_ORDER_SIDE,
                entry_price=Decimal("2400.00"),
                atr_value=Decimal("10.00"),
                multiplier=Decimal("1.5"),
            )

    def test_returns_decimal(self) -> None:
        stop = ATRStopMixin.calculate_atr_stop(
            side=OrderSide.BUY,
            entry_price=Decimal("2400.00"),
            atr_value=Decimal("10.00"),
            multiplier=Decimal("1.5"),
        )
        assert isinstance(stop, Decimal)


class TestCalculateAtrTakeProfit:
    """ATR-based take-profit calculation (reward side)."""

    def test_long_tp_above_entry(self) -> None:
        # entry 2400, ATR 10, multiplier 3.0 → TP = 2430
        tp = ATRStopMixin.calculate_atr_take_profit(
            side=OrderSide.BUY,
            entry_price=Decimal("2400.00"),
            atr_value=Decimal("10.00"),
            multiplier=Decimal("3.0"),
        )
        assert tp == Decimal("2430.00")

    def test_short_tp_below_entry(self) -> None:
        tp = ATRStopMixin.calculate_atr_take_profit(
            side=OrderSide.SELL,
            entry_price=Decimal("2400.00"),
            atr_value=Decimal("10.00"),
            multiplier=Decimal("3.0"),
        )
        assert tp == Decimal("2370.00")

    def test_reward_to_risk_2_to_1(self) -> None:
        # Symmetric 2R target
        entry = Decimal("100")
        atr = Decimal("1")
        sl = ATRStopMixin.calculate_atr_stop(
            OrderSide.BUY, entry, atr, Decimal("1.0")
        )
        tp = ATRStopMixin.calculate_atr_take_profit(
            OrderSide.BUY, entry, atr, Decimal("2.0")
        )
        risk = entry - sl
        reward = tp - entry
        assert reward == 2 * risk
