"""Shared portfolio balance / equity readers for backtest actors.

Single source of truth for how backtest actors read account state from
the Nautilus ``Portfolio`` — used by both ``EquityRecorderActor`` and
the venue branch of ``PropFirmComplianceActor._read_equity`` so the two
cannot drift:

* :func:`read_account_balance` — REALIZED balance
  (``account.balance_total``) with warm-up fallbacks. This is what the
  compliance actor evaluates rules on (unchanged semantics).
* :func:`read_unrealized_pnl` — sum of open positions' unrealized PnL
  in the account currency; best-effort, ``0`` on any failure. The
  equity recorder adds this on top of the balance so the recorded curve
  is true mark-to-market equity (intra-trade drawdown visible).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def read_account_balance(
    portfolio: Any,
    venue: Any,
    currency: Any,
    fallback: Decimal,
) -> Decimal:
    """Realized account balance for ``venue`` in ``currency``.

    Pre-fill warm-up (no account yet) and a missing ``balance_total``
    both fall back to ``fallback`` (the starting balance) so equity
    curves still populate from the first bar.
    """
    account = portfolio.account(venue)
    if account is None:
        return fallback
    balance = account.balance_total(currency)
    if balance is None:
        return fallback
    return Decimal(str(balance.as_double()))


def read_unrealized_pnl(portfolio: Any, venue: Any, currency: Any) -> Decimal:
    """Sum of open positions' unrealized PnL in ``currency`` for ``venue``.

    ``Portfolio.unrealized_pnls(venue)`` returns ``dict[Currency, Money]``
    (Nautilus 1.221). Missing currency entries mean no open exposure in
    that currency → ``0``. Any lookup/calculation failure degrades to
    ``0`` (balance-only equity) with a debug log — an equity read must
    never crash the bar stream.
    """
    try:
        pnls = portfolio.unrealized_pnls(venue)
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.debug(
            "unrealized_pnls(%s) failed; recording balance-only equity: %s",
            venue,
            exc,
        )
        return Decimal("0")
    money = pnls.get(currency) if pnls else None
    if money is None:
        return Decimal("0")
    return Decimal(str(money.as_double()))
