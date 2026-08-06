"""Per-firm commission resolution for backtest cost parity (Epic 9 P0.13).

Live trading pays venue commission on every fill. Backtests that ignore
commission report inflated PnL and let strategies that look profitable
on paper fail the FTMO consistency check the moment they go live. This
module bridges the two: a :class:`FirmProfile`'s
:class:`CommissionProfile` becomes a Nautilus :class:`FeeModel` attached
to the simulated venue.

Two converters cover the two call patterns:

* :func:`commission_profile_to_fee_model` — for callers that already
  resolved a :class:`CommissionProfile` from the firm registry. Pair
  with :func:`resolve_commission_profile` to pick the effective profile.
* :func:`commission_per_lot_to_fee_model` — escape hatch for callers
  that only have a bare per-lot value (e.g. a non-firm-bound test or a
  ``VenueSpec`` populated outside the registry path).

Both return a :class:`SpreadAwareFeeModel` (redesign plan Track 1.4):
it converts the fill quantity from engine units to MT5 lots via the
symbol's :class:`~src.kernel.instruments.contract_specs.ContractSpec` before
charging, so per-lot commission means per LOT — not per unit. The
Nautilus :class:`PerContractFeeModel` used pre-2026-07 charged per
engine unit, which (once sizing was fixed) would multiply fees by the
contract size; it is no longer used.

Currency assumption: ``CommissionProfile.per_lot_usd`` is denominated
in USD as the field name implies. Both converters reject non-USD
``currency`` arguments — adding a non-USD prop firm is a deliberate
schema change, not a silent reinterpretation.

Resolution rules:

* ``product.commission_overrides`` wins over ``firm.commission`` when set
  — products inside a firm can have different cost structures (e.g.,
  premium accounts with tighter spreads).
* When neither side declares a profile, returns ``None`` and the
  backtest falls back to Nautilus defaults (= zero commission).
* Story 10.9 (D8): non-empty ``spread_pips`` additionally charges
  ``spread_pips × pip_value_per_lot × lots`` per fill, with the pip
  value derived from the :class:`ContractSpec`.
  ``swap_long_pips`` / ``swap_short_pips`` are still future work —
  proper modelling needs a Nautilus ``SimulationModule`` that hooks the
  rollover boundary; see :mod:`spread_fee_model` for the deferral note.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from nautilus_trader.model.currencies import USD

from src.config.firm_profile import CommissionProfile, FirmProfile
from .spread_fee_model import SpreadAwareFeeModel

if TYPE_CHECKING:
    from nautilus_trader.backtest.models import FeeModel
    from nautilus_trader.model.objects import Currency


def _require_usd(currency: Currency) -> None:
    """Reject non-USD currencies at the boundary.

    ``CommissionProfile.per_lot_usd`` is USD-denominated by name and by
    contract. Until the firm-profile schema gains an explicit
    currency_code, accepting another currency would silently
    reinterpret the value (e.g. 7 EUR/lot vs 7 USD/lot).
    """
    if currency != USD:
        raise ValueError(
            f"per_lot_usd is USD-denominated; got currency={currency.code!r}. "
            "Extend CommissionProfile with an explicit currency_code field "
            "before adding non-USD venues."
        )


def resolve_commission_profile(
    firm: FirmProfile,
    product_id: str,
) -> CommissionProfile | None:
    """Pick the effective :class:`CommissionProfile` for ``(firm, product)``.

    Product-level overrides take precedence; falls back to firm-level
    default; returns ``None`` when neither is declared.

    Raises:
        KeyError: If ``product_id`` is not a product of ``firm``.
    """
    product = firm.get_product(product_id)
    if product.commission_overrides is not None:
        return product.commission_overrides
    return firm.commission


def commission_profile_to_fee_model(
    profile: CommissionProfile | None,
    currency: Currency,
) -> FeeModel | None:
    """Convert a :class:`CommissionProfile` into a Nautilus :class:`FeeModel`.

    Returns ``None`` only when the profile is missing AND has no
    spread to apply. A profile with zero ``per_lot_usd`` but non-empty
    ``spread_pips`` still returns a working fee model — the spread
    cost on its own warrants a fee model.

    Raises:
        ValueError: If ``currency`` is not USD (see :func:`_require_usd`).
    """
    if profile is None:
        return None
    has_per_lot = profile.per_lot_usd > 0
    has_spread = bool(profile.spread_pips)
    if not has_per_lot and not has_spread:
        return None

    _require_usd(currency)

    return SpreadAwareFeeModel(
        per_lot_usd=profile.per_lot_usd,
        spread_pips=profile.spread_pips,
    )


def commission_per_lot_to_fee_model(
    per_lot_usd: Decimal | float,
    currency: Currency,
) -> FeeModel | None:
    """Build a fee model from a bare per-lot value (escape hatch for
    non-firm-bound backtests that just want commission parity without
    loading a :class:`FirmRegistry`).

    Unlike :func:`commission_profile_to_fee_model`, this entrypoint
    accepts unvalidated input so the negative-value guard *is* live —
    callers may pass arbitrary :class:`Decimal` or :class:`float`.

    Raises:
        ValueError: If ``per_lot_usd`` is negative, or ``currency`` is
            not USD.
    """
    amount = Decimal(str(per_lot_usd))
    if amount < 0:
        raise ValueError(f"per_lot_usd must be >= 0, got {amount}")
    if amount == 0:
        return None
    _require_usd(currency)
    return SpreadAwareFeeModel(per_lot_usd=float(amount))


__all__ = [
    "commission_per_lot_to_fee_model",
    "commission_profile_to_fee_model",
    "resolve_commission_profile",
]
