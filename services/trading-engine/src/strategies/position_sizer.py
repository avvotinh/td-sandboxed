"""Position sizing for trading strategies.

This module provides position sizing calculations based on risk parameters.
Supports both fixed lot sizing (for prop firm accounts) and risk-based
dynamic sizing. Conforms to ``PositionSizerProtocol`` via the
``calculate_lot_size`` adapter.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, Field


class PositionSizerConfig(BaseModel):
    """Configuration for position sizing.

    Attributes:
        risk_percent: Risk per trade as % of balance (default 1%)
        max_lot_size: Maximum allowed lot size
        min_lot_size: Minimum allowed lot size
        fixed_lot_size: Fixed size (overrides risk calculation if set)
    """

    risk_percent: Decimal = Field(default=Decimal("1.0"), ge=0, le=100)
    max_lot_size: Decimal = Field(default=Decimal("10.0"), gt=0)
    min_lot_size: Decimal = Field(default=Decimal("0.01"), gt=0)
    fixed_lot_size: Decimal | None = None


class PositionSizer:
    """Calculates position sizes based on risk parameters.

    Supports:
    - Fixed lot sizing (for prop firm accounts)
    - Risk-based sizing (% of balance at risk)
    - Min/max lot size constraints

    Example:
        sizer = PositionSizer(PositionSizerConfig(risk_percent=Decimal("2.0")))
        lot_size = sizer.calculate_size(
            account_balance=Decimal("100000"),
            stop_loss_pips=Decimal("20"),
            pip_value=Decimal("10.0")
        )
    """

    def __init__(self, config: PositionSizerConfig | None = None):
        """Initialize position sizer.

        Args:
            config: Position sizer configuration. Uses defaults if not provided.
        """
        self.config = config or PositionSizerConfig()

    def calculate_size(
        self,
        account_balance: Decimal,
        stop_loss_pips: Decimal,
        pip_value: Decimal = Decimal("10.0"),
    ) -> Decimal:
        """Calculate lot size based on risk parameters.

        Uses fixed lot size if configured, otherwise calculates based on:
        - Account balance
        - Risk percentage
        - Stop loss distance in pips
        - Pip value per lot

        Formula: lot_size = (balance * risk%) / (stop_loss_pips * pip_value)

        Args:
            account_balance: Current account balance
            stop_loss_pips: Stop loss distance in pips
            pip_value: Value per pip per lot (default $10 for gold)

        Returns:
            Calculated lot size within min/max constraints
        """
        # Use fixed size if configured
        if self.config.fixed_lot_size is not None:
            return self._apply_constraints(self.config.fixed_lot_size)

        # Guard against invalid inputs
        if stop_loss_pips <= 0 or pip_value <= 0:
            return self.config.min_lot_size

        # Calculate risk amount
        risk_amount = account_balance * (self.config.risk_percent / Decimal("100"))

        # Calculate lot size: risk_amount / (stop_loss_pips * pip_value)
        lot_size = risk_amount / (stop_loss_pips * pip_value)
        return self._apply_constraints(lot_size)

    def get_fixed_size(self) -> Decimal:
        """Get fixed lot size for simple strategies.

        Returns the configured fixed lot size if set, otherwise
        returns the minimum lot size.

        Returns:
            Fixed lot size within constraints
        """
        if self.config.fixed_lot_size is not None:
            return self._apply_constraints(self.config.fixed_lot_size)
        return self.config.min_lot_size

    def get_lot_size(
        self,
        current_price: Decimal,
        account_balance: Decimal | None = None,
        stop_loss_pips: Decimal | None = None,
        pip_value: Decimal = Decimal("10.0"),
    ) -> Decimal:
        """Get lot size based on current conditions.

        Convenience method that either returns fixed size or calculates
        based on provided parameters.

        Args:
            current_price: Current market price (for reference)
            account_balance: Account balance (required for risk-based sizing)
            stop_loss_pips: Stop loss in pips (required for risk-based sizing)
            pip_value: Value per pip per lot

        Returns:
            Lot size within constraints
        """
        # If fixed size configured, use it
        if self.config.fixed_lot_size is not None:
            return self.get_fixed_size()

        # Otherwise calculate based on risk
        if account_balance is not None and stop_loss_pips is not None:
            return self.calculate_size(account_balance, stop_loss_pips, pip_value)

        # Fallback to minimum
        return self.config.min_lot_size

    def calculate_lot_size(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
        pip_value_per_lot: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Adapter for ``PositionSizerProtocol``.

        Converts price-distance inputs to pip distance, then delegates to the
        legacy ``calculate_size`` so existing fixed-lot / risk-percent logic is
        preserved unchanged.
        """
        if pip_size <= 0:
            return self.config.min_lot_size
        stop_loss_pips = abs(entry_price - stop_price) / pip_size
        return self.calculate_size(
            account_balance=account_balance,
            stop_loss_pips=stop_loss_pips,
            pip_value=pip_value_per_lot,
        )

    def _apply_constraints(self, lot_size: Decimal) -> Decimal:
        """Apply min/max constraints to lot size.

        Floors to 2 decimal places (never rounds up) so realised risk never
        exceeds the configured target — critical for FTMO compliance.

        Args:
            lot_size: Raw calculated lot size

        Returns:
            Lot size clamped to min/max and floored to 2 decimal places
        """
        lot_size = max(lot_size, self.config.min_lot_size)
        lot_size = min(lot_size, self.config.max_lot_size)
        return lot_size.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
