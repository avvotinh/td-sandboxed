"""Pure-function trade-level metrics for backtest results.

All functions take a list of trade P&Ls (winners positive, losers negative)
and return floats. Empty input is handled safely: every metric returns 0
except profit factor (0 when empty or all-loss, ``inf`` when all-win) and
sortino (``inf`` when no negative returns).

Decimal inputs are accepted and coerced to float at the seam.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Union

_Number = Union[float, Decimal]
_ANNUALISATION = 252  # typical trading days per year


def _as_float_list(values: Sequence[_Number]) -> list[float]:
    return [float(v) for v in values]


def compute_profit_factor(pnls: Sequence[_Number]) -> float:
    """Σ(wins) / |Σ(losses)|. Returns ``inf`` when no losses, 0 when empty/all-loss."""
    floats = _as_float_list(pnls)
    wins = sum(p for p in floats if p > 0)
    losses = sum(-p for p in floats if p < 0)
    if losses == 0:
        return math.inf if wins > 0 else 0.0
    return wins / losses


def compute_win_rate(pnls: Sequence[_Number]) -> float:
    """Fraction of trades with pnl > 0. Returns 0 on empty input."""
    floats = _as_float_list(pnls)
    if not floats:
        return 0.0
    wins = sum(1 for p in floats if p > 0)
    return wins / len(floats)


def compute_avg_win(pnls: Sequence[_Number]) -> float:
    floats = _as_float_list(pnls)
    winners = [p for p in floats if p > 0]
    if not winners:
        return 0.0
    return sum(winners) / len(winners)


def compute_avg_loss(pnls: Sequence[_Number]) -> float:
    """Returns the signed average loss (a negative number), or 0 if no losers."""
    floats = _as_float_list(pnls)
    losers = [p for p in floats if p < 0]
    if not losers:
        return 0.0
    return sum(losers) / len(losers)


def compute_expectancy(pnls: Sequence[_Number]) -> float:
    """win_rate * avg_win + loss_rate * avg_loss. Avg loss is signed-negative."""
    floats = _as_float_list(pnls)
    if not floats:
        return 0.0
    win_rate = compute_win_rate(floats)
    return win_rate * compute_avg_win(floats) + (1 - win_rate) * compute_avg_loss(floats)


def compute_max_consecutive_losses(pnls: Sequence[_Number]) -> int:
    """Longest consecutive run of trades with pnl < 0."""
    floats = _as_float_list(pnls)
    longest = 0
    current = 0
    for p in floats:
        if p < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std_dev(values: list[float], mean: float | None = None) -> float:
    if len(values) < 2:
        return 0.0
    m = mean if mean is not None else _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def compute_sharpe_ratio(
    returns: Sequence[_Number], risk_free_rate: float = 0.0
) -> float:
    """Annualised Sharpe — ``(mean - rf) / std * sqrt(252)``.

    Returns 0 for empty input, fewer than 2 samples, or zero std dev.
    Risk-free rate defaults to 0 (common for short-horizon strategy eval).
    """
    floats = _as_float_list(returns)
    if len(floats) < 2:
        return 0.0
    mean = _mean(floats)
    std = _std_dev(floats, mean)
    if std == 0:
        return 0.0
    return (mean - risk_free_rate) / std * math.sqrt(_ANNUALISATION)


def compute_sortino_ratio(
    returns: Sequence[_Number], risk_free_rate: float = 0.0
) -> float:
    """Annualised Sortino — ``(mean - rf) / downside_std * sqrt(252)``.

    Uses sample variance (``/ (N-1)``) for the downside deviation to match
    the convention used by :func:`compute_sharpe_ratio` — this keeps the
    two ratios directly comparable on the same return series.

    Returns ``inf`` when mean exceeds rf but no returns fall below rf
    (no downside deviation); returns 0 on empty input or when mean <= rf
    with no downside samples.
    """
    floats = _as_float_list(returns)
    if len(floats) < 2:
        return 0.0
    mean = _mean(floats)
    excess_mean = mean - risk_free_rate
    downside = [min(r - risk_free_rate, 0) for r in floats]
    sum_sq = sum(d * d for d in downside)
    if sum_sq == 0:
        return math.inf if excess_mean > 0 else 0.0
    downside_std = math.sqrt(sum_sq / (len(floats) - 1))
    return excess_mean / downside_std * math.sqrt(_ANNUALISATION)
