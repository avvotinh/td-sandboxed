"""SQLAlchemy ORM models for database tables.

These models map to TimescaleDB tables defined in infra/timescaledb/init.sql.
CRITICAL: All financial fields use DECIMAL for precision.
"""

from sqlalchemy import DECIMAL, TIMESTAMP, CheckConstraint, Column, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""

    pass


class TradeRecord(Base):
    """SQLAlchemy model for trades table.

    Maps to the 'trades' table in TimescaleDB.
    Used for querying realized P&L during crash recovery.

    CRITICAL: All financial fields are DECIMAL, not float.

    Table Schema (from infra/timescaledb/init.sql):
        trade_id UUID PRIMARY KEY
        account_id VARCHAR(50) NOT NULL
        symbol VARCHAR(20) NOT NULL
        side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL'))
        quantity DECIMAL(18, 8) NOT NULL
        entry_price DECIMAL(18, 5) NOT NULL
        entry_time TIMESTAMPTZ NOT NULL
        exit_price DECIMAL(18, 5)
        exit_time TIMESTAMPTZ
        pnl_dollars DECIMAL(18, 2)
        status VARCHAR(20) DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled'))
        created_at TIMESTAMPTZ DEFAULT NOW()
    """

    __tablename__ = "trades"

    trade_id = Column(UUID, primary_key=True)
    account_id = Column(String(50), nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)
    entry_price = Column(DECIMAL(18, 5), nullable=False)
    entry_time = Column(TIMESTAMP(timezone=True), nullable=False)
    exit_price = Column(DECIMAL(18, 5), nullable=True)
    exit_time = Column(TIMESTAMP(timezone=True), nullable=True)
    pnl_dollars = Column(DECIMAL(18, 2), nullable=True)
    status = Column(String(20), default="open", nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="check_side"),
        CheckConstraint(
            "status IN ('open', 'closed', 'cancelled')", name="check_status"
        ),
        Index("idx_trades_account_time", "account_id", "entry_time"),
        Index("idx_trades_account_exit_time", "account_id", "exit_time"),
    )
