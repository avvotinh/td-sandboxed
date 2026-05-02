"""Risk-percent based position sizer.

Targets a fixed % of account equity per trade. Lot size is derived from
the price distance between entry and stop, scaled by pip value per lot.

Formula:
    risk_amount   = account_balance * (risk_percent / 100)
    stop_pips     = abs(entry_price - stop_price) / pip_size
    loss_per_lot  = stop_pips * pip_value_per_lot
    raw_lot_size  = risk_amount / loss_per_lot

The raw size is then floored to ``lot_step``. If the floored size is
**below** ``min_lot_size`` the method returns ``Decimal("0")`` to signal
"cannot size within risk budget" — callers must skip the trade rather
than silently upsize to ``min_lot_size`` and breach the FTMO risk target.
Above the minimum, the result is clamped to ``max_lot_size``.

Invalid inputs (non-positive balance, pip size, pip value, or stop
distance) likewise return ``Decimal("0")`` so strategies do not open
positions from malformed context.

Pip value contract:
    ``pip_value_per_lot`` MUST be denominated in the account currency.
    For non-account-currency-quoted instruments (e.g. EURJPY on a USD
    account), the caller is responsible for converting at the live rate
    before invoking this sizer.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, Field


class RiskBasedSizerConfig(BaseModel):
    """Configuration for ``RiskBasedPositionSizer``.

    Attributes:
        risk_percent: Risk per trade as % of account balance (0-100).
        max_lot_size: Hard ceiling on lot size.
        min_lot_size: Hard floor on lot size (returned for invalid inputs).
        lot_step: Quantisation step (e.g. 0.01 for most FX brokers).
    """

    risk_percent: Decimal = Field(default=Decimal("1.0"), ge=0, le=100)
    max_lot_size: Decimal = Field(default=Decimal("10.0"), gt=0)
    min_lot_size: Decimal = Field(default=Decimal("0.01"), gt=0)
    lot_step: Decimal = Field(default=Decimal("0.01"), gt=0)


class RiskBasedPositionSizer:
    """Position sizer that targets a fixed % risk per trade."""

    def __init__(self, config: RiskBasedSizerConfig | None = None) -> None:
        self.config = config or RiskBasedSizerConfig()

    def calculate_lot_size(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
        pip_value_per_lot: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Return lot size respecting risk_percent and lot constraints.

        Returns ``Decimal("0")`` when the trade cannot be sized within the
        risk budget (e.g. small account + wide stop) or when any input is
        malformed. Callers MUST treat ``0`` as "skip trade".
        """
        if (
            account_balance <= 0
            or pip_size <= 0
            or pip_value_per_lot <= 0
        ):
            return Decimal("0")

        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return Decimal("0")

        risk_amount = account_balance * (self.config.risk_percent / Decimal("100"))
        stop_pips = stop_distance / pip_size
        loss_per_lot = stop_pips * pip_value_per_lot
        raw_lot_size = risk_amount / loss_per_lot

        return self._clamp(raw_lot_size)

    def _clamp(self, lot_size: Decimal) -> Decimal:
        """Floor to lot_step, then enforce [min, max] with a zero-on-underflow.

        Below ``min_lot_size`` we return ``Decimal("0")`` instead of
        promoting to the minimum — promoting would silently inflate realised
        risk above the configured ``risk_percent`` target, breaching FTMO
        limits on small accounts with wide stops.
        """
        steps = (lot_size / self.config.lot_step).to_integral_value(rounding=ROUND_DOWN)
        floored = steps * self.config.lot_step

        if floored < self.config.min_lot_size:
            return Decimal("0")
        return min(floored, self.config.max_lot_size)
