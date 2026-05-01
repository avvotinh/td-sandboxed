"""Comprehensive Audit Service - Unified logging for all system events.

Provides typed convenience methods for different event types while
delegating to :class:`AuditWriter` for persistence.

Story 10.3 split each event into an *async* and *sync* variant:

- ``log_*`` (default) routes through :meth:`AuditWriter.log_async` —
  the entry is enqueued for batched persistence. Suitable for telemetry.
- ``log_*_sync`` routes through :meth:`AuditWriter.log_sync` and blocks
  the caller until the row hits the database. Mandatory for any event
  preceding a write to ``account.*`` tables (double-entry discipline,
  see ``.claude/rules/database/audit.md``) and for emergency events
  whose audit trail must survive a crash mid-shutdown.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from ..rules.audit_logger import AuditEntry, AuditEventType
from .audit_writer import AuditWriter

logger = logging.getLogger(__name__)


class AuditService:
    """Facade for comprehensive audit logging across all services.

    Wraps :class:`AuditWriter` to provide typed convenience methods for
    different event types. Each event type exposes a ``log_*`` (async,
    enqueued) and a ``log_*_sync`` (blocking until commit) variant; the
    caller picks based on whether the surrounding mutation requires
    audit-first durability.
    """

    def __init__(self, writer: AuditWriter) -> None:
        self._writer = writer

    @property
    def writer(self) -> AuditWriter:
        return self._writer

    async def start(self) -> None:
        """Start the underlying writer (idempotent)."""
        await self._writer.start()

    async def stop(self) -> None:
        """Stop the underlying writer, flushing buffered entries."""
        await self._writer.stop()

    async def drain(self, timeout: float | None = None) -> None:
        """Wait until every queued entry is persisted."""
        await self._writer.drain(timeout=timeout)

    # ----- Trade-execution events --------------------------------------

    def _build_trade_executed_entry(
        self,
        *,
        account_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        entry_price: float,
        strategy_name: str,
        order_id: str | None,
        context: dict[str, Any] | None,
    ) -> AuditEntry:
        return AuditEntry(
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
        """Enqueue a trade-execution event (async path)."""
        entry = self._build_trade_executed_entry(
            account_id=account_id,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            strategy_name=strategy_name,
            order_id=order_id,
            context=context,
        )
        await self._writer.log_async(entry)

    async def log_trade_executed_sync(
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
        """Persist a trade-execution event before the caller continues.

        Use when the audit row must precede any subsequent write to
        ``account.*`` tables.
        """
        entry = self._build_trade_executed_entry(
            account_id=account_id,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=entry_price,
            strategy_name=strategy_name,
            order_id=order_id,
            context=context,
        )
        await self._writer.log_sync(entry)

    # ----- Position-close events ---------------------------------------

    def _build_position_closed_entry(
        self,
        *,
        account_id: str,
        trade_id: str,
        symbol: str,
        side: str,
        exit_price: float,
        pnl_dollars: float,
        order_id: str | None,
        context: dict[str, Any] | None,
    ) -> AuditEntry:
        level = "WARNING" if pnl_dollars < 0 else "INFO"
        return AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id=account_id,
            event_type=AuditEventType.POSITION_CLOSED.value,
            event_subtype="exit_fill",
            source="execution-service",
            level=level,
            message=(
                f"Position closed: {side} {symbol} @ {exit_price} "
                f"(PnL: ${pnl_dollars:.2f})"
            ),
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
        """Enqueue a position-close event (async path)."""
        entry = self._build_position_closed_entry(
            account_id=account_id,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            exit_price=exit_price,
            pnl_dollars=pnl_dollars,
            order_id=order_id,
            context=context,
        )
        await self._writer.log_async(entry)

    async def log_position_closed_sync(
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
        """Persist a position-close event before the caller continues."""
        entry = self._build_position_closed_entry(
            account_id=account_id,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            exit_price=exit_price,
            pnl_dollars=pnl_dollars,
            order_id=order_id,
            context=context,
        )
        await self._writer.log_sync(entry)

    # ----- System lifecycle events -------------------------------------

    def _build_system_event_entry(
        self,
        *,
        event_subtype: str,
        message: str,
        account_id: str | None,
        level: str,
        context: dict[str, Any] | None,
    ) -> AuditEntry:
        return AuditEntry(
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

    async def log_system_event(
        self,
        event_subtype: str,
        message: str,
        account_id: str | None = None,
        level: str = "INFO",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Enqueue a system lifecycle event (async path)."""
        entry = self._build_system_event_entry(
            event_subtype=event_subtype,
            message=message,
            account_id=account_id,
            level=level,
            context=context,
        )
        await self._writer.log_async(entry)

    async def log_system_event_sync(
        self,
        event_subtype: str,
        message: str,
        account_id: str | None = None,
        level: str = "INFO",
        context: dict[str, Any] | None = None,
    ) -> None:
        """Persist a system lifecycle event before the caller continues.

        Use for emergency events (lock_lost, emergency_stop, ...) whose
        audit trail must survive even if the process is killed seconds
        later.
        """
        entry = self._build_system_event_entry(
            event_subtype=event_subtype,
            message=message,
            account_id=account_id,
            level=level,
            context=context,
        )
        await self._writer.log_sync(entry)
