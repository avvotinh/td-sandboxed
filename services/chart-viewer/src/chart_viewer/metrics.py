"""Headline-metric fallbacks shared by the run list and the run payload.

When a result's ``metrics`` block is missing a value, both the run-list
summary (``results.summarize``) and the chart payload
(``payload._headline_metrics``) reconstruct it the same way. Keeping the
derivation here means the two consumers cannot drift apart.
"""

from __future__ import annotations

from typing import Any


def fallback_net_pnl(account: dict[str, Any], pnl_metrics: dict[str, Any]) -> float | None:
    """``metrics.pnl.net_pnl`` if present, else final − initial balance."""
    net_pnl = pnl_metrics.get("net_pnl")
    if net_pnl is not None:
        return net_pnl
    if account:
        try:
            return float(account["final_balance"]) - float(account["initial_balance"])
        except (KeyError, TypeError, ValueError):
            return None
    return None


def fallback_win_rate(
    trades: list[dict[str, Any]], trades_metrics: dict[str, Any]
) -> float | None:
    """``metrics.trades.win_rate`` if present, else wins/total over trades."""
    win_rate = trades_metrics.get("win_rate")
    if win_rate is not None:
        return win_rate
    if trades:
        wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
        return wins / len(trades)
    return None
