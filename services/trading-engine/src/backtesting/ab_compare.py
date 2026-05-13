"""A/B comparison of two ``BacktestResult`` runs (Story 13.9).

The validation report for Epic 13 (50/50 scale-out + Supertrend trail)
needs a one-shot comparison between a baseline strategy run and a
scale-out variant run on the same dataset. ``run_backtest`` already
emits :class:`PropFirmMetricsSchema` (EV, drawdown, win rate, Sharpe).
This module adds the missing piece: a winner-R distribution so the
report can quote the 95th-percentile winner R-multiple improvement that
Epic 13's quant review (§2.6) hinges on.

R-multiple convention here matches the existing schema convention in
``metrics.calculator``: per-trade R is ``pnl / |avg_loss|`` (a
recovery-per-avg-loss heuristic, not a true initial-risk R). True
initial-risk R requires per-trade SL distance which the current
``TradeRecord`` does not carry — documented as a follow-up if Phase 2
needs tighter R reporting. Each side uses its own ``avg_loss`` so the
distribution describes that side's own risk-adjusted wins, which is
the metric quoted by the quant review.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from src.backtesting.result import BacktestResult, TradeRecord


@dataclass(frozen=True)
class WinnerDistribution:
    """Percentile snapshot of a backtest's winning-trade R-multiples.

    ``count`` is the number of winning trades the distribution was built
    from. Percentile fields are ``0.0`` when ``count == 0`` so callers
    can still emit a JSON envelope without special-casing empty sides.
    """

    count: int
    avg_loss_abs: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    largest_winner_r: float


@dataclass(frozen=True)
class ABComparisonResult:
    """Side-by-side baseline vs variant comparison with deltas."""

    baseline: BacktestResult
    variant: BacktestResult
    baseline_winners: WinnerDistribution
    variant_winners: WinnerDistribution
    metric_deltas: dict[str, dict[str, float]]


def _avg_loss_abs(trades: list[TradeRecord]) -> float:
    losses = [abs(float(t.pnl)) for t in trades if float(t.pnl) < 0]
    if not losses:
        return 0.0
    return sum(losses) / len(losses)


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile; returns 0.0 if ``values`` is empty.

    Wraps :func:`statistics.quantiles` so the percentile semantics match
    NumPy's ``method='linear'`` default and the function is safe on
    single-element lists (returns the element itself).
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    # statistics.quantiles needs n>=2; method="inclusive" matches numpy linear.
    quantiles = statistics.quantiles(sorted_vals, n=100, method="inclusive")
    # quantiles produces 99 cut-points for indices 1..99.
    idx = max(1, min(99, int(round(pct * 100)))) - 1
    return float(quantiles[idx])


def compute_winner_distribution(trades: list[TradeRecord]) -> WinnerDistribution:
    """Build the winner-R-multiple distribution from a trade list.

    Each winning trade contributes ``pnl / |avg_loss|`` to the
    distribution. When the run has zero losing trades (``avg_loss == 0``)
    R is undefined, so every percentile is ``0.0`` and ``avg_loss_abs``
    is ``0.0`` — the caller is expected to treat this as "no comparable
    distribution" rather than a real zero.
    """
    avg_loss = _avg_loss_abs(trades)
    if avg_loss == 0.0:
        return WinnerDistribution(
            count=0,
            avg_loss_abs=0.0,
            p50=0.0,
            p75=0.0,
            p90=0.0,
            p95=0.0,
            p99=0.0,
            largest_winner_r=0.0,
        )

    winner_rs = [float(t.pnl) / avg_loss for t in trades if float(t.pnl) > 0]
    if not winner_rs:
        return WinnerDistribution(
            count=0,
            avg_loss_abs=avg_loss,
            p50=0.0,
            p75=0.0,
            p90=0.0,
            p95=0.0,
            p99=0.0,
            largest_winner_r=0.0,
        )

    return WinnerDistribution(
        count=len(winner_rs),
        avg_loss_abs=avg_loss,
        p50=_percentile(winner_rs, 0.50),
        p75=_percentile(winner_rs, 0.75),
        p90=_percentile(winner_rs, 0.90),
        p95=_percentile(winner_rs, 0.95),
        p99=_percentile(winner_rs, 0.99),
        largest_winner_r=max(winner_rs),
    )


def _scalar_metrics(result: BacktestResult) -> dict[str, float]:
    """Flatten the metric set into a name->float dict for delta computation.

    Sections beyond what we surface in the A/B view are intentionally
    omitted; the full ``BacktestResult`` is still carried in
    :class:`ABComparisonResult` for callers that need it.
    """
    if result.metrics is None:
        return {}
    m = result.metrics
    return {
        "total_trades": float(m.trades.total_trades),
        "win_rate": m.trades.win_rate,
        "expectancy": m.pnl.expectancy,
        "return_pct": m.pnl.return_pct,
        "avg_r_multiple": m.pnl.avg_r_multiple,
        "profit_factor": m.pnl.profit_factor,
        "max_overall_dd_pct": m.drawdown.max_overall_dd_pct,
        "sharpe_ratio": m.risk.sharpe_ratio,
        "sortino_ratio": m.risk.sortino_ratio,
        "calmar_ratio": m.risk.calmar_ratio,
        "max_consecutive_losses": float(m.risk.max_consecutive_losses),
    }


def _build_deltas(
    baseline: dict[str, float], variant: dict[str, float]
) -> dict[str, dict[str, float]]:
    """Compute ``{metric: {baseline, variant, delta, pct_change}}``.

    ``pct_change`` is left at ``0.0`` when the baseline value is ``0``
    to avoid division blow-ups; downstream renderers display "n/a"
    in that case based on the absolute delta.
    """
    out: dict[str, dict[str, float]] = {}
    for key in baseline.keys() | variant.keys():
        base_v = baseline.get(key, 0.0)
        var_v = variant.get(key, 0.0)
        delta = var_v - base_v
        pct = (delta / base_v * 100.0) if base_v != 0.0 else 0.0
        out[key] = {
            "baseline": base_v,
            "variant": var_v,
            "delta": delta,
            "pct_change": pct,
        }
    return out


def compare_ab(
    *, baseline: BacktestResult, variant: BacktestResult
) -> ABComparisonResult:
    """Produce a side-by-side comparison object from two backtest results."""
    return ABComparisonResult(
        baseline=baseline,
        variant=variant,
        baseline_winners=compute_winner_distribution(baseline.trades),
        variant_winners=compute_winner_distribution(variant.trades),
        metric_deltas=_build_deltas(
            _scalar_metrics(baseline), _scalar_metrics(variant)
        ),
    )


def winner_distribution_to_dict(dist: WinnerDistribution) -> dict[str, Any]:
    return {
        "count": dist.count,
        "avg_loss_abs": dist.avg_loss_abs,
        "p50": dist.p50,
        "p75": dist.p75,
        "p90": dist.p90,
        "p95": dist.p95,
        "p99": dist.p99,
        "largest_winner_r": dist.largest_winner_r,
    }
