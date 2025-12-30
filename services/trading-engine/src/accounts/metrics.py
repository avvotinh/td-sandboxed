"""AccountMetrics dataclass for per-account financial metrics display.

Combines balance (from MT5) with risk metrics (from RiskStateRegistry)
to provide a complete financial picture of each account.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class AccountMetrics:
    """Per-account financial metrics for display.

    Combines balance (from MT5) with risk metrics (from RiskStateRegistry)
    to provide a complete financial picture of each account.

    IMPORTANT: All financial values use Decimal for precision.

    Attributes:
        account_id: Unique account identifier
        account_name: Human-readable account name
        status: Account status (active, paused, stopped, error)
        balance: Current account balance (USD)
        equity: Current account equity (balance + unrealized P&L)
        daily_pnl: Accumulated P&L for current trading day (USD)
        daily_pnl_percent: Daily P&L as percentage of starting balance
        peak_equity: Highest equity reached (high water mark)
        max_drawdown_percent: Drawdown from peak as percentage
        last_updated: Timestamp of last state update
    """

    account_id: str
    account_name: str
    status: str  # active, paused, stopped, error
    balance: Decimal = Decimal("0")
    equity: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    daily_pnl_percent: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L = Equity - Balance."""
        return self.equity - self.balance

    @staticmethod
    def format_currency(value: Decimal) -> str:
        """Format decimal as currency string.

        Args:
            value: Decimal value to format

        Returns:
            Formatted string like "$100,000.00" or "-$1,500.00"
        """
        if value < 0:
            return f"-${abs(value):,.2f}"
        return f"${value:,.2f}"

    @staticmethod
    def format_percent(value: Decimal, show_sign: bool = True) -> str:
        """Format decimal as percentage string.

        Args:
            value: Decimal value to format (e.g., -1.5 for -1.5%)
            show_sign: Whether to show +/- sign

        Returns:
            Formatted string like "+0.8%" or "-1.5%"
        """
        if show_sign:
            return f"{value:+.1f}%"
        return f"{value:.1f}%"

    def to_status_dict(self) -> dict[str, str]:
        """Format metrics for CLI status display.

        Returns:
            Dict with formatted string values for display
        """
        return {
            "account_id": self.account_id,
            "account_name": self.account_name,
            "status": self.status,
            "balance": self.format_currency(self.balance),
            "equity": self.format_currency(self.equity),
            "daily_pnl": f"{self.format_currency(self.daily_pnl)} ({self.format_percent(self.daily_pnl_percent)})",
            "max_drawdown": self.format_percent(self.max_drawdown_percent, show_sign=False),
            "peak_equity": self.format_currency(self.peak_equity),
        }

    def to_list_row(self) -> list[str]:
        """Format metrics for CLI list table row.

        Returns:
            List of formatted string values for table row
        """
        return [
            self.account_id,
            self.account_name,
            self.status,
            self.format_currency(self.balance),
            self.format_percent(self.daily_pnl_percent),
        ]
