"""Per-symbol contract specifications — the lot ↔ unit source of truth.

Every venue-facing quantity in this codebase exists in one of two unit
systems:

* **MT5 lots** — what the risk sizer, FTMO presets, and (eventually) the
  MT5 bridge speak. 1 lot = ``contract_size`` units of the base asset
  (XAUUSD: 100 oz; FX majors: 100 000 units of base currency).
* **Engine units** — what Nautilus ``Quantity`` means for our backtest
  instruments (1 quantity = 1 oz / 1 unit of base currency).

Before 2026-07 the conversion between the two lived nowhere: sizer lots
were submitted as engine units, shrinking realised risk by the contract
size (the lot-vs-unit bug, ``docs/strategy-redesign-plan-2026-07-02.md``
§1). This module centralises the conversion constants; the ONLY
lot→unit conversion point in production code is
:meth:`src.strategies.mixins.risk_sized_mixin.RiskSizedMixin.size_from_risk`.

``pip_size`` is retained for fee/spread models and reporting. For every
whitelisted symbol it equals ``10 × price_increment`` of the matching
backtest instrument (cross-checked in ``tests/unit/test_contract_specs.py``).

Unknown symbols fail loudly (``ValueError``) — sizing with guessed
contract economics is exactly the class of silent error this module
exists to kill.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """Market conventions for one tradeable symbol.

    Attributes:
        symbol: Bare ticker (no venue suffix), e.g. ``"XAUUSD"``.
        contract_size: Base-asset units per 1.0 MT5 lot.
        pip_size: Price increment of one pip in quote-currency terms.
        base_currency: ISO/metal code of the base asset.
        quote_currency: ISO code prices are denominated in.
    """

    symbol: str
    contract_size: Decimal
    pip_size: Decimal
    base_currency: str
    quote_currency: str

    def lots_to_units(self, lots: Decimal) -> Decimal:
        """Convert MT5 lots to engine units (Nautilus ``Quantity`` scale)."""
        return lots * self.contract_size

    def units_to_lots(self, units: Decimal) -> Decimal:
        """Convert engine units back to MT5 lots (bridge / reporting)."""
        return units / self.contract_size

    def quote_to_account_rate(
        self, price: Decimal, account_currency: str = "USD"
    ) -> Decimal:
        """Rate converting 1 unit of quote currency into account currency.

        For USD-quoted symbols on a USD account this is 1. For
        USD-*based* symbols (USDJPY: quote JPY) the instrument's own
        price IS the account→quote rate, so the conversion is
        ``1 / price``. Cross pairs (neither side the account currency)
        would need an external rate feed — none are whitelisted, and we
        refuse to guess.
        """
        if price <= 0:
            raise ValueError(
                f"{self.symbol}: price must be positive to derive a "
                f"quote→{account_currency} rate, got {price}"
            )
        if self.quote_currency == account_currency:
            return Decimal("1")
        if self.base_currency == account_currency:
            return Decimal("1") / price
        raise ValueError(
            f"{self.symbol}: cannot convert {self.quote_currency} to "
            f"{account_currency} without an external rate (cross pair); "
            "wire a rate source before trading this symbol"
        )


def _fx_major(symbol: str, *, pip_size: str = "0.0001") -> ContractSpec:
    return ContractSpec(
        symbol=symbol,
        contract_size=Decimal("100000"),
        pip_size=Decimal(pip_size),
        base_currency=symbol[:3],
        quote_currency=symbol[-3:],
    )


_SPECS: MappingProxyType[str, ContractSpec] = MappingProxyType(
    {
        "XAUUSD": ContractSpec(
            symbol="XAUUSD",
            contract_size=Decimal("100"),
            pip_size=Decimal("0.01"),
            base_currency="XAU",
            quote_currency="USD",
        ),
        "EURUSD": _fx_major("EURUSD"),
        "GBPUSD": _fx_major("GBPUSD"),
        "AUDUSD": _fx_major("AUDUSD"),
        # JPY quotes to 3dp; pip is 0.01 (not 0.0001).
        "USDJPY": _fx_major("USDJPY", pip_size="0.01"),
    }
)


def get_contract_spec(symbol: str) -> ContractSpec:
    """Return the :class:`ContractSpec` for ``symbol`` or fail loudly.

    ``symbol`` is the bare ticker; venue-qualified ids
    (``XAUUSD.SIM``) are accepted and stripped for caller convenience.
    """
    bare = symbol.split(".", 1)[0].upper()
    try:
        return _SPECS[bare]
    except KeyError as exc:
        known = ", ".join(sorted(_SPECS))
        raise ValueError(
            f"No contract spec for symbol {symbol!r}. Known: {known}. "
            "Add it to src/instruments/contract_specs.py — do NOT size "
            "trades with guessed contract economics."
        ) from exc


def known_symbols() -> tuple[str, ...]:
    """Symbols with a registered contract spec (sorted)."""
    return tuple(sorted(_SPECS))
