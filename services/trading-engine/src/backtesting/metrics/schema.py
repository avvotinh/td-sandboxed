"""Pydantic schema for prop-firm-aware backtest metrics.

The schema is the contract between the backtest metrics calculator and any
downstream consumer (JSON report, HTML report, walk-forward aggregator,
external tooling). Nested models group related metrics so reports can
render sections directly.

Epic 9 rename: ``FtmoMetricsSchema`` → ``PropFirmMetricsSchema`` and
``FtmoComplianceMetrics`` → ``PropFirmComplianceMetrics``. The schema
shape is unchanged; naming now reflects the multi-firm abstraction.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PnlMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    gross_pnl: float
    net_pnl: float
    return_pct: float
    profit_factor: float = Field(..., ge=0)
    expectancy: float
    avg_r_multiple: float


class DrawdownMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_overall_dd_pct: float = Field(..., ge=0)
    max_overall_dd_abs: float = Field(..., ge=0)
    max_daily_dd_pct: float = Field(..., ge=0)
    avg_daily_dd_pct: float = Field(..., ge=0)
    recovery_factor: float


class RiskMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_consecutive_losses: int = Field(..., ge=0)


class TradeMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_trades: int = Field(..., ge=0)
    winning_trades: int = Field(..., ge=0)
    losing_trades: int = Field(..., ge=0)
    win_rate: float = Field(..., ge=0, le=1)
    avg_win: float
    avg_loss: float


class PropFirmComplianceMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    daily_loss_breaches: int = Field(..., ge=0)
    max_dd_breach: bool
    profit_target_hit: bool
    min_trading_days_met: bool


class PropFirmMetricsSchema(BaseModel):
    """Top-level metrics envelope emitted at the end of every backtest."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    pnl: PnlMetrics
    drawdown: DrawdownMetrics
    risk: RiskMetrics
    trades: TradeMetrics
    prop_firm_compliance: PropFirmComplianceMetrics
