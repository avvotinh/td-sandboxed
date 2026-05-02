"""Position-sizing protocol for strategies.

This module defines the runtime-checkable Protocol that all position sizers
must satisfy. Strategies depend on the protocol — not the concrete class —
so a fixed-lot sizer (legacy) and a risk-based sizer can be swapped freely.

The protocol method ``calculate_lot_size`` accepts price-distance inputs
(entry/stop) plus instrument pip metadata, returning a ``Decimal`` lot
size. This is the price-distance equivalent of the legacy pip-distance API.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class PositionSizerProtocol(Protocol):
    """Common interface for risk-aware position sizers.

    Implementations compute a lot size from account state, entry/stop prices,
    and instrument pip metadata. The result must respect any internal min/max
    and step constraints.
    """

    def calculate_lot_size(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
        pip_value_per_lot: Decimal,
        pip_size: Decimal,
    ) -> Decimal:
        """Return lot size respecting risk policy and instrument constraints."""
        ...
