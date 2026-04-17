"""FTMO-specific drawdown, breach, and profit-target metrics.

All functions are pure: they take equity curves or scalar balances and
return floats / ints / bools. No I/O, no Nautilus dependencies — makes
them independently unit-testable.

Equity curve format: ``list[tuple[datetime, Decimal]]`` where the
datetime MUST be timezone-aware. The first entry is the initial balance.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby


_EquityCurve = Sequence[tuple[datetime, Decimal]]


def compute_max_overall_drawdown_pct(curve: _EquityCurve) -> float:
    """Largest peak-to-trough drawdown as % of the peak.

    Returns 0 for empty or single-point curves.
    """
    if len(curve) < 2:
        return 0.0
    peak = curve[0][1]
    max_dd_pct = Decimal("0")
    for _, equity in curve:
        if equity > peak:
            peak = equity
        elif peak > 0:
            dd = (peak - equity) / peak * 100
            if dd > max_dd_pct:
                max_dd_pct = dd
    return float(max_dd_pct)


def _group_by_day(curve: _EquityCurve) -> list[tuple[date, list[Decimal]]]:
    """Group equity points by local-UTC date. Preserves within-day order."""
    sorted_curve = sorted(curve, key=lambda p: p[0])
    grouped: list[tuple[date, list[Decimal]]] = []
    for day, points in groupby(sorted_curve, key=lambda p: p[0].date()):
        grouped.append((day, [equity for _, equity in points]))
    return grouped


def compute_daily_pnl_percentages(
    curve: _EquityCurve, *, initial_balance: Decimal
) -> list[float]:
    """Per-day P&L expressed as % of ``initial_balance`` (FTMO convention).

    Each day's PnL = close-of-day equity - open-of-day equity. Closed days
    only; a single-point curve returns an empty list.
    """
    if not curve or initial_balance <= 0:
        return []
    grouped = _group_by_day(curve)
    percentages: list[float] = []
    for _, points in grouped:
        if len(points) < 2:
            continue
        day_open = points[0]
        day_close = points[-1]
        pnl_pct = float((day_close - day_open) / initial_balance * 100)
        percentages.append(pnl_pct)
    return percentages


def compute_max_daily_drawdown_pct(
    curve: _EquityCurve, *, initial_balance: Decimal
) -> float:
    """Worst single-day loss as % of ``initial_balance`` (FTMO daily-loss metric).

    Returns the *absolute* value of the worst daily-loss %, e.g. a -5%
    daily return returns ``5.0``. Positive days are ignored.
    """
    daily_pcts = compute_daily_pnl_percentages(curve, initial_balance=initial_balance)
    losses = [-p for p in daily_pcts if p < 0]
    return max(losses, default=0.0)


def compute_profit_target_hit(
    *, initial_balance: Decimal, final_balance: Decimal, target_pct: float
) -> bool:
    """True if final_balance / initial_balance - 1 >= target_pct/100."""
    if initial_balance <= 0:
        return False
    gain_pct = (final_balance - initial_balance) / initial_balance * 100
    return float(gain_pct) >= target_pct


def compute_recovery_factor(
    *, net_pnl: Decimal, max_dd_abs: Decimal
) -> float:
    """net_pnl / max_dd_abs. Returns 0 when max_dd_abs is 0."""
    if max_dd_abs == 0:
        return 0.0
    return float(net_pnl / max_dd_abs)


def compute_trading_days_count(curve: _EquityCurve) -> int:
    """Number of unique UTC dates represented in the curve."""
    if not curve:
        return 0
    return len({ts.date() for ts, _ in curve})
