"""Daily Snapshot Service - Midnight UTC scheduler for account compliance snapshots.

Collects data from:
- Redis: RiskState (daily_pnl, opening_balance, drawdown)
- Redis: StateSnapshot (closing_balance, peak_balance)
- TimescaleDB: state_snapshots (intraday high/low balance)
- TimescaleDB: trades (daily trade stats)

Scheduling: asyncio-native (no APScheduler dependency).
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from .snapshot_db_writer import SnapshotDBWriter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from ..accounts.account_manager import AccountManager
    from ..audit.audit_service import AuditService
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


class DailySnapshotService:
    """Collects and persists daily account snapshots at midnight UTC."""

    def __init__(
        self,
        db_writer: SnapshotDBWriter,
        redis_state: "RedisStateManager",
        account_manager: "AccountManager",
        db_session_factory: "async_sessionmaker",
        audit_service: "AuditService | None" = None,
    ) -> None:
        self._db_writer = db_writer
        self._redis_state = redis_state
        self._account_manager = account_manager
        self._session_factory = db_session_factory
        self._audit_service = audit_service
        self._scheduler_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(), name="daily_snapshot_scheduler",
        )
        logger.info("DailySnapshotService started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("DailySnapshotService stopped")

    @staticmethod
    def _calculate_seconds_until_midnight() -> float:
        """Return seconds from now until next midnight UTC."""
        now = datetime.now(timezone.utc)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        return (next_midnight - now).total_seconds()

    async def _scheduler_loop(self) -> None:
        """Sleep until midnight UTC, take snapshots, repeat."""
        while self._running:
            delay = self._calculate_seconds_until_midnight()
            logger.info(
                "Next daily snapshot in %.0f seconds",
                delay,
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            if self._running:
                await self._take_all_snapshots()

    async def _take_all_snapshots(self) -> None:
        """Take a snapshot for every active account (fire-and-forget per account).

        IMPORTANT: This must run BEFORE any daily risk state reset
        (RiskState.reset_daily / RedisStateManager.reset_daily_risk_state)
        because it reads daily_pnl and daily_pnl_percent from Redis.
        If the reset runs first, the snapshot captures zeroed-out values.
        """
        # The snapshot_date is the day that just ended (yesterday from midnight's POV)
        snapshot_date = (datetime.now(timezone.utc) - timedelta(seconds=1)).date()
        active_accounts = self._account_manager.get_active_account_ids()

        logger.info(
            "Taking daily snapshots for %d accounts (date: %s)",
            len(active_accounts),
            snapshot_date,
        )

        success_count = 0
        for account_id in active_accounts:
            try:
                data = await self._collect_snapshot_data(account_id, snapshot_date)
                await self._db_writer.write_snapshot(data)
                success_count += 1
                logger.info("Snapshot saved: %s / %s", account_id, snapshot_date)
            except Exception:
                logger.exception("Failed to snapshot account %s", account_id)

        logger.info(
            "Daily snapshots complete: %d/%d succeeded",
            success_count,
            len(active_accounts),
        )

        # Fire-and-forget audit log
        if self._audit_service and success_count > 0:
            from ..rules.audit_logger import audit_task_done_callback

            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="daily_snapshot",
                    message=f"Daily snapshots taken: {success_count}/{len(active_accounts)} accounts",
                    context={
                        "snapshot_date": str(snapshot_date),
                        "success_count": success_count,
                        "total_accounts": len(active_accounts),
                    },
                ),
                name="audit_daily_snapshot",
            )
            task.add_done_callback(audit_task_done_callback)

    async def _collect_snapshot_data(
        self, account_id: str, snapshot_date: date,
    ) -> dict[str, Any]:
        """Gather snapshot data from Redis state + TimescaleDB queries."""
        midnight_utc = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
        next_midnight = midnight_utc + timedelta(days=1)

        # 1. Redis risk state
        risk_state = await self._redis_state.get_risk_state(account_id)
        # 2. Redis state snapshot
        state_snapshot = await self._redis_state.get_snapshot(account_id)

        opening_balance = risk_state.daily_starting_balance if risk_state else None
        closing_balance = state_snapshot.account_balance if state_snapshot else None
        daily_pnl = risk_state.daily_pnl if risk_state else None
        daily_pnl_percent = risk_state.daily_pnl_percent if risk_state else None
        peak_balance = state_snapshot.peak_balance if state_snapshot else None
        drawdown_percent = risk_state.total_drawdown_percent if risk_state else None

        # 3. TimescaleDB: intraday high/low balance from state_snapshots
        high_balance, low_balance = await self._query_high_low_balance(
            account_id, midnight_utc, next_midnight,
        )
        # Fallback if no state_snapshots for the day
        if high_balance is None:
            high_balance = closing_balance
        if low_balance is None:
            low_balance = closing_balance

        # 4. TimescaleDB: daily trade stats
        trades_stats = await self._query_daily_trade_stats(
            account_id, midnight_utc, next_midnight,
        )

        # 5. Derived fields
        drawdown_from_peak = None
        if peak_balance is not None and closing_balance is not None:
            drawdown_from_peak = peak_balance - closing_balance

        return {
            "account_id": account_id,
            "snapshot_date": snapshot_date,
            "snapshot_time": time(0, 0, 0),
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "high_balance": high_balance,
            "low_balance": low_balance,
            "daily_pnl": daily_pnl,
            "daily_pnl_percent": daily_pnl_percent,
            "peak_balance": peak_balance,
            "drawdown_from_peak": drawdown_from_peak,
            "drawdown_percent": drawdown_percent,
            "trades_count": trades_stats["trades_count"],
            "winning_trades": trades_stats["winning_trades"],
            "losing_trades": trades_stats["losing_trades"],
            "total_volume": trades_stats["total_volume"],
        }

    async def _query_high_low_balance(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[Decimal | None, Decimal | None]:
        """Query state_snapshots hypertable for intraday high/low balance."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT MAX(account_balance) AS high, MIN(account_balance) AS low "
                    "FROM state_snapshots "
                    "WHERE account_id = :account_id "
                    "AND timestamp >= :start AND timestamp < :end"
                ),
                {"account_id": account_id, "start": start, "end": end},
            )
            row = result.one_or_none()
            if row and row.high is not None:
                return Decimal(str(row.high)), Decimal(str(row.low))
            return None, None

    async def _query_daily_trade_stats(
        self,
        account_id: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Query trades table for daily trade statistics."""
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    "SELECT "
                    "COUNT(*) AS trades_count, "
                    "COUNT(*) FILTER (WHERE pnl_dollars > 0) AS winning_trades, "
                    "COUNT(*) FILTER (WHERE pnl_dollars < 0) AS losing_trades, "
                    "COALESCE(SUM(quantity), 0) AS total_volume "
                    "FROM trades "
                    "WHERE account_id = :account_id "
                    "AND entry_time >= :start AND entry_time < :end"
                ),
                {"account_id": account_id, "start": start, "end": end},
            )
            row = result.one()
            return {
                "trades_count": row.trades_count or 0,
                "winning_trades": row.winning_trades or 0,
                "losing_trades": row.losing_trades or 0,
                "total_volume": Decimal(str(row.total_volume)) if row.total_volume else Decimal("0"),
            }

    @property
    def is_running(self) -> bool:
        return self._running
