"""Top-level orchestrator: trade list + equity curve → ``FtmoMetricsSchema``.

Pure function, no I/O. Delegates all arithmetic to the focused helpers in
``trade_metrics`` and ``ftmo_metrics`` — keeps this layer a thin assembly
step that maps to the Pydantic envelope.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.backtesting.metrics.ftmo_metrics import (
    compute_max_daily_drawdown_pct,
    compute_max_overall_drawdown_pct,
    compute_profit_target_hit,
    compute_recovery_factor,
    compute_trading_days_count,
)
from src.backtesting.metrics.schema import (
    DrawdownMetrics,
    FtmoComplianceMetrics,
    FtmoMetricsSchema,
    PnlMetrics,
    RiskMetrics,
    TradeMetrics,
)
from src.backtesting.metrics.trade_metrics import (
    compute_avg_loss,
    compute_avg_win,
    compute_expectancy,
    compute_max_consecutive_losses,
    compute_profit_factor,
    compute_sharpe_ratio,
    compute_sortino_ratio,
    compute_win_rate,
)
from src.backtesting.result import BreachEvent, TradeRecord


def _equity_curve_to_returns(
    curve: list[tuple[datetime, Decimal]],
) -> list[float]:
    """Bar-to-bar pct returns from the equity curve (used for Sharpe/Sortino)."""
    if len(curve) < 2:
        return []
    returns: list[float] = []
    for prev, curr in zip(curve, curve[1:], strict=False):
        prev_eq = prev[1]
        curr_eq = curr[1]
        if prev_eq <= 0:
            continue
        returns.append(float((curr_eq - prev_eq) / prev_eq))
    return returns


def _max_overall_dd_abs(
    curve: list[tuple[datetime, Decimal]],
) -> Decimal:
    if len(curve) < 2:
        return Decimal("0")
    peak = curve[0][1]
    worst = Decimal("0")
    for _, eq in curve:
        if eq > peak:
            peak = eq
        elif peak - eq > worst:
            worst = peak - eq
    return worst


def calculate_metrics(
    *,
    strategy_name: str,
    initial_balance: Decimal,
    final_balance: Decimal,
    equity_curve: list[tuple[datetime, Decimal]],
    trades: list[TradeRecord],
    breaches: list[BreachEvent],
    profit_target_pct: float = 10.0,
    max_dd_pct: float = 10.0,
    min_trading_days: int = 4,
) -> FtmoMetricsSchema:
    """Assemble the top-level metrics envelope for a completed backtest.

    Notes on metric conventions used here:

    * ``return_pct`` and all drawdown/daily-DD percentages are expressed
      as percentage-points (``5.0`` means +5%).
    * ``calmar_ratio`` uses total-run return ÷ max-overall-DD (both %),
      not annualised return. Suited to backtest scoring; document if
      downstream expects the classical annualised variant.
    * ``avg_r_multiple`` is computed as ``net_pnl / |avg_loss|``. This is
      a recovery-per-avg-loss heuristic, not a per-trade R-multiple. True
      R-multiples require per-trade initial-risk which is only available
      once bracket orders are wired end-to-end (Story 8.4+).
    """
    pnls = [float(t.pnl) for t in trades]
    returns = _equity_curve_to_returns(equity_curve)

    net_pnl_decimal = final_balance - initial_balance
    net_pnl = float(net_pnl_decimal)
    # Expressed as percentage (e.g. 5.0 = +5%) — matches FtmoMetricsSchema
    # convention used by drawdown.max_overall_dd_pct.
    return_pct = (
        float(net_pnl_decimal / initial_balance * 100)
        if initial_balance > 0
        else 0.0
    )

    # Sum of absolute-value risks per losing trade (simple R-multiple proxy).
    avg_loss_abs = abs(compute_avg_loss(pnls))
    avg_r_multiple = (
        float(net_pnl / avg_loss_abs) if avg_loss_abs > 0 else 0.0
    )

    max_overall_dd_pct = compute_max_overall_drawdown_pct(equity_curve)
    max_overall_dd_abs = float(_max_overall_dd_abs(equity_curve))
    daily_pcts_magnitudes = [
        abs(p)
        for p in _daily_pct_list(equity_curve, initial_balance)
        if p < 0
    ]
    avg_daily_dd_pct = (
        sum(daily_pcts_magnitudes) / len(daily_pcts_magnitudes)
        if daily_pcts_magnitudes
        else 0.0
    )

    max_daily_dd_pct = compute_max_daily_drawdown_pct(
        equity_curve, initial_balance=initial_balance
    )

    calmar = (
        return_pct / max_overall_dd_pct if max_overall_dd_pct > 0 else 0.0
    )

    pnl = PnlMetrics(
        gross_pnl=sum(pnls) if pnls else 0.0,
        net_pnl=net_pnl,
        return_pct=return_pct,
        profit_factor=compute_profit_factor(pnls),
        expectancy=compute_expectancy(pnls),
        avg_r_multiple=avg_r_multiple,
    )

    drawdown = DrawdownMetrics(
        max_overall_dd_pct=max_overall_dd_pct,
        max_overall_dd_abs=max_overall_dd_abs,
        max_daily_dd_pct=max_daily_dd_pct,
        avg_daily_dd_pct=avg_daily_dd_pct,
        recovery_factor=compute_recovery_factor(
            net_pnl=net_pnl_decimal,
            max_dd_abs=Decimal(str(max_overall_dd_abs)),
        ),
    )

    risk = RiskMetrics(
        sharpe_ratio=compute_sharpe_ratio(returns),
        sortino_ratio=compute_sortino_ratio(returns),
        calmar_ratio=calmar,
        max_consecutive_losses=compute_max_consecutive_losses(pnls),
    )

    winners = sum(1 for p in pnls if p > 0)
    losers = sum(1 for p in pnls if p < 0)
    trade_metrics = TradeMetrics(
        total_trades=len(trades),
        winning_trades=winners,
        losing_trades=losers,
        win_rate=compute_win_rate(pnls),
        avg_win=compute_avg_win(pnls),
        avg_loss=compute_avg_loss(pnls),
    )

    daily_loss_breaches = sum(
        1 for b in breaches if b.rule_name == "daily_loss_limit"
    )
    compliance = FtmoComplianceMetrics(
        daily_loss_breaches=daily_loss_breaches,
        max_dd_breach=max_overall_dd_pct > max_dd_pct,
        profit_target_hit=compute_profit_target_hit(
            initial_balance=initial_balance,
            final_balance=final_balance,
            target_pct=profit_target_pct,
        ),
        min_trading_days_met=compute_trading_days_count(equity_curve)
        >= min_trading_days,
    )

    return FtmoMetricsSchema(
        strategy_name=strategy_name,
        pnl=pnl,
        drawdown=drawdown,
        risk=risk,
        trades=trade_metrics,
        ftmo_compliance=compliance,
    )


def _daily_pct_list(
    curve: list[tuple[datetime, Decimal]], initial_balance: Decimal
) -> list[float]:
    """Per-day P&L % list (internal helper)."""
    from src.backtesting.metrics.ftmo_metrics import compute_daily_pnl_percentages

    return compute_daily_pnl_percentages(curve, initial_balance=initial_balance)
