"""Comprehensive Audit Service - Unified logging for all system events.

Provides typed convenience methods for different event types while
delegating to AuditDBWriter for batch persistence.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..rules.audit_db_writer import AuditDBWriter
from ..rules.audit_logger import AuditEntry, AuditEventType

logger = logging.getLogger(__name__)


class AuditService:
    """Facade for comprehensive audit logging across all services.

    Wraps AuditDBWriter to provide typed convenience methods for
    different event types while maintaining the batch buffer pattern.
    """

    def __init__(self, db_writer: AuditDBWriter) -> None:
        self._db_writer = db_writer

    async def log_trade_executed(
        self,
        account_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        strategy_name: str,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a trade execution event."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=account_id,
            event_type=AuditEventType.TRADE_EXECUTED.value,
            event_subtype="entry_fill",
            source="execution-service",
            level="INFO",
            message=f"Trade executed: {side} {quantity} {symbol} @ {entry_price}",
            rule_name="",
            rule_result="",
            current_value=entry_price,
            threshold_value=None,
            order_id=order_id,
            trade_id=trade_id,
            context=context if context is not None else {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "strategy": strategy_name,
            },
        )
        await self._db_writer.add_entry(entry)

    async def log_position_closed(
        self,
        account_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        exit_price: float,
        pnl_dollars: float,
        order_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a position close event."""
        level = "WARNING" if pnl_dollars < 0 else "INFO"
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=account_id,
            event_type=AuditEventType.POSITION_CLOSED.value,
            event_subtype="exit_fill",
            source="execution-service",
            level=level,
            message=f"Position closed: {side} {symbol} @ {exit_price} (PnL: ${pnl_dollars:.2f})",
            rule_name="",
            rule_result="",
            current_value=exit_price,
            threshold_value=None,
            order_id=order_id,
            trade_id=trade_id,
            context=context if context is not None else {
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl_dollars": pnl_dollars,
            },
        )
        await self._db_writer.add_entry(entry)

    async def log_system_event(
        self,
        event_subtype: str,
        message: str,
        account_id: str | None = None,
        level: str = "INFO",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Log a system lifecycle event (startup, shutdown, recovery)."""
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=account_id,
            event_type=AuditEventType.SYSTEM_EVENT.value,
            event_subtype=event_subtype,
            source="trading-engine",
            level=level,
            message=message,
            rule_name="",
            rule_result="",
            current_value=None,
            threshold_value=None,
            order_id=None,
            trade_id=None,
            context=context,
        )
        await self._db_writer.add_entry(entry)
