"""Mixin that delegates risk sizing to an injected ``PositionSizerProtocol``.

This module owns the lot→engine-unit conversion for the risk-sized
(bracket) path — the only conversion on that path; the dormant
fixed-``trade_size`` path converts in ``BaseStrategy.get_position_size``
with the same :class:`ContractSpec` discipline. The sizer speaks MT5
lots (that is what FTMO limits, lot_step and the MT5 bridge are
denominated in); Nautilus ``Quantity`` for our backtest instruments
means base-asset units (1 oz / 1 unit of base currency).
``size_from_risk`` sizes in lots, then converts to engine units via the
symbol's :class:`~src.kernel.instruments.contract_specs.ContractSpec` before
returning. Everything downstream of this mixin (bracket helpers,
``make_qty``, partial closes) is engine units — do not convert again.
"""

from __future__ import annotations

from decimal import Decimal

from src.kernel.instruments.contract_specs import ContractSpec, get_contract_spec
from src.kernel.strategies.sizing import PositionSizerProtocol


class RiskSizedMixin:
    """Mixin providing risk-based position sizing via a swappable sizer.

    Strategies inheriting this mixin must call ``set_position_sizer`` before
    invoking ``size_from_risk``; otherwise a ``RuntimeError`` is raised. The
    mixin holds a single sizer reference and never mutates it.

    Requires the host to provide ``self.config.instrument_id`` (any
    Nautilus ``StrategyConfig``) so the contract spec can be resolved
    from the traded symbol.
    """

    _position_sizer: PositionSizerProtocol | None = None
    _cached_contract_spec: ContractSpec | None = None

    def set_position_sizer(self, sizer: PositionSizerProtocol) -> None:
        """Inject (or replace) the active position sizer."""
        self._position_sizer = sizer

    def contract_spec(self) -> ContractSpec:
        """Contract spec for the traded symbol (resolved once, then cached).

        The cache assumes the Nautilus invariant of one immutable
        (frozen-config) instrument per strategy instance for its whole
        lifetime. The symbol is re-checked on every call so a violated
        assumption (config swap, multi-symbol reuse) fails loudly
        instead of silently sizing with stale contract economics.

        Raises ``ValueError`` for symbols without a registered spec —
        sizing must never proceed on guessed contract economics.
        """
        symbol = str(self.config.instrument_id.symbol)  # type: ignore[attr-defined]
        bare = symbol.split(".", 1)[0].upper()
        cached = self._cached_contract_spec
        if cached is not None:
            if cached.symbol != bare:
                raise RuntimeError(
                    f"Cached contract spec is for {cached.symbol!r} but the "
                    f"strategy config now trades {bare!r} — strategy instances "
                    "must not be reused across instruments"
                )
            return cached
        self._cached_contract_spec = get_contract_spec(symbol)
        return self._cached_contract_spec

    def size_from_risk(
        self,
        *,
        account_balance: Decimal,
        entry_price: Decimal,
        stop_price: Decimal,
    ) -> Decimal:
        """Return the position size in **engine units** for the risk budget.

        Delegates lot sizing to the injected sizer (which enforces the
        lot-step / min / max clamps in MT5-lot space), then converts
        lots → engine units. Returns ``Decimal("0")`` when the sizer
        signals "cannot size within risk budget" — callers must skip
        the trade.

        The account currency is USD by contract: the strategy stack
        reads balances via ``balance_total(USD)`` and every whitelisted
        symbol is USD-based or USD-quoted.
        """
        if self._position_sizer is None:
            raise RuntimeError(
                "Position sizer not configured; call set_position_sizer() first"
            )
        spec = self.contract_spec()
        lots = self._position_sizer.calculate_lot_size(
            account_balance=account_balance,
            entry_price=entry_price,
            stop_price=stop_price,
            contract_size=spec.contract_size,
            quote_to_account_rate=spec.quote_to_account_rate(entry_price),
        )
        return spec.lots_to_units(lots)
