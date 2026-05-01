"""Per-symbol spread-aware fee model for backtest cost parity.

Story 10.9 (D8) — :class:`PerContractFeeModel` (wired in Epic 9 P0.13)
charges a flat per-lot commission. Live fills also pay the bid/ask
spread; a backtest that ignores it overstates PnL on every entry +
exit. ForexFactory and broker docs publish typical spreads in pips
per symbol; the firm registry stores them as
:attr:`CommissionProfile.spread_pips`.

This module bridges the per-symbol mapping into Nautilus's
:class:`FeeModel` API by computing

    spread_cost_usd = spread_pips × pip_value_per_lot_usd × fill_qty

on every fill, on top of the existing per-lot commission. Both legs
of a round-trip pay the spread once (Nautilus calls
``get_commission`` per fill, so an entry + exit each incur the cost,
matching how live brokers settle).

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
from typing import Mapping

from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.objects import Money

logger = logging.getLogger(__name__)


# Forex majors in standard lots: 1 pip = $10. Exotic / metals have
# different math (XAUUSD = $1/pip/lot for the canonical pip definition
# of 0.01, BTCUSD = $1/point/contract, …) so callers can override per
# symbol. The default is the conservative-typical value used by the
# strategies in src/strategies/bracket_strategy.py:50.
DEFAULT_PIP_VALUE_PER_LOT_USD: float = 10.0


class SpreadAwareFeeModel(FeeModel):
    """Combined per-lot commission + per-symbol spread cost.

    Args:
        per_lot_usd: Flat commission charged per lot per fill. Matches
            the existing :class:`PerContractFeeModel` semantics.
        spread_pips: Mapping of trading symbol → spread (in pips). Each
            fill incurs ``spread × pip_value × fill_qty`` in USD on top
            of commission. Symbols absent from the mapping pay
            commission only.
        pip_value_per_lot_usd: USD value of one pip × one lot. Either a
            scalar (applied to every symbol) or a per-symbol mapping
            so XAUUSD (~$1/pip/lot) and EURUSD ($10/pip/lot) cohabit.
            Symbols absent from the mapping fall through to
            :data:`DEFAULT_PIP_VALUE_PER_LOT_USD`.

    Notes:
        Subclasses Nautilus's Cython :class:`FeeModel`. Only
        :meth:`get_commission` is overridden — Nautilus invokes it on
        every fill.
    """

    def __init__(
        self,
        *,
        per_lot_usd: float = 0.0,
        spread_pips: Mapping[str, float] | None = None,
        pip_value_per_lot_usd: float | Mapping[str, float] = DEFAULT_PIP_VALUE_PER_LOT_USD,
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

        # Pip-value normalisation.
        clean_pip_value: dict[str, float] | float
        if isinstance(pip_value_per_lot_usd, Mapping):
            clean_pip_value = {}
            for symbol, value in pip_value_per_lot_usd.items():
                if value <= 0:
                    raise ValueError(
                        f"pip_value_per_lot_usd[{symbol!r}] must be positive, "
                        f"got {value}"
                    )
                clean_pip_value[symbol.strip().upper()] = float(value)
        else:
            if pip_value_per_lot_usd <= 0:
                raise ValueError(
                    f"pip_value_per_lot_usd must be positive, "
                    f"got {pip_value_per_lot_usd}"
                )
            clean_pip_value = float(pip_value_per_lot_usd)

        self._per_lot_usd: float = float(per_lot_usd)
        self._spread_pips: dict[str, float] = clean_spread
        self._pip_value: dict[str, float] | float = clean_pip_value

    # ----- Public test seams -------------------------------------------

    @property
    def per_lot_usd(self) -> float:
        return self._per_lot_usd

    @property
    def spread_pips(self) -> dict[str, float]:
        return dict(self._spread_pips)

    @property
    def pip_value(self) -> dict[str, float] | float:
        if isinstance(self._pip_value, dict):
            return dict(self._pip_value)
        return self._pip_value

    def cost_per_lot_for(self, symbol: str) -> float:
        """USD cost charged per lot for ``symbol`` (commission + spread).

        Useful for diagnostics — the same value :meth:`get_commission`
        scales by ``fill_qty``.
        """
        return self._per_lot_usd + self._spread_cost_per_lot(symbol)

    # ----- Nautilus FeeModel surface -----------------------------------

    def get_commission(self, order, fill_qty, fill_px, instrument):  # noqa: ANN001 — Cython types
        """Compute the per-fill USD cost = commission + spread.

        Nautilus calls this on every fill; an entry and an exit each
        invoke once, so a round trip pays the spread twice — matching
        how live brokers settle.
        """
        symbol = self._extract_symbol(instrument)
        qty_lots = float(fill_qty)
        per_lot_total = self._per_lot_usd + self._spread_cost_per_lot(symbol)
        total_usd = per_lot_total * qty_lots
        return Money(total_usd, USD)

    # ----- Internals ---------------------------------------------------

    @staticmethod
    def _extract_symbol(instrument) -> str:  # noqa: ANN001 — Cython types
        """Best-effort symbol extraction from a Nautilus ``Instrument``."""
        symbol = getattr(getattr(instrument, "id", None), "symbol", None)
        if symbol is None:
            return ""
        return str(symbol).strip().upper()

    def _spread_cost_per_lot(self, symbol: str) -> float:
        spread = self._spread_pips.get(symbol)
        if not spread:
            return 0.0
        if isinstance(self._pip_value, dict):
            pip_value = self._pip_value.get(
                symbol, DEFAULT_PIP_VALUE_PER_LOT_USD
            )
        else:
            pip_value = self._pip_value
        return spread * pip_value


__all__ = ["DEFAULT_PIP_VALUE_PER_LOT_USD", "SpreadAwareFeeModel"]
