"""ATR-based stop-loss and take-profit calculation."""

from __future__ import annotations

from decimal import Decimal

from nautilus_trader.model.enums import OrderSide


class ATRStopMixin:
    """Mixin providing ATR-based SL/TP price math.

    Stateless — both methods are static. Inherit when a strategy needs
    ATR-derived stops and prefers them on ``self`` for ergonomic access.
    """

    @staticmethod
    def calculate_atr_stop(
        side: OrderSide,
        entry_price: Decimal,
        atr_value: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        """Return stop-loss price for a position.

        For LONG: stop is below entry (entry - atr * mult).
        For SHORT: stop is above entry (entry + atr * mult).
        """
        offset = ATRStopMixin._validated_offset(atr_value, multiplier)
        if side == OrderSide.BUY:
            return entry_price - offset
        if side == OrderSide.SELL:
            return entry_price + offset
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    @staticmethod
    def calculate_atr_take_profit(
        side: OrderSide,
        entry_price: Decimal,
        atr_value: Decimal,
        multiplier: Decimal,
    ) -> Decimal:
        """Return take-profit price for a position (mirror of stop)."""
        offset = ATRStopMixin._validated_offset(atr_value, multiplier)
        if side == OrderSide.BUY:
            return entry_price + offset
        if side == OrderSide.SELL:
            return entry_price - offset
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    @staticmethod
    def _validated_offset(atr_value: Decimal, multiplier: Decimal) -> Decimal:
        if atr_value <= 0:
            raise ValueError(f"atr_value must be positive, got {atr_value}")
        if multiplier <= 0:
            raise ValueError(f"multiplier must be positive, got {multiplier}")
        return atr_value * multiplier
