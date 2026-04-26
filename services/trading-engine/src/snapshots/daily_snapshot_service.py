"""Daily Snapshot Service - Firm-session aware scheduler for account snapshots.

Snapshots are taken at the local-midnight (or configured reset_time) of each
firm session. Active accounts are grouped by their resolved
:class:`SessionConfig` and scheduled independently — multi-firm deployments
can mix CET-anchored FTMO accounts with America/New_York-anchored futures
accounts in the same engine.

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
from zoneinfo import ZoneInfo

from sqlalchemy import text

from ..config.firm_profile import SessionConfig
from ..config.firm_registry import FirmRegistryError
from ..config.session_clock import next_reset_at, previous_reset_at
from .snapshot_db_writer import SnapshotDBWriter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from ..accounts.account_manager import AccountManager
    from ..audit.audit_service import AuditService
    from ..config.firm_registry import FirmRegistry
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


DEFAULT_SESSION = SessionConfig(timezone="UTC", reset_time="00:00")


class DailySnapshotService:
    """Collects and persists daily account snapshots at firm-session resets.

    Active accounts are grouped by their resolved
    :class:`SessionConfig` (firm-bound accounts use
    ``FirmProfile.session``; legacy/unbound accounts use
    ``default_session``). One asyncio scheduler task is spawned per unique
    session group.
    """

    def __init__(
        self,
        db_writer: SnapshotDBWriter,
        redis_state: "RedisStateManager",
        account_manager: "AccountManager",
        db_session_factory: "async_sessionmaker",
        audit_service: "AuditService | None" = None,
        firm_registry: "FirmRegistry | None" = None,
        default_session: SessionConfig | None = None,
    ) -> None:
        self._db_writer = db_writer
        self._redis_state = redis_state
        self._account_manager = account_manager
        self._session_factory = db_session_factory
        self._audit_service = audit_service
        self._firm_registry = firm_registry
        self._default_session = default_session or DEFAULT_SESSION
        self._scheduler_tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        groups = self._group_accounts_by_session()
        if not groups:
            # No accounts yet → spawn a single loop on the default session so
            # accounts added later still get snapshotted (each tick re-resolves
            # the live account list).
            groups = {self._default_session: []}

        for session in groups:
            task = asyncio.create_task(
                self._scheduler_loop(session),
                name=f"daily_snapshot_{_safe_tz_name(session.timezone)}",
            )
            self._scheduler_tasks.append(task)

        logger.info(
            "DailySnapshotService started: %d session group(s)",
            len(self._scheduler_tasks),
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for task in self._scheduler_tasks:
            task.cancel()
        for task in self._scheduler_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._scheduler_tasks.clear()
        logger.info("DailySnapshotService stopped")

    # ---------------------------------------------------------------------
    # Scheduling
    # ---------------------------------------------------------------------

    @staticmethod
    def _calculate_seconds_until_next_reset(session: SessionConfig) -> float:
        """Return seconds from now (UTC) until the next session reset."""
        now = datetime.now(timezone.utc)
        return (next_reset_at(session, now) - now).total_seconds()

    async def _scheduler_loop(self, session: SessionConfig) -> None:
        """Sleep until next reset for ``session``, take snapshots, repeat.

        Captures ``target_reset`` BEFORE sleeping so that the snapshot date is
        derived from the intended boundary even if the OS timer wakes us a
        few milliseconds early. After waking, re-sleeps any residual time
        until ``target_reset`` is reached.
        """
        while self._running:
            now = datetime.now(timezone.utc)
            target_reset = next_reset_at(session, now)
            delay = (target_reset - now).total_seconds()
            logger.info(
                "Next snapshot for session %s (%s) in %.0f seconds (at %s UTC)",
                session.timezone,
                session.reset_time,
                delay,
                target_reset.isoformat(),
            )
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            # Guard: re-sleep any residual if OS scheduler woke us early.
            while self._running:
                residual = (target_reset - datetime.now(timezone.utc)).total_seconds()
                if residual <= 0:
                    break
                try:
                    await asyncio.sleep(residual)
                except asyncio.CancelledError:
                    return
            if self._running:
                self._ensure_session_tasks()
                account_ids = self._accounts_for_session(session)
                snapshot_date = self._snapshot_date_for_target(session, target_reset)
                await self._take_snapshots_for_session(
                    session, account_ids, snapshot_date,
                )

    # ---------------------------------------------------------------------
    # Session resolution / grouping
    # ---------------------------------------------------------------------

    def _group_accounts_by_session(self) -> dict[SessionConfig, list[str]]:
        groups: dict[SessionConfig, list[str]] = {}
        for account_id in self._account_manager.get_active_account_ids():
            session = self._resolve_session_for_account(account_id)
            groups.setdefault(session, []).append(account_id)
        return groups

    def _resolve_session_for_account(self, account_id: str) -> SessionConfig:
        if self._firm_registry is None:
            return self._default_session
        account = self._account_manager.get_account(account_id)
        firm_id = getattr(account, "firm_id", None) if account is not None else None
        if firm_id is None:
            return self._default_session
        try:
            firm = self._firm_registry.get(firm_id)
        except FirmRegistryError:
            logger.warning(
                "Firm %s not in registry for account %s; "
                "falling back to default session %s",
                firm_id, account_id, self._default_session.timezone,
            )
            return self._default_session
        return firm.session

    def _accounts_for_session(self, session: SessionConfig) -> list[str]:
        return [
            aid
            for aid in self._account_manager.get_active_account_ids()
            if self._resolve_session_for_account(aid) == session
        ]

    def _snapshot_date_for_session(self, session: SessionConfig) -> date:
        """Return the local date of the trading day that just ended.

        Computed at call time relative to ``datetime.now(UTC)``: the most
        recent reset boundary in the past, then converted back to local
        wall clock to recover the calendar date.
        """
        now = datetime.now(timezone.utc)
        return self._snapshot_date_for_target(session, previous_reset_at(session, now))

    @staticmethod
    def _snapshot_date_for_target(
        session: SessionConfig, target_reset_utc: datetime,
    ) -> date:
        """Return the local date that ended at ``target_reset_utc``.

        Used by the scheduler to derive the snapshot_date deterministically
        from the boundary captured BEFORE the sleep, immune to early-wake
        OS scheduler variance.
        """
        local_just_before = (target_reset_utc - timedelta(seconds=1)).astimezone(
            ZoneInfo(session.timezone)
        )
        return local_just_before.date()

    def _ensure_session_tasks(self) -> None:
        """Spawn scheduler tasks for any session that doesn't yet have one.

        Called each tick so that hot-adding an account whose firm session
        timezone is new (e.g., adding a The5ers/NY account to an engine that
        previously only had FTMO/CET accounts) does not silently drop
        snapshots until restart.
        """
        running_names = {
            t.get_name() for t in self._scheduler_tasks if not t.done()
        }
        for session in self._group_accounts_by_session():
            name = f"daily_snapshot_{_safe_tz_name(session.timezone)}"
            if name in running_names:
                continue
            task = asyncio.create_task(self._scheduler_loop(session), name=name)
            self._scheduler_tasks.append(task)
            logger.warning(
                "Spawned late scheduler task for previously-unseen session: %s",
                session.timezone,
            )

    # ---------------------------------------------------------------------
    # Snapshot collection
    # ---------------------------------------------------------------------

    async def _take_snapshots_for_session(
        self,
        session: SessionConfig,
        account_ids: list[str],
        snapshot_date: date,
    ) -> None:
        """Snapshot every account in ``account_ids`` for ``snapshot_date``.

        IMPORTANT: This must run BEFORE any daily risk state reset
        (RiskState.reset_daily / RedisStateManager.reset_daily_risk_state)
        because it reads daily_pnl and daily_pnl_percent from Redis.
        """
        logger.info(
            "Taking daily snapshots for %d accounts (date: %s, session: %s)",
            len(account_ids), snapshot_date, session.timezone,
        )

        success_count = 0
        for account_id in account_ids:
            try:
                data = await self._collect_snapshot_data(
                    account_id, snapshot_date, session,
                )
                await self._db_writer.write_snapshot(data)
                success_count += 1
                logger.info("Snapshot saved: %s / %s", account_id, snapshot_date)
            except Exception:
                logger.exception("Failed to snapshot account %s", account_id)

        logger.info(
            "Daily snapshots complete: %d/%d succeeded (session: %s)",
            success_count, len(account_ids), session.timezone,
        )

        if self._audit_service and success_count > 0:
            from ..rules.audit_logger import audit_task_done_callback

            task = asyncio.create_task(
                self._audit_service.log_system_event(
                    event_subtype="daily_snapshot",
                    message=(
                        f"Daily snapshots taken: {success_count}/{len(account_ids)} "
                        f"accounts ({session.timezone})"
                    ),
                    context={
                        "snapshot_date": str(snapshot_date),
                        "session_timezone": session.timezone,
                        "session_reset_time": session.reset_time,
                        "success_count": success_count,
                        "total_accounts": len(account_ids),
                    },
                ),
                name="audit_daily_snapshot",
            )
            task.add_done_callback(audit_task_done_callback)

    async def _collect_snapshot_data(
        self,
        account_id: str,
        snapshot_date: date,
        session: SessionConfig | None = None,
    ) -> dict[str, Any]:
        """Gather snapshot data from Redis state + TimescaleDB queries.

        Query window is the trading day identified by ``snapshot_date`` in
        ``session.timezone`` (or UTC if ``session`` is omitted, for tests
        and legacy callers).
        """
        window_start_utc, window_end_utc = _query_window_for_date(
            snapshot_date, session,
        )

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
            account_id, window_start_utc, window_end_utc,
        )
        # Fallback if no state_snapshots for the day
        if high_balance is None:
            high_balance = closing_balance
        if low_balance is None:
            low_balance = closing_balance

        # 4. TimescaleDB: daily trade stats
        trades_stats = await self._query_daily_trade_stats(
            account_id, window_start_utc, window_end_utc,
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


def _query_window_for_date(
    snapshot_date: date,
    session: SessionConfig | None,
) -> tuple[datetime, datetime]:
    """Return UTC ``(start, end)`` for the trading day identified by date+session.

    ``start`` is the local reset boundary at the beginning of ``snapshot_date``;
    ``end`` is the next local reset boundary on the following calendar day.
    DST is handled by ``ZoneInfo``-aware ``datetime.combine`` — the resulting
    UTC interval is 23h, 24h, or 25h depending on transitions in the window.
    """
    if session is None:
        # Legacy / test path: assume the day spans UTC midnight to UTC midnight.
        start = datetime.combine(snapshot_date, time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        return start, end

    tz = ZoneInfo(session.timezone)
    hour_str, minute_str = session.reset_time.split(":")
    reset_local_time = time(hour=int(hour_str), minute=int(minute_str))
    start_local = datetime.combine(snapshot_date, reset_local_time, tzinfo=tz)
    end_local = datetime.combine(
        snapshot_date + timedelta(days=1), reset_local_time, tzinfo=tz,
    )
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _safe_tz_name(timezone_name: str) -> str:
    """Return a task-name-safe variant of an IANA timezone string."""
    return timezone_name.replace("/", "_")
