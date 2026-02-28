"""Report data gathering - queries DB and computes summary statistics."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from .models import ReportData, ReportSummary


class ReportDataGatherer:
    """Gathers data from TimescaleDB and computes report summaries."""

    async def gather(
        self,
        session: Any,
        account_id: str,
        since: date | None = None,
        until: date | None = None,
    ) -> ReportData:
        """Gather all report data for an account.

        Reuses query patterns from src/cli/audit.py.

        Args:
            session: AsyncSession from SQLAlchemy.
            account_id: Account ID to query.
            since: Start date filter (inclusive). None means all history.
            until: End date filter (inclusive). None means today.

        Returns:
            ReportData with all gathered data and computed summary.
        """
        from sqlalchemy import select

        from ..orders.db_models import TradeRecord
        from ..rules.violation_db_writer import RuleViolationModel
        from ..snapshots.models import AccountSnapshotModel

        period_end = until or date.today()
        period_start = since or date(2000, 1, 1)

        # Query trades
        trade_stmt = select(TradeRecord).where(
            TradeRecord.account_id == account_id,
        )
        if since is not None:
            since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
            trade_stmt = trade_stmt.where(TradeRecord.entry_time >= since_dt)
        if until is not None:
            until_dt = datetime(
                until.year, until.month, until.day, 23, 59, 59, tzinfo=timezone.utc
            )
            trade_stmt = trade_stmt.where(TradeRecord.entry_time <= until_dt)
        trade_stmt = trade_stmt.order_by(TradeRecord.entry_time.desc())
        trades = (await session.scalars(trade_stmt)).all()

        # Query violations
        violation_stmt = select(RuleViolationModel).where(
            RuleViolationModel.account_id == account_id,
        )
        if since is not None:
            since_dt = datetime(since.year, since.month, since.day, tzinfo=timezone.utc)
            violation_stmt = violation_stmt.where(
                RuleViolationModel.timestamp >= since_dt
            )
        if until is not None:
            until_dt = datetime(
                until.year, until.month, until.day, 23, 59, 59, tzinfo=timezone.utc
            )
            violation_stmt = violation_stmt.where(
                RuleViolationModel.timestamp <= until_dt
            )
        violation_stmt = violation_stmt.order_by(RuleViolationModel.timestamp.desc())
        violations = (await session.scalars(violation_stmt)).all()

        # Query snapshots
        snapshot_stmt = select(AccountSnapshotModel).where(
            AccountSnapshotModel.account_id == account_id,
        )
        if since is not None:
            snapshot_stmt = snapshot_stmt.where(
                AccountSnapshotModel.snapshot_date >= since
            )
        if until is not None:
            snapshot_stmt = snapshot_stmt.where(
                AccountSnapshotModel.snapshot_date <= until
            )
        snapshot_stmt = snapshot_stmt.order_by(AccountSnapshotModel.snapshot_date.asc())
        snapshots = (await session.scalars(snapshot_stmt)).all()

        summary = _compute_summary(trades, violations, snapshots, period_start, period_end)

        return ReportData(
            account_id=account_id,
            period_start=period_start,
            period_end=period_end,
            generated_at=datetime.now(timezone.utc),
            trades=list(trades),
            violations=list(violations),
            snapshots=list(snapshots),
            summary=summary,
        )


def _compute_summary(
    trades: list[Any],
    violations: list[Any],
    snapshots: list[Any],
    period_start: date,
    period_end: date,
) -> ReportSummary:
    """Compute report summary from gathered data.

    Args:
        trades: List of TradeRecord instances.
        violations: List of RuleViolationModel instances.
        snapshots: List of AccountSnapshotModel instances.
        period_start: Report period start date.
        period_end: Report period end date.

    Returns:
        ReportSummary with computed metrics.
    """
    # Trade stats
    total_trades = len(trades)
    winning = 0
    losing = 0
    net_pnl = Decimal("0")

    for t in trades:
        if t.pnl_dollars is not None:
            net_pnl += t.pnl_dollars
            if t.pnl_dollars > 0:
                winning += 1
            elif t.pnl_dollars < 0:
                losing += 1

    closed = winning + losing
    win_rate = (
        Decimal(str(round((winning / closed) * 100, 2))) if closed > 0 else Decimal("0")
    )

    # Snapshot stats
    trading_days = 0
    best_day_pnl = Decimal("0")
    worst_day_pnl = Decimal("0")
    worst_day_pnl_percent = Decimal("0")
    opening_balance = Decimal("0")
    closing_balance = Decimal("0")
    peak_balance = Decimal("0")
    max_drawdown_percent = Decimal("0")
    current_drawdown_percent = Decimal("0")

    if snapshots:
        # Snapshots are ordered by date ascending
        first_snapshot = snapshots[0]
        last_snapshot = snapshots[-1]

        opening_balance = first_snapshot.opening_balance or Decimal("0")
        closing_balance = last_snapshot.closing_balance or Decimal("0")

        for s in snapshots:
            if s.trades_count and s.trades_count > 0:
                trading_days += 1
            if s.daily_pnl is not None:
                if s.daily_pnl > best_day_pnl:
                    best_day_pnl = s.daily_pnl
                if s.daily_pnl < worst_day_pnl:
                    worst_day_pnl = s.daily_pnl
            if s.daily_pnl_percent is not None:
                if s.daily_pnl_percent < worst_day_pnl_percent:
                    worst_day_pnl_percent = s.daily_pnl_percent
            if s.peak_balance is not None and s.peak_balance > peak_balance:
                peak_balance = s.peak_balance
            if s.drawdown_percent is not None:
                if s.drawdown_percent > max_drawdown_percent:
                    max_drawdown_percent = s.drawdown_percent

        current_drawdown_percent = last_snapshot.drawdown_percent or Decimal("0")

    calendar_days = (period_end - period_start).days + 1

    # Violation stats
    total_violations = len(violations)
    blocked_count = 0
    violations_by_rule: dict[str, int] = {}

    for v in violations:
        if v.order_blocked:
            blocked_count += 1
        violations_by_rule[v.rule_type] = violations_by_rule.get(v.rule_type, 0) + 1

    return ReportSummary(
        total_trades=total_trades,
        winning_trades=winning,
        losing_trades=losing,
        win_rate=win_rate,
        net_pnl=net_pnl,
        best_day_pnl=best_day_pnl,
        worst_day_pnl=worst_day_pnl,
        worst_day_pnl_percent=worst_day_pnl_percent,
        trading_days=trading_days,
        calendar_days=calendar_days,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        peak_balance=peak_balance,
        max_drawdown_percent=max_drawdown_percent,
        current_drawdown_percent=current_drawdown_percent,
        total_violations=total_violations,
        blocked_count=blocked_count,
        violations_by_rule=violations_by_rule,
    )
