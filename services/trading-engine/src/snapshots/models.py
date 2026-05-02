"""AccountSnapshotModel ORM - Maps to account_snapshots table in TimescaleDB.

Schema source: infra/timescaledb/init.sql (AUTHORITATIVE - 17 data columns).
This is a regular PostgreSQL table (NOT a hypertable).
"""

import uuid
from datetime import time
from decimal import Decimal

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class AccountSnapshotModel(Base):
    """ORM model for account_snapshots table.

    UNIQUE(account_id, snapshot_date) enables idempotent upserts via
    INSERT ... ON CONFLICT DO UPDATE.
    """

    __tablename__ = "account_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "snapshot_date",
            name="account_snapshots_account_id_snapshot_date_key",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    snapshot_time = Column(Time, nullable=True, default=time(0, 0, 0))
    opening_balance = Column(Numeric(18, 2), nullable=True)
    closing_balance = Column(Numeric(18, 2), nullable=True)
    high_balance = Column(Numeric(18, 2), nullable=True)
    low_balance = Column(Numeric(18, 2), nullable=True)
    daily_pnl = Column(Numeric(18, 2), nullable=True)
    daily_pnl_percent = Column(Numeric(8, 4), nullable=True)
    peak_balance = Column(Numeric(18, 2), nullable=True)
    drawdown_from_peak = Column(Numeric(18, 2), nullable=True)
    drawdown_percent = Column(Numeric(8, 4), nullable=True)
    trades_count = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    total_volume = Column(Numeric(18, 2), default=Decimal("0"))
    created_at = Column(DateTime(timezone=True), server_default="NOW()")

    @classmethod
    def from_snapshot_data(cls, data: dict) -> "AccountSnapshotModel":
        """Create model instance from collected snapshot metrics dict.

        All financial values are converted to Decimal via str() to
        prevent floating-point precision loss.
        """

        def _to_decimal(value: object) -> Decimal | None:
            if value is None:
                return None
            return Decimal(str(value))

        return cls(
            account_id=data["account_id"],
            snapshot_date=data["snapshot_date"],
            snapshot_time=data.get("snapshot_time", time(0, 0, 0)),
            opening_balance=_to_decimal(data.get("opening_balance")),
            closing_balance=_to_decimal(data.get("closing_balance")),
            high_balance=_to_decimal(data.get("high_balance")),
            low_balance=_to_decimal(data.get("low_balance")),
            daily_pnl=_to_decimal(data.get("daily_pnl")),
            daily_pnl_percent=_to_decimal(data.get("daily_pnl_percent")),
            peak_balance=_to_decimal(data.get("peak_balance")),
            drawdown_from_peak=_to_decimal(data.get("drawdown_from_peak")),
            drawdown_percent=_to_decimal(data.get("drawdown_percent")),
            trades_count=data.get("trades_count", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            total_volume=_to_decimal(data.get("total_volume")) or Decimal("0"),
        )

    def to_dict(self) -> dict[str, str | int | None]:
        """Serialize to dict with financial fields as strings for precision."""
        return {
            "id": str(self.id) if self.id else None,
            "account_id": self.account_id,
            "snapshot_date": self.snapshot_date.isoformat() if self.snapshot_date else None,
            "snapshot_time": self.snapshot_time.isoformat() if self.snapshot_time else None,
            "opening_balance": str(self.opening_balance) if self.opening_balance is not None else None,
            "closing_balance": str(self.closing_balance) if self.closing_balance is not None else None,
            "high_balance": str(self.high_balance) if self.high_balance is not None else None,
            "low_balance": str(self.low_balance) if self.low_balance is not None else None,
            "daily_pnl": str(self.daily_pnl) if self.daily_pnl is not None else None,
            "daily_pnl_percent": str(self.daily_pnl_percent) if self.daily_pnl_percent is not None else None,
            "peak_balance": str(self.peak_balance) if self.peak_balance is not None else None,
            "drawdown_from_peak": str(self.drawdown_from_peak) if self.drawdown_from_peak is not None else None,
            "drawdown_percent": str(self.drawdown_percent) if self.drawdown_percent is not None else None,
            "trades_count": self.trades_count,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_volume": str(self.total_volume) if self.total_volume is not None else None,
        }
