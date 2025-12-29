"""RiskState dataclass for per-account risk metrics.

Each account has its own isolated RiskState instance.
No state is shared between accounts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class RiskState:
    """Per-account risk metrics state.

    Each account has its own isolated RiskState instance.
    No state is shared between accounts.

    Attributes:
        daily_pnl: Accumulated P&L for current trading day (USD)
        daily_pnl_percent: Daily P&L as percentage of starting balance
        current_equity: Current account equity (balance + unrealized P&L)
        peak_equity: Highest equity reached (high water mark)
        total_drawdown_percent: Drawdown from peak as percentage
        daily_starting_balance: Balance at start of trading day
        last_updated: Timestamp of last state update
    """

    daily_pnl: Decimal = Decimal("0")
    daily_pnl_percent: Decimal = Decimal("0")
    current_equity: Decimal = Decimal("0")
    peak_equity: Decimal = Decimal("0")
    total_drawdown_percent: Decimal = Decimal("0")
    daily_starting_balance: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def drawdown_from_peak(self) -> Decimal:
        """Calculate current drawdown from peak equity.

        Returns:
            Drawdown percentage (0-100 scale)
        """
        if self.peak_equity <= 0:
            return Decimal("0")
        return (self.peak_equity - self.current_equity) / self.peak_equity * 100

    def update_equity(self, equity: Decimal) -> None:
        """Update current equity and recalculate drawdown.

        Args:
            equity: New current equity value
        """
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity
        self.total_drawdown_percent = self.drawdown_from_peak
        self.last_updated = datetime.now(timezone.utc)

    def record_trade(self, realized_pnl: Decimal) -> None:
        """Record realized P&L from a completed trade.

        Args:
            realized_pnl: Realized profit/loss from trade
        """
        self.daily_pnl += realized_pnl
        if self.daily_starting_balance > 0:
            self.daily_pnl_percent = self.daily_pnl / self.daily_starting_balance * 100
        self.last_updated = datetime.now(timezone.utc)

    def reset_daily(self, starting_balance: Decimal) -> None:
        """Reset daily metrics at midnight UTC.

        Args:
            starting_balance: Account balance at start of new day
        """
        self.daily_pnl = Decimal("0")
        self.daily_pnl_percent = Decimal("0")
        self.daily_starting_balance = starting_balance
        self.last_updated = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, str]:
        """Serialize to dict for Redis storage.

        Returns:
            Dict with string values for Redis HSET
        """
        return {
            "daily_pnl": str(self.daily_pnl),
            "daily_pnl_percent": str(self.daily_pnl_percent),
            "current_equity": str(self.current_equity),
            "peak_equity": str(self.peak_equity),
            "total_drawdown_percent": str(self.total_drawdown_percent),
            "daily_starting_balance": str(self.daily_starting_balance),
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "RiskState":
        """Deserialize from Redis hash data.

        Args:
            data: Dict from Redis HGETALL

        Returns:
            RiskState instance
        """
        return cls(
            daily_pnl=Decimal(data.get("daily_pnl", "0")),
            daily_pnl_percent=Decimal(data.get("daily_pnl_percent", "0")),
            current_equity=Decimal(data.get("current_equity", "0")),
            peak_equity=Decimal(data.get("peak_equity", "0")),
            total_drawdown_percent=Decimal(data.get("total_drawdown_percent", "0")),
            daily_starting_balance=Decimal(data.get("daily_starting_balance", "0")),
            last_updated=datetime.fromisoformat(
                data.get("last_updated", datetime.now(timezone.utc).isoformat())
            ),
        )
