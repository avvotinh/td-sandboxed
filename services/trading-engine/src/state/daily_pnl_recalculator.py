"""Daily P&L Recalculator for crash recovery.

This module recalculates daily P&L from trade history after crash recovery.
It queries closed trades from TimescaleDB and combines with unrealized P&L
from reconciled positions to compute accurate daily P&L values.

The recalculated value is used instead of the snapshot value because:
1. Trades may have closed between snapshot and crash
2. Day boundary may have crossed since snapshot
3. Snapshot unrealized P&L is stale

Calculation Formula:
    Daily P&L = Realized P&L + Unrealized P&L

Where:
    Realized P&L = SUM(pnl_dollars) from trades WHERE status='closed' AND
                   exit_time >= last firm-session reset (was: midnight UTC)
    Unrealized P&L = SUM(position.unrealized_pnl) for all open positions (from PnLTracker)

The day boundary is resolved per account from its ``FirmProfile.session``
when a ``FirmRegistry`` and ``AccountManager`` are wired in; legacy /
unbound accounts fall back to UTC midnight.

CRITICAL: All financial calculations use Decimal for precision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError

from ..config.firm_profile import SessionConfig
from ..config.firm_registry import FirmRegistryError
from ..config.session_clock import previous_reset_at

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..accounts.account_manager import AccountManager
    from ..accounts.pnl_registry import PnLTrackerRegistry
    from ..accounts.risk_registry import RiskStateRegistry
    from ..config.firm_registry import FirmRegistry
    from .redis_state import RedisStateManager


_DEFAULT_SESSION = SessionConfig(timezone="UTC", reset_time="00:00")

logger = logging.getLogger(__name__)


@dataclass
class RecalculatedPnL:
    """Result of P&L recalculation from trade history.

    Attributes:
        account_id: Account that was recalculated
        realized_pnl: Sum of P&L from closed trades today
        unrealized_pnl: Sum of unrealized P&L from open positions
        total_daily_pnl: realized_pnl + unrealized_pnl
        trade_count: Number of closed trades used in calculation
        calculation_time: When recalculation was performed
        day_boundary: Midnight UTC used for day boundary
    """

    account_id: str
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_daily_pnl: Decimal
    trade_count: int
    calculation_time: datetime
    day_boundary: datetime


@dataclass
class RecalculationResult:
    """Result of daily P&L recalculation attempt.

    Attributes:
        success: True if recalculation completed successfully
        recalculated: RecalculatedPnL if success, None otherwise
        snapshot_value: Original value from snapshot (for comparison)
        adjustment: Difference between recalculated and snapshot
        error_message: Error details if success=False
    """

    success: bool
    recalculated: RecalculatedPnL | None
    snapshot_value: Decimal
    adjustment: Decimal
    error_message: str | None = None


class DailyPnLRecalculator:
    """Recalculates daily P&L from trade history after crash recovery.

    This recalculator queries the trades table for completed trades
    since midnight UTC and adds unrealized P&L from reconciled positions.

    The recalculated value is used instead of the snapshot value because:
    1. Trades may have closed between snapshot and crash
    2. Day boundary may have crossed since snapshot
    3. Snapshot unrealized P&L is stale

    CRITICAL: Always use Decimal for financial calculations.

    Example:
        recalculator = DailyPnLRecalculator(
            db_session_factory=session_factory,
            redis_manager=redis,
            risk_registry=risk_registry,
            pnl_registry=pnl_registry,
        )

        result = await recalculator.recalculate_daily_pnl(
            account_id="ftmo-001",
            snapshot_daily_pnl=Decimal("-500.00"),
        )

        if result.success:
            await recalculator.apply_recalculation(account_id, result)
    """

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        redis_manager: RedisStateManager,
        risk_registry: RiskStateRegistry,
        pnl_registry: PnLTrackerRegistry,
        firm_registry: FirmRegistry | None = None,
        account_manager: AccountManager | None = None,
    ) -> None:
        """Initialize DailyPnLRecalculator.

        Args:
            db_session_factory: Async session factory for database queries
            redis_manager: Redis state manager for persisting updates
            risk_registry: Risk state registry for updating risk metrics
            pnl_registry: P&L registry for accessing account trackers
            firm_registry: Optional firm registry for resolving per-account
                session timezones (Epic 9 P0.5).
            account_manager: Optional account manager used together with
                ``firm_registry`` to look up an account's ``firm_id``.
        """
        self._session_factory = db_session_factory
        self._redis = redis_manager
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._firm_registry = firm_registry
        self._account_manager = account_manager

    def _resolve_session(self, account_id: str) -> SessionConfig:
        """Return the session config for an account, defaulting to UTC midnight."""
        if self._firm_registry is None or self._account_manager is None:
            return _DEFAULT_SESSION
        account = self._account_manager.get_account(account_id)
        firm_id = getattr(account, "firm_id", None) if account is not None else None
        if firm_id is None:
            return _DEFAULT_SESSION
        try:
            firm = self._firm_registry.get(firm_id)
        except FirmRegistryError:
            logger.warning(
                "Firm %s not in registry for account %s; "
                "falling back to UTC midnight",
                firm_id, account_id,
            )
            return _DEFAULT_SESSION
        return firm.session

    def _get_day_boundary(
        self,
        account_id: str | None = None,
        now: datetime | None = None,
    ) -> datetime:
        """Calculate the start of the current trading day in UTC.

        For firm-bound accounts, this is the most recent reset boundary in
        the firm's session timezone. Otherwise it is midnight UTC.

        Args:
            account_id: Account whose firm session governs the boundary.
                If omitted (or no firm_registry/account_manager wired in),
                falls back to UTC midnight for backwards compatibility.
            now: Optional datetime to use as current time (for testing).

        Returns:
            UTC datetime of the most recent reset at or before ``now``.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        session = (
            self._resolve_session(account_id)
            if account_id is not None
            else _DEFAULT_SESSION
        )
        return previous_reset_at(session, now)

    async def _query_realized_pnl(
        self,
        account_id: str,
        day_boundary: datetime,
    ) -> tuple[Decimal, int]:
        """Query sum of realized P&L from closed trades since midnight UTC.

        SQL equivalent:
        SELECT COALESCE(SUM(pnl_dollars), 0), COUNT(*)
        FROM trades
        WHERE account_id = :account_id
          AND status = 'closed'
          AND exit_time >= :day_boundary

        Args:
            account_id: Account to query trades for
            day_boundary: Midnight UTC of current trading day

        Returns:
            (realized_pnl, trade_count) tuple
            realized_pnl: Sum of pnl_dollars from closed trades
            trade_count: Number of trades used in sum

        Raises:
            SQLAlchemyError: On database connection/query failure
        """
        from ..orders.db_models import TradeRecord

        async with self._session_factory() as session:
            stmt = select(
                func.coalesce(func.sum(TradeRecord.pnl_dollars), 0).label("total_pnl"),
                func.count().label("trade_count"),
            ).where(
                and_(
                    TradeRecord.account_id == account_id,
                    TradeRecord.status == "closed",
                    TradeRecord.exit_time >= day_boundary,
                )
            )

            result = await session.execute(stmt)
            row = result.one()
            return Decimal(str(row.total_pnl)), row.trade_count

    def _get_unrealized_pnl(self, account_id: str) -> Decimal:
        """Get current unrealized P&L from reconciled positions.

        After Story 5.3 (position reconciliation), the PnLTracker has
        accurate positions matching MT5. This method retrieves the
        total unrealized P&L from those positions.

        ARCHITECTURE: Uses PnLTrackerRegistry to access the account's PnLTracker
        which was updated during position reconciliation.

        Args:
            account_id: Account to get unrealized P&L for

        Returns:
            Total unrealized P&L from open positions (Decimal)
            Returns Decimal("0") if no tracker or no positions
        """
        tracker = self._pnl_registry.get(account_id)
        if tracker is None:
            logger.warning(
                "No PnLTracker found for %s during P&L recalculation",
                account_id,
            )
            return Decimal("0")

        metrics = tracker.get_pnl_metrics()
        return metrics.unrealized_pnl

    async def recalculate_daily_pnl(
        self,
        account_id: str,
        snapshot_daily_pnl: Decimal,
    ) -> RecalculationResult:
        """Recalculate daily P&L from trade history and current positions.

        Called after position reconciliation (Story 5.3) to ensure
        compliance rules use accurate P&L values.

        Calculation:
        1. Determine current day boundary (midnight UTC)
        2. Query realized P&L from closed trades since midnight
        3. Get unrealized P&L from reconciled positions
        4. Total = Realized + Unrealized

        Args:
            account_id: Account to recalculate P&L for
            snapshot_daily_pnl: Daily P&L value from snapshot (for comparison)

        Returns:
            RecalculationResult with success status and recalculated values
        """
        try:
            # 1. Calculate day boundary (firm-session local reset, or UTC midnight)
            now = datetime.now(timezone.utc)
            day_boundary = self._get_day_boundary(account_id, now)

            # 2. Query realized P&L from database
            realized_pnl, trade_count = await self._query_realized_pnl(
                account_id, day_boundary
            )

            # 3. Get unrealized P&L from positions
            unrealized_pnl = self._get_unrealized_pnl(account_id)

            # 4. Calculate total
            total_daily_pnl = realized_pnl + unrealized_pnl

            recalculated = RecalculatedPnL(
                account_id=account_id,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_daily_pnl=total_daily_pnl,
                trade_count=trade_count,
                calculation_time=now,
                day_boundary=day_boundary,
            )

            adjustment = total_daily_pnl - snapshot_daily_pnl

            # 5. Log if adjustment occurred (AC2)
            if adjustment != Decimal("0"):
                logger.info(
                    "Daily P&L adjusted from snapshot: %s → %s (adjustment: %s)",
                    snapshot_daily_pnl,
                    total_daily_pnl,
                    adjustment,
                )

            return RecalculationResult(
                success=True,
                recalculated=recalculated,
                snapshot_value=snapshot_daily_pnl,
                adjustment=adjustment,
            )

        except SQLAlchemyError as e:
            # AC6: Database error - fall back to snapshot value
            logger.warning(
                "P&L recalculation failed for %s due to database error, "
                "using snapshot value: %s",
                account_id,
                e,
            )
            return RecalculationResult(
                success=False,
                recalculated=None,
                snapshot_value=snapshot_daily_pnl,
                adjustment=Decimal("0"),
                error_message=f"Database error: {e}",
            )
        except Exception as e:
            # General error - fall back to snapshot value
            logger.warning(
                "P&L recalculation failed for %s, using snapshot value: %s",
                account_id,
                e,
            )
            return RecalculationResult(
                success=False,
                recalculated=None,
                snapshot_value=snapshot_daily_pnl,
                adjustment=Decimal("0"),
                error_message=str(e),
            )

    async def _update_risk_state(
        self,
        account_id: str,
        recalculated: RecalculatedPnL,
    ) -> None:
        """Update risk state with recalculated daily P&L.

        Updates:
        1. RiskStateRegistry (in-memory risk state)
        2. Redis risk state (persistent)

        Args:
            account_id: Account to update
            recalculated: Recalculated P&L values
        """
        # 1. Get current risk state
        risk_state = self._risk_registry.get_risk_state(account_id)
        if risk_state is None:
            logger.error("No risk state found for %s during P&L update", account_id)
            return

        # 2. Update risk state values
        risk_state.daily_pnl = recalculated.total_daily_pnl
        if risk_state.daily_starting_balance > 0:
            risk_state.daily_pnl_percent = (
                recalculated.total_daily_pnl / risk_state.daily_starting_balance * 100
            )

        # 3. Persist to Redis (AC5)
        await self._redis.save_risk_state(account_id, risk_state)

        logger.info(
            "Risk state updated for %s: daily_pnl=%s, daily_pnl_percent=%s%%",
            account_id,
            recalculated.total_daily_pnl,
            risk_state.daily_pnl_percent,
        )

    async def apply_recalculation(
        self,
        account_id: str,
        result: RecalculationResult,
    ) -> None:
        """Apply recalculation result to all state stores.

        Only called if recalculation was successful.
        Updates risk registry, Redis, and P&L tracker.

        Args:
            account_id: Account to update
            result: Successful recalculation result
        """
        if not result.success or result.recalculated is None:
            logger.debug(
                "Skipping state update for %s - recalculation failed",
                account_id,
            )
            return

        await self._update_risk_state(account_id, result.recalculated)
