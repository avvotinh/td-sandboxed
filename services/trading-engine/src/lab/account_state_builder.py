"""Build an AccountState dict for the Epic 4 rule engine.

The live path assembles this dict from Redis + ZMQ; in backtest, the
:class:`PropFirmComplianceActor` passes a snapshot extracted from Nautilus's
``Portfolio`` into :func:`build_account_state`, which augments it with
derived metrics (daily loss %, trailing drawdown %) needed by rules.

Keeping the snapshot dict at the seam (rather than accepting a
``Portfolio`` object directly) means the builder is trivially unit
testable without instantiating a ``BacktestEngine``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def build_account_state(
    *,
    portfolio_snapshot: dict[str, Any],
    initial_balance: Decimal,
    peak_balance: Decimal,
    daily_pnl: Decimal,
) -> dict[str, Any]:
    """Assemble a dict matching ``RuleContextBuilder.build_validation_context``.

    Args:
        portfolio_snapshot: Keys ``balance``, ``equity``, ``open_positions``,
            ``total_exposure`` extracted from Nautilus ``Portfolio``.
        initial_balance: Starting balance of the backtest.
        peak_balance: High-water mark reached so far (for trailing DD).
        daily_pnl: P&L since the current trading-day boundary (session tz).

    Returns:
        Dict ready to be passed into ``RuleEngine.validate`` as the signal
        context (missing only the ``signal`` / ``symbol`` / ``side`` keys,
        which are filled in by ``RuleContextBuilder`` at validation time).
    """
    balance = Decimal(str(portfolio_snapshot.get("balance", 0)))
    equity = Decimal(str(portfolio_snapshot.get("equity", 0)))

    if initial_balance > 0:
        daily_pnl_percent = float(daily_pnl / initial_balance * 100)
    else:
        daily_pnl_percent = 0.0

    if peak_balance > 0 and equity < peak_balance:
        total_drawdown_percent = float((peak_balance - equity) / peak_balance * 100)
    else:
        total_drawdown_percent = 0.0

    return {
        "balance": balance,
        "equity": equity,
        "initial_balance": initial_balance,
        "peak_balance": peak_balance,
        "daily_pnl": daily_pnl,
        "daily_pnl_percent": daily_pnl_percent,
        "total_drawdown_percent": total_drawdown_percent,
        "open_positions_count": portfolio_snapshot.get("open_positions", 0),
        "total_exposure": portfolio_snapshot.get("total_exposure", 0),
    }
