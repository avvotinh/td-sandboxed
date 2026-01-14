"""SQLAlchemy model for state_snapshots hypertable."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Column, DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from .snapshot import StateSnapshot


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class StateSnapshotModel(Base):
    """SQLAlchemy model for state_snapshots hypertable.

    Maps to TimescaleDB state_snapshots table for cold storage backup.
    Used as fallback when Redis snapshots are unavailable.

    Note: Uses separate DeclarativeBase from AuditDBWriter intentionally
    for module isolation. These models don't share transactions.
    If future stories need cross-model queries, consider a shared base
    in `src/models/base.py`.

    Table Schema (from infra/timescaledb/init.sql):
        id UUID
        account_id VARCHAR(50) NOT NULL
        timestamp TIMESTAMPTZ NOT NULL
        positions JSONB NOT NULL
        pending_orders JSONB NOT NULL
        account_balance DECIMAL(18, 2) NOT NULL
        equity DECIMAL(18, 2) NOT NULL
        peak_balance DECIMAL(18, 2) NOT NULL
        daily_starting_balance DECIMAL(18, 2) NOT NULL
        checksum VARCHAR(64) NOT NULL
        created_at TIMESTAMPTZ DEFAULT NOW()
    """

    __tablename__ = "state_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, primary_key=True)
    positions = Column(JSONB, nullable=False)
    pending_orders = Column(JSONB, nullable=False)
    account_balance = Column(Numeric(18, 2), nullable=False)
    equity = Column(Numeric(18, 2), nullable=False)
    peak_balance = Column(Numeric(18, 2), nullable=False)
    daily_starting_balance = Column(Numeric(18, 2), nullable=False)
    checksum = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def from_snapshot(cls, snapshot: StateSnapshot) -> StateSnapshotModel:
        """Create model from StateSnapshot dataclass.

        Args:
            snapshot: StateSnapshot instance to convert.

        Returns:
            StateSnapshotModel ready for database insert.
        """
        return cls(
            id=uuid.uuid4(),
            account_id=snapshot.account_id,
            timestamp=snapshot.timestamp,
            positions=snapshot.positions,  # Already a list of dicts
            pending_orders=snapshot.pending_orders,
            account_balance=Decimal(str(snapshot.account_balance)),
            equity=Decimal(str(snapshot.equity)),
            peak_balance=Decimal(str(snapshot.peak_balance)),
            daily_starting_balance=Decimal(str(snapshot.daily_starting_balance)),
            checksum=snapshot.checksum,
        )

    def to_snapshot(self) -> StateSnapshot:
        """Convert model back to StateSnapshot dataclass.

        Returns:
            StateSnapshot instance with data from database.
        """
        from .snapshot import StateSnapshot

        return StateSnapshot(
            account_id=self.account_id,
            timestamp=self.timestamp,
            positions=self.positions,
            pending_orders=self.pending_orders,
            account_balance=Decimal(str(self.account_balance)),
            equity=Decimal(str(self.equity)),
            peak_balance=Decimal(str(self.peak_balance)),
            daily_starting_balance=Decimal(str(self.daily_starting_balance)),
            checksum=self.checksum,
        )
