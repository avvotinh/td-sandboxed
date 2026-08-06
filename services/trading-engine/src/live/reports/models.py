"""Report data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class ReportSummary:
    """Computed summary metrics for a compliance report."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = field(default_factory=lambda: Decimal("0"))
    net_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    best_day_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    worst_day_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    worst_day_pnl_percent: Decimal = field(default_factory=lambda: Decimal("0"))
    trading_days: int = 0
    calendar_days: int = 0
    opening_balance: Decimal = field(default_factory=lambda: Decimal("0"))
    closing_balance: Decimal = field(default_factory=lambda: Decimal("0"))
    peak_balance: Decimal = field(default_factory=lambda: Decimal("0"))
    max_drawdown_percent: Decimal = field(default_factory=lambda: Decimal("0"))
    current_drawdown_percent: Decimal = field(default_factory=lambda: Decimal("0"))
    total_violations: int = 0
    blocked_count: int = 0
    violations_by_rule: dict[str, int] = field(default_factory=dict)


@dataclass
class ReportData:
    """All gathered data for a compliance report."""

    account_id: str
    period_start: date
    period_end: date
    generated_at: datetime
    trades: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    summary: ReportSummary = field(default_factory=ReportSummary)
