"""BacktestResult and companion dataclasses for backtest output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backtesting.metrics.schema import FtmoMetricsSchema


@dataclass(frozen=True)
class TradeRecord:
    """Single closed trade in backtest output."""

    trade_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_ts: datetime
    exit_ts: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class BreachEvent:
    """FTMO rule-engine breach captured during backtest."""

    ts: datetime
    rule_name: str
    current_value: float
    threshold_value: float
    message: str


@dataclass(frozen=True)
class BacktestResult:
    """Aggregated backtest output."""

    strategy_name: str
    start: datetime
    end: datetime
    initial_balance: Decimal
    final_balance: Decimal
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    breaches: list[BreachEvent] = field(default_factory=list)
    metrics: FtmoMetricsSchema | None = None
