"""SQLAlchemy ORM models for database tables.

These models map to TimescaleDB tables defined in infra/timescaledb/init.sql.
CRITICAL: All financial fields use DECIMAL for precision.
"""

from __future__ import annotations

import uuid as uuid_module
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DECIMAL, TIMESTAMP, CheckConstraint, Column, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from .trade import Trade


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""

    pass


class TradeRecord(Base):
    """SQLAlchemy model for trades table.

    Maps to the 'trades' table in TimescaleDB.
    Used for persisting trade execution audit records and querying realized P&L.

    CRITICAL: All financial fields are DECIMAL, not float.

    Table Schema (from infra/timescaledb/init.sql):
        trade_id UUID PRIMARY KEY
        account_id VARCHAR(50) NOT NULL
        strategy_name VARCHAR(100) NOT NULL
        symbol VARCHAR(20) NOT NULL
        side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL'))
        quantity DECIMAL(18, 8) NOT NULL
        entry_price DECIMAL(18, 5) NOT NULL
        entry_time TIMESTAMPTZ NOT NULL
        exit_price DECIMAL(18, 5)
        exit_time TIMESTAMPTZ
        pnl_dollars DECIMAL(18, 2)
        pnl_percent DECIMAL(8, 4)
        slippage DECIMAL(18, 5)
        signal_reason TEXT
        metadata JSONB
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled'))
        created_at TIMESTAMPTZ DEFAULT NOW()
    """

    __tablename__ = "trades"

    trade_id = Column(UUID, primary_key=True)
    account_id = Column(String(50), nullable=False, index=True)
    strategy_name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)
    order_type = Column(String(20), nullable=False, default="MARKET")
    quantity = Column(DECIMAL(18, 8), nullable=False)
    entry_price = Column(DECIMAL(18, 5), nullable=False)
    entry_time = Column(TIMESTAMP(timezone=True), nullable=False)
    exit_price = Column(DECIMAL(18, 5), nullable=True)
    exit_time = Column(TIMESTAMP(timezone=True), nullable=True)
    pnl_dollars = Column(DECIMAL(18, 2), nullable=True)
    pnl_percent = Column(DECIMAL(8, 4), nullable=True)
    slippage_pips = Column("slippage_pips", DECIMAL(18, 2), nullable=True)
    signal_reason = Column(String, nullable=True)
    signal_metadata = Column("metadata", JSONB, nullable=True)
    status = Column(String(20), default="open", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="check_side"),
        CheckConstraint(
            "status IN ('open', 'closed', 'cancelled')", name="check_status"
        ),
        Index("idx_trades_account_time", "account_id", "entry_time"),
        Index("idx_trades_account_exit_time", "account_id", "exit_time"),
        Index("idx_trades_strategy", "strategy_name", "entry_time"),
    )

    @classmethod
    def from_trade(
        cls,
        trade: "Trade",
        strategy_name: str,
        signal_reason: Optional[str] = None,
        signal_metadata: Optional[dict[str, Any]] = None,
    ) -> "TradeRecord":
        """Create TradeRecord from Trade dataclass.

        Args:
            trade: Trade dataclass instance.
            strategy_name: REQUIRED - name of strategy that generated the trade.
            signal_reason: Optional reason extracted from signal.metadata.get('reason').
            signal_metadata: Optional signal metadata dict.

        Returns:
            TradeRecord instance ready for database insertion.

        Raises:
            ValueError: If strategy_name is None or empty (DB constraint).
        """
        if not strategy_name:
            raise ValueError("strategy_name is required (NOT NULL constraint in database)")

        return cls(
            trade_id=uuid_module.UUID(trade.trade_id),
            account_id=trade.account_id,
            strategy_name=strategy_name,
            symbol=trade.symbol,
            side=trade.side.value,
            order_type="MARKET",
            quantity=Decimal(str(trade.quantity)),
            entry_price=Decimal(str(trade.entry_price)),
            entry_time=trade.entry_time,
            exit_price=Decimal(str(trade.exit_price)) if trade.exit_price else None,
            exit_time=trade.exit_time,
            pnl_dollars=Decimal(str(trade.pnl_dollars)) if trade.pnl_dollars else None,
            pnl_percent=Decimal(str(trade.pnl_percent)) if trade.pnl_percent else None,
            slippage_pips=Decimal(str(trade.slippage)) if trade.slippage else None,
            signal_reason=signal_reason,
            signal_metadata=signal_metadata,
            status="open" if trade.is_open else "closed",
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize TradeRecord to dictionary.

        Financial fields are serialized as strings to preserve DECIMAL precision
        for compliance reporting. Use Decimal(value) to restore precision.

        Returns:
            Dictionary representation of the trade record.
        """
        return {
            "trade_id": str(self.trade_id),
            "account_id": self.account_id,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "entry_price": str(self.entry_price) if self.entry_price is not None else None,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_price": str(self.exit_price) if self.exit_price is not None else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "pnl_dollars": str(self.pnl_dollars) if self.pnl_dollars is not None else None,
            "pnl_percent": str(self.pnl_percent) if self.pnl_percent is not None else None,
            "slippage_pips": str(self.slippage_pips) if self.slippage_pips is not None else None,
            "signal_reason": self.signal_reason,
            "metadata": self.signal_metadata,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
