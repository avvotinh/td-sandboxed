"""Per-symbol lot-aware fee model for backtest cost parity.

Story 10.9 (D8) introduced spread-aware fees; the 2026-07 sizing fix
(redesign plan Track 1.4) made this model **lot-aware**: Nautilus hands
``get_commission`` the fill quantity in ENGINE UNITS (1 oz / 1 unit of
base currency — see :mod:`src.kernel.instruments.contract_specs`), while
commission and spread are quoted per MT5 lot. The model converts
``fill_qty / contract_size → lots`` before charging. Pre-fix code
multiplied per-lot cost by raw units, which is why FX fees "burned"
accounts and were zeroed as a workaround — that workaround is gone.

Per-fill cost:

    lots            = fill_qty / contract_size
    spread_per_lot  = spread_pips × pip_size × contract_size × quote→USD
    total_usd       = (per_lot_usd + spread_per_lot) × lots

The pip value per lot is DERIVED from the symbol's
:class:`~src.kernel.instruments.contract_specs.ContractSpec` (XAUUSD:
0.01 × 100 = $1/pip/lot; EURUSD: 0.0001 × 100 000 = $10/pip/lot;
USDJPY: 1000 JPY/pip/lot converted at the fill price) — the old
caller-supplied ``pip_value_per_lot_usd`` knob is gone for the same
reason the strategy configs lost ``pip_size``: static per-symbol
economics in config was the root cause of the sizing bug.

Both legs of a round-trip pay the spread once (Nautilus calls
``get_commission`` per fill, matching how live brokers settle).

Out of scope (deferred to a follow-up story):

- ``swap_long_pips`` / ``swap_short_pips`` overnight financing. Proper
  modelling needs a Nautilus ``SimulationModule`` that hooks into the
  venue's bar-by-bar tick to detect the rollover boundary (typically
  22:00 server time) and deduct from held positions. The
  :class:`CommissionProfile` already carries the data; wiring it
  through is its own iteration.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Mapping

from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

from src.kernel.instruments.contract_specs import get_contract_spec

logger = logging.getLogger(__name__)


class SpreadAwareFeeModel(FeeModel):
    """Combined per-lot commission + per-symbol spread cost.

    Args:
        per_lot_usd: Flat commission charged per MT5 lot per fill.
        spread_pips: Mapping of trading symbol → spread (in pips). Each
            fill incurs ``spread × pip_value_per_lot × lots`` in USD on
            top of commission; the pip value is derived from the
            symbol's :class:`ContractSpec`. Symbols absent from the
            mapping pay commission only.

    Notes:
        Subclasses Nautilus's Cython :class:`FeeModel`. Only
        :meth:`get_commission` is overridden — Nautilus invokes it on
        every fill. Fills for symbols without a registered
        :class:`ContractSpec` fail loudly (``ValueError``): charging a
        guessed fee on a mis-registered instrument is the same class of
        silent error as sizing with guessed contract economics.
    """

    def __init__(
        self,
        *,
        per_lot_usd: float = 0.0,
        spread_pips: Mapping[str, float] | None = None,
    ) -> None:
        super().__init__()
        if per_lot_usd < 0:
            raise ValueError(
                f"per_lot_usd must be non-negative, got {per_lot_usd}"
            )
        # Normalise spread mapping to uppercase keys + reject negatives.
        clean_spread: dict[str, float] = {}
        for symbol, pips in (spread_pips or {}).items():
            if pips < 0:
                raise ValueError(
                    f"spread_pips[{symbol!r}] must be non-negative, got {pips}"
                )
            if pips == 0:
                continue  # zero-spread entry adds nothing
            clean_spread[symbol.strip().upper()] = float(pips)

        self._per_lot_usd: float = float(per_lot_usd)
        self._spread_pips: dict[str, float] = clean_spread

    # ----- Public test seams -------------------------------------------

    @property
    def per_lot_usd(self) -> float:
        return self._per_lot_usd

    @property
    def spread_pips(self) -> dict[str, float]:
        return dict(self._spread_pips)

    def cost_per_lot_for(self, symbol: str, price: float | None = None) -> float:
        """USD cost charged per lot for ``symbol`` (commission + spread).

        Useful for diagnostics — the same value :meth:`get_commission`
        scales by the fill's lot count. ``price`` is required for
        symbols whose quote currency is not USD (the spread cost
        converts at that rate).
        """
        return self._per_lot_usd + self._spread_cost_per_lot(symbol, price)

    # ----- Nautilus FeeModel surface -----------------------------------

    def get_commission(self, order, fill_qty, fill_px, instrument) -> Money:  # noqa: ANN001 — Cython params
        """Compute the per-fill USD cost = (commission + spread) × lots.

        Nautilus calls this on every fill; an entry and an exit each
        invoke once, so a round trip pays the spread twice — matching
        how live brokers settle. The lot conversion and total are
        computed in ``Decimal``; floats only cross the boundary at the
        Nautilus ``Money`` constructor (which quantises to cents).
        """
        symbol = self._extract_symbol(instrument)
        spec = get_contract_spec(symbol)
        qty_lots = Decimal(str(float(fill_qty))) / spec.contract_size
        per_lot_total = Decimal(str(self._per_lot_usd)) + Decimal(
            str(self._spread_cost_per_lot(symbol, float(fill_px)))
        )
        return Money(per_lot_total * qty_lots, USD)

    # ----- Internals ---------------------------------------------------

    @staticmethod
    def _extract_symbol(instrument) -> str:  # noqa: ANN001 — Cython types
        """Best-effort symbol extraction from a Nautilus ``Instrument``."""
        symbol = getattr(getattr(instrument, "id", None), "symbol", None)
        if symbol is None:
            return ""
        return str(symbol).strip().upper()

    def _spread_cost_per_lot(self, symbol: str, price: float | None) -> float:
        """Spread cost in USD per lot: pips × pip-value-per-lot(USD).

        Symbols with no configured spread short-circuit to 0 and skip
        ContractSpec validation entirely — commission-only symbols are
        allowed; the loud unknown-symbol guard for every fill lives in
        :meth:`get_commission` instead.
        """
        spread = self._spread_pips.get(symbol.strip().upper())
        if not spread:
            return 0.0
        spec = get_contract_spec(symbol)
        pip_value_quote = float(spec.pip_size) * float(spec.contract_size)
        if spec.quote_currency == "USD":
            return spread * pip_value_quote
        if price is None:
            raise ValueError(
                f"{symbol}: fill price required to convert the "
                f"{spec.quote_currency}-denominated spread cost to USD"
            )
        rate = float(spec.quote_to_account_rate(Decimal(str(price))))
        return spread * pip_value_quote * rate


__all__ = ["SpreadAwareFeeModel"]
