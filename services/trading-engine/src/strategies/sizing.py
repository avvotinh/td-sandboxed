"""Position-sizing protocol for strategies.

This module defines the runtime-checkable Protocol that all position sizers
must satisfy. Strategies depend on the protocol — not the concrete class —
so a fixed-lot sizer (legacy) and a risk-based sizer can be swapped freely.

The protocol method ``calculate_lot_size`` accepts price-distance inputs
(entry/stop) plus the symbol's contract economics, returning a ``Decimal``
size in **MT5 lots**. Callers convert lots to engine units at the single
conversion point (``RiskSizedMixin.size_from_risk``) using the same
:class:`~src.instruments.contract_specs.ContractSpec` they sized with.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable


@runtime_checkable
class PositionSizerProtocol(Protocol):
    """Common interface for risk-aware position sizers.

    Implementations compute an MT5-lot size from account state, entry/stop
    prices, and contract economics. The result must respect any internal
    min/max and step constraints.
    """

    def calculate_lot_size(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
        contract_size: Decimal,
        quote_to_account_rate: Decimal,
    ) -> Decimal:
        """Return lot size respecting risk policy and instrument constraints.

        Args:
            account_balance: Account equity in the account currency.
            entry_price: Intended entry price.
            stop_price: Stop-loss price.
            contract_size: Base-asset units per 1.0 lot
                (``ContractSpec.contract_size``).
            quote_to_account_rate: Rate converting 1 quote-currency unit
                into the account currency
                (``ContractSpec.quote_to_account_rate``); 1 for
                USD-quoted symbols on a USD account.
        """
        ...
