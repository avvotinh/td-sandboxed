"""Mixin that delegates lot sizing to an injected ``PositionSizerProtocol``."""

from __future__ import annotations

from decimal import Decimal

from src.strategies.sizing import PositionSizerProtocol


class RiskSizedMixin:
    """Mixin providing risk-based position sizing via a swappable sizer.

    Strategies inheriting this mixin must call ``set_position_sizer`` before
    invoking ``size_from_risk``; otherwise a ``RuntimeError`` is raised. The
    mixin holds a single sizer reference and never mutates it.
    """

    _position_sizer: PositionSizerProtocol | None = None

    def set_position_sizer(self, sizer: PositionSizerProtocol) -> None:
        """Inject (or replace) the active position sizer."""
        self._position_sizer = sizer

    def size_from_risk(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
        pip_value_per_lot: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Compute lot size by delegating to the injected sizer."""
        if self._position_sizer is None:
            raise RuntimeError(
                "Position sizer not configured; call set_position_sizer() first"
            )
        return self._position_sizer.calculate_lot_size(
            account_balance=account_balance,
            entry_price=entry_price,
            stop_price=stop_price,
            pip_value_per_lot=pip_value_per_lot,
            pip_size=pip_size,
        )
