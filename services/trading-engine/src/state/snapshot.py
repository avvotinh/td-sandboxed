"""StateSnapshot dataclass for account state persistence.

This module provides the data model for periodic account state snapshots
stored in Redis for crash recovery purposes.

Snapshot Strategy:
- Snapshots are created every 5 seconds for active accounts
- Stored at Redis key: snapshot:{account_id}:latest
- TTL: 1 hour (3600 seconds)
- SHA256 checksum for data integrity validation
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StateSnapshot:
    """Point-in-time snapshot of account state for crash recovery.

    All data needed to recover an account after system restart:
    - Open positions and pending orders
    - Balance and equity metrics
    - Risk tracking values (peak balance, daily starting balance)

    Serialization:
    - to_dict() converts to Redis hash-compatible format (all values as strings)
    - from_dict() deserializes back with type conversion
    - Checksum validates data integrity

    Example:
        snapshot = StateSnapshot(
            account_id="ftmo-gold-001",
            timestamp=datetime.now(timezone.utc),
            positions=[{"symbol": "XAUUSD", "side": "BUY", "volume": "0.1"}],
            pending_orders=[],
            account_balance=Decimal("100000.00"),
            equity=Decimal("99850.00"),
            peak_balance=Decimal("102500.00"),
            daily_starting_balance=Decimal("100500.00"),
            checksum="",
        )
        snapshot.checksum = snapshot.compute_checksum()

    Attributes:
        account_id: Unique account identifier
        timestamp: When snapshot was created (UTC)
        positions: List of position dicts with symbol, side, volume, entry_price, entry_time, order_id
        pending_orders: List of pending order dicts (empty for MVP)
        account_balance: Current account balance
        equity: Current account equity (balance + unrealized P&L)
        peak_balance: Highest equity reached (high water mark for drawdown)
        daily_starting_balance: Balance at start of trading day
        checksum: SHA256 hash of all other fields for integrity validation
    """

    account_id: str
    timestamp: datetime
    positions: list[dict[str, Any]]
    pending_orders: list[dict[str, Any]]
    account_balance: Decimal
    equity: Decimal
    peak_balance: Decimal
    daily_starting_balance: Decimal
    checksum: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to Redis hash-compatible dict (all values as strings).

        Redis hashes require string values. Complex types are JSON-encoded.

        Returns:
            Dict with string keys and string values suitable for Redis HSET.

        Example:
            >>> snapshot.to_dict()
            {
                "account_id": "ftmo-gold-001",
                "timestamp": "2026-01-03T14:32:15.123456+00:00",
                "positions": '[{"symbol": "XAUUSD", ...}]',
                "pending_orders": "[]",
                "account_balance": "100000.00",
                ...
            }
        """
        return {
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "positions": json.dumps(self.positions, sort_keys=True),
            "pending_orders": json.dumps(self.pending_orders, sort_keys=True),
            "account_balance": str(self.account_balance),
            "equity": str(self.equity),
            "peak_balance": str(self.peak_balance),
            "daily_starting_balance": str(self.daily_starting_balance),
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> StateSnapshot:
        """Deserialize from Redis hash data.

        Performs type conversion from strings back to native types:
        - JSON strings → lists
        - Decimal strings → Decimal
        - ISO timestamp → datetime

        Args:
            data: Dict from Redis HGETALL with string values

        Returns:
            StateSnapshot instance with proper types

        Raises:
            KeyError: If required fields are missing
            ValueError: If data cannot be parsed (invalid JSON, decimal, etc.)

        Example:
            >>> data = await redis.hgetall("snapshot:ftmo-gold-001:latest")
            >>> snapshot = StateSnapshot.from_dict(data)
        """
        return cls(
            account_id=data["account_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            positions=json.loads(data["positions"]),
            pending_orders=json.loads(data["pending_orders"]),
            account_balance=Decimal(data["account_balance"]),
            equity=Decimal(data["equity"]),
            peak_balance=Decimal(data["peak_balance"]),
            daily_starting_balance=Decimal(data["daily_starting_balance"]),
            checksum=data["checksum"],
        )

    def compute_checksum(self) -> str:
        """Compute SHA256 checksum of all fields except checksum itself.

        Creates a deterministic hash by:
        1. Building a dict of all fields (excluding checksum)
        2. JSON serializing with sorted keys for determinism
        3. Computing SHA256 hash

        Returns:
            Hex-encoded SHA256 hash string (64 characters)

        Note:
            The checksum field itself is excluded from computation.
            This allows validation by comparing stored vs computed checksums.
        """
        content = {
            "account_id": self.account_id,
            "timestamp": self.timestamp.isoformat(),
            "positions": json.dumps(self.positions, sort_keys=True),
            "pending_orders": json.dumps(self.pending_orders, sort_keys=True),
            "account_balance": str(self.account_balance),
            "equity": str(self.equity),
            "peak_balance": str(self.peak_balance),
            "daily_starting_balance": str(self.daily_starting_balance),
        }
        serialized = json.dumps(content, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def validate_checksum(self) -> bool:
        """Validate stored checksum matches computed checksum.

        Used to detect data corruption or tampering.

        Returns:
            True if checksum is valid, False if data was modified

        Example:
            >>> snapshot = StateSnapshot.from_dict(redis_data)
            >>> if not snapshot.validate_checksum():
            ...     raise ValueError("Snapshot data corrupted!")
        """
        computed = self.compute_checksum()
        is_valid = self.checksum == computed
        if not is_valid:
            logger.warning(
                "Checksum validation failed for account %s: stored=%s, computed=%s",
                self.account_id,
                self.checksum[:16] + "...",
                computed[:16] + "...",
            )
        return is_valid
